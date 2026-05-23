"""Command-line interface for the validator.

Usage:
    python -m engine.validator run --config baseline --sports all --seasons 2021-2025
    python -m engine.validator run --config baseline --sports football --seasons 2025
    python -m engine.validator diff baseline phase-2a
    python -m engine.validator list

Flags:
    --sports         comma-separated names or 'all'
    --seasons        2021-2025, 2025, or 2021,2024
    --no-write       skip DB writes (smoke testing)
    --output-dir     overrides default 'reports/'
    --no-bootstrap   set bootstrap resamples to 0 (skip CIs)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from engine.prediction.config import PredictionConfig

from .data import ALL_SPORTS

# Default grid of candidate margin-weight (alpha) values; small/cheap by design.
DEFAULT_MARGIN_WEIGHT_GRID: list[float] = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]

# Default grid for the Phase-2b recent-form alpha. Same scale as margin since
# both signals are in capped-margin units.
DEFAULT_FORM_WEIGHT_GRID: list[float] = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]

# Phase-2a fitted-parameter file. Lives inside the package so CLI consumers
# pick it up without extra config wiring.
FITTED_PARAMS_PATH: Path = (
    Path(__file__).resolve().parents[1] / "prediction" / "fitted_params.json"
)


def _load_fitted_params(path: Path = FITTED_PARAMS_PATH) -> dict:
    """Return ``fitted_params.json`` as a dict, or ``{}`` if missing/empty."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text()) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _build_config_for_label(label: str) -> PredictionConfig:
    """Construct the ``PredictionConfig`` matching the given CLI ``--config`` label.

    ``baseline`` -> default config. ``phase-2a`` -> margin feature enabled
    with per-sport weights loaded from ``fitted_params.json`` (falls back
    to the default scalar ``margin_weight`` if no fitted file is present,
    but in practice the fit step should be run first). ``phase-2b`` ->
    margin + recent_form, both with per-sport weights from
    ``fitted_params.json``.
    """
    if label == "baseline":
        return PredictionConfig.baseline()
    if label == "phase-2a":
        fitted = _load_fitted_params()
        margin_weight_by_sport = fitted.get("margin_weight_by_sport", {}) or {}
        return PredictionConfig(
            enabled_features=["margin"],
            margin_weight_by_sport={
                str(k): float(v) for k, v in margin_weight_by_sport.items()
            },
        )
    if label == "phase-2b":
        fitted = _load_fitted_params()
        margin_weight_by_sport = fitted.get("margin_weight_by_sport", {}) or {}
        form_weight_by_sport = fitted.get("form_weight_by_sport", {}) or {}
        return PredictionConfig(
            enabled_features=["margin", "recent_form"],
            margin_weight_by_sport={
                str(k): float(v) for k, v in margin_weight_by_sport.items()
            },
            form_weight_by_sport={
                str(k): float(v) for k, v in form_weight_by_sport.items()
            },
        )
    return PredictionConfig()


def _parse_sports(arg: str) -> list[str]:
    if arg.lower() == "all":
        return list(ALL_SPORTS)
    names = [s.strip() for s in arg.split(",") if s.strip()]
    # Case-insensitive match against canonical names
    canonical = {n.lower(): n for n in ALL_SPORTS}
    out: list[str] = []
    for n in names:
        c = canonical.get(n.lower())
        if c is None:
            raise SystemExit(f"Unknown sport: {n!r}. Known: {', '.join(ALL_SPORTS)}")
        out.append(c)
    return out


def _parse_seasons(arg: str) -> list[int]:
    arg = arg.strip()
    if "-" in arg and "," not in arg:
        lo, hi = arg.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    if "," in arg:
        return sorted({int(s.strip()) for s in arg.split(",") if s.strip()})
    return [int(arg)]


