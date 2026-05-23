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
import os
import sys
from pathlib import Path

from engine.prediction.config import PredictionConfig

from .data import ALL_SPORTS


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

    config = PredictionConfig.baseline() if args.config == "baseline" else PredictionConfig()

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
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