def _cmd_run(args: argparse.Namespace) -> int:
    from .runner import run_validation

    sports = _parse_sports(args.sports) if args.sports else None
    seasons = _parse_seasons(args.seasons) if args.seasons else None
    holdout = _parse_seasons(args.holdout) if args.holdout else None
    n_boot = 0 if args.no_bootstrap else args.bootstrap

    config = _build_config_for_label(args.config)

    result = run_validation(
        config=config,
        config_label=args.config,
        sports=sports,
        seasons=seasons,
        holdout_seasons=holdout,
        write_to_db=not args.no_write,
        output_dir=Path(args.output_dir),
        n_bootstrap=n_boot,
    )
    print(f"Run {result.run_id} complete. {result.n_predictions} predictions.")
    if result.output_dir:
        print(f"Artifacts: {result.output_dir}")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    from .diff import diff

    payload = diff(
        config_a=args.config_a,
        config_b=args.config_b,
        output_dir=Path(args.output_dir),
    )
    overall = payload.get("overall", {}) or {}
    if overall.get("n"):
        print(
            f"acc {payload['config_a']}={overall['acc_a']:.4f} -> "
            f"{payload['config_b']}={overall['acc_b']:.4f} "
            f"(Δ {overall['acc_delta']:+.4f})"
        )
    if "_output_dir" in payload:
        print(f"Diff artifacts: {payload['_output_dir']}")
    return 0


def _parse_grid(arg: str) -> list[float]:
    """Parse a comma-separated grid of floats, e.g. '0.5,1.0,1.5'."""
    return [float(x.strip()) for x in arg.split(",") if x.strip()]


def _cmd_fit(args: argparse.Namespace) -> int:
    """Grid-search per-sport weights for the requested feature and write fitted_params.json.

    ``--feature margin`` is Phase 2a: fit per-sport ``margin_weight`` from
    scratch.

    ``--feature recent_form`` is Phase 2b: fit per-sport ``form_weight``
    on top of already-fit ``margin_weight_by_sport`` (read from
    ``fitted_params.json``). The grid search keeps the margin signal on
    so we measure the marginal lift of form *given* the Phase 2a signal.
    """
    if args.feature not in {"margin", "recent_form"}:
        print(
            f"Unknown --feature {args.feature!r}; expected 'margin' or 'recent_form'.",
            file=sys.stderr,
        )
        return 2

    from .runner import run_validation

    train_seasons = _parse_seasons(args.train_seasons)
    sports = _parse_sports(args.sports) if args.sports else list(ALL_SPORTS)
    default_grid = (
        DEFAULT_MARGIN_WEIGHT_GRID if args.feature == "margin" else DEFAULT_FORM_WEIGHT_GRID
    )
    grid = _parse_grid(args.grid) if args.grid else list(default_grid)

    # Reuse one Supabase client across the whole sweep so we don't re-auth
    # per candidate weight per sport.
    sb = None
    if not args.dry_run:
        from supabase import create_client

        url = os.environ.get("SUPABASE_URL", "https://ywlaekkxkwfznwuupggi.supabase.co")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not key:
            print("SUPABASE_SERVICE_ROLE_KEY env var is required", file=sys.stderr)
            return 2
        sb = create_client(url, key)

    existing = _load_fitted_params()
    existing_margin_w = {
        str(k): float(v)
        for k, v in (existing.get("margin_weight_by_sport") or {}).items()
    }
    existing_form_w = {
        str(k): float(v)
        for k, v in (existing.get("form_weight_by_sport") or {}).items()
    }

    fitted: dict[str, float] = {}
    print(f"Fitting feature={args.feature!r} over sports={sports} train_seasons={train_seasons}")
    print(f"Grid: {grid}")

    for sport in sports:
        best_w: float | None = None
        best_acc: float = -1.0
        for w in grid:
            if args.feature == "margin":
                cfg = PredictionConfig(
                    enabled_features=["margin"],
                    margin_weight_by_sport={sport: float(w)},
                )
                label = f"fit-margin-{sport}-{w}"
            else:
                # Phase 2b: fit form on top of fitted margin. Use the already-fit
                # margin weight for this sport (skip the sport with a warning if
                # we have none — that means Phase 2a wasn't run).
                margin_w = existing_margin_w.get(sport)
                if margin_w is None:
                    print(
                        f"  {sport:<18} skipped (no fitted margin_weight; run "
                        f"`fit --feature margin` first)",
                        file=sys.stderr,
                    )
                    break
                cfg = PredictionConfig(
                    enabled_features=["margin", "recent_form"],
                    margin_weight_by_sport={sport: float(margin_w)},
                    form_weight_by_sport={sport: float(w)},
                )
                label = f"fit-form-{sport}-{w}"
            result = run_validation(
                config=cfg,
                config_label=label,
                sports=[sport],
                seasons=train_seasons,
                # Treat the whole training window as train; no holdout split during fit.
                holdout_seasons=[],
                write_to_db=False,
                output_dir=Path(args.output_dir),
                n_bootstrap=0,
                supabase_client=sb,
            )
            block = result.sports.get(sport, {})
            train_block = block.get("train", {})
            acc = train_block.get("game_winner_acc", 0.0)
            n = train_block.get("n_games", 0)
            print(f"  {sport:<18} w={w:<5} train_acc={acc:.4f} n={n}")
            if acc > best_acc:
                best_acc = acc
                best_w = w
        if best_w is not None:
            fitted[sport] = float(best_w)
            print(f"  -> {sport}: best w={best_w} (train_acc={best_acc:.4f})")

    # Merge into the existing file rather than overwriting other features' weights.
    if args.feature == "margin":
        payload = {
            "margin_weight_by_sport": fitted,
            "form_weight_by_sport": existing_form_w,
        }
    else:
        payload = {
            "margin_weight_by_sport": existing_margin_w,
            "form_weight_by_sport": fitted,
        }
    # Drop empty maps for cleanliness.
    payload = {k: v for k, v in payload.items() if v}
    FITTED_PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FITTED_PARAMS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {FITTED_PARAMS_PATH}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """List the most-recent runs in game_predictions, grouped by config_label."""
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "https://ywlaekkxkwfznwuupggi.supabase.co")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not key:
        print("SUPABASE_SERVICE_ROLE_KEY env var is required", file=sys.stderr)
        return 2
    sb = create_client(url, key)

    res = (
        sb.table("game_predictions")
        .select("config_label,run_id,created_at")
        .order("created_at", desc=True)
        .limit(args.limit)
        .execute()
    )
    seen: dict[tuple[str, str], str] = {}
    for r in res.data or []:
        key_pair = (r["config_label"], r["run_id"])
        if key_pair not in seen:
            seen[key_pair] = r["created_at"]
    print(f"{'config_label':<20} {'run_id':<36} created_at")
    for (cfg, rid), ts in seen.items():
        print(f"{cfg:<20} {rid:<36} {ts}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="engine.validator")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run validator")
    p_run.add_argument("--config", required=True, help="Config label (e.g. 'baseline', 'phase-2a')")
    p_run.add_argument("--sports", default="all", help="Comma-separated names or 'all'")
    p_run.add_argument("--seasons", default="2021-2025", help="2021-2025, 2025, or 2021,2024")
    p_run.add_argument("--holdout", default="2025", help="Holdout seasons (same format as --seasons)")
    p_run.add_argument("--no-write", action="store_true", help="Skip DB writes")
    p_run.add_argument("--output-dir", default="reports", help="Where to write artifacts")
    p_run.add_argument("--bootstrap", type=int, default=1000, help="Bootstrap resamples")
    p_run.add_argument("--no-bootstrap", action="store_true", help="Disable bootstrap CIs entirely")
    p_run.set_defaults(func=_cmd_run)

    p_diff = sub.add_parser("diff", help="Diff two prior runs")
    p_diff.add_argument("config_a")
    p_diff.add_argument("config_b")
    p_diff.add_argument("--output-dir", default="reports")
    p_diff.set_defaults(func=_cmd_diff)

    p_list = sub.add_parser("list", help="List prior runs from DB")
    p_list.add_argument("--limit", type=int, default=200)
    p_list.set_defaults(func=_cmd_list)

    p_fit = sub.add_parser(
        "fit",
        help="Fit feature weights from training data, write to fitted_params.json",
    )
    p_fit.add_argument(
        "--feature",
        required=True,
        choices=["margin", "recent_form"],
        help=(
            "Which prediction feature to fit. 'margin' = Phase 2a from scratch; "
            "'recent_form' = Phase 2b on top of already-fit margin weights."
        ),
    )
    p_fit.add_argument(
        "--train-seasons",
        default="2021-2024",
        help="Training seasons (e.g. '2021-2024').",
    )
    p_fit.add_argument(
        "--sports",
        default="all",
        help="Sports to fit, comma-separated or 'all'.",
    )
    p_fit.add_argument(
        "--grid",
        default=None,
        help="Override the default weight grid (e.g. '0.5,1.0,1.5,2.0').",
    )
    p_fit.add_argument(
        "--output-dir",
        default="reports",
        help="Reports dir for in-memory runs (no DB writes).",
    )
    p_fit.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Supabase client construction (useful for tests).",
    )
    p_fit.set_defaults(func=_cmd_fit)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
