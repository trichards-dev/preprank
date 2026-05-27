"""Step 1b diagnostic — Boys Soccer cold-start vs non-cold-start gap split.

Triggered by Step 1a: Phase 2 baseline CI excludes 0 (gap=+0.0281,
CI=[+0.0007, +0.0592], p=0.0440 uncorrected). Phase 4b CI straddles 0 so
Step 1b does NOT fire on that variant — see Reese 2026-05-27 sign-off
for the strict-rule rationale.

Question from Reese 2026-05-26 / 2026-05-27:

    "Cold-start vs non-cold-start split: if the gap is concentrated in
     cold-start games (early-season, prior-year-missing teams), then
     division-median fallback IS load-bearing and Option A is right
     after all. If the gap is uniform across cold-start and non-cold-
     start, the gap isn't about division coverage."

Cold-start definition
---------------------
Per the runner's PredictionRecord schema, a side is "cold-start" when
``prior_year_rating is None`` — i.e., the team has no prior season's
final rating, so ``_resolve_pregame_rating`` falls back to either the
in-season engine rating (after week 1 it kicks in) or the
division-median (for week 1 with no prior-year data). A game is
"cold-start" when EITHER team is cold-start.

Slices reported
---------------
1. Within-holdout accuracy by cold-start status — does the model do
   materially worse on cold-start games in the holdout?
2. Within-subset (train_acc - hold_acc) gap — does the Phase 2 +0.0281
   gap concentrate in the cold-start subset, the non-cold-start subset,
   or distribute uniformly?
3. Secondary slice by week 1 vs week 2+ — captures the "early-season"
   half of Reese's phrasing (early-season is partially-but-not-fully
   collinear with cold-start, since week-1 games may also involve
   warm-start teams that played last season).

Bootstrap CIs are computed per subset (two-sample independent bootstrap,
same construction as Step 1a) on the within-subset gap. The "gap
concentrates in cold-start" hypothesis predicts CI on the cold-start
gap strictly exceeds the non-cold-start gap CI.

Inputs
------
Reads ``predictions_phase2.jsonl`` from the latest Step 1a run dir (or
from a directory passed via --step1a-dir). No refit; uses the persisted
per-game (p_home, actual_home_won, home_cold_start, away_cold_start,
week_number, season_year, fold) records.

Output: reports/walk_forward/boys-soccer-step1b-coldstart-split/<ts>/
{summary.json, report.md}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))

import numpy as np


SPORT = "Boys Soccer"


def _two_sample_diff_bootstrap(
    train_correct: np.ndarray,
    hold_correct: np.ndarray,
    *,
    n_resamples: int,
    seed: int,
) -> tuple[float, tuple[float, float], np.ndarray]:
    """Same construction as Step 1a — for parity of method."""
    rng = np.random.default_rng(seed)
    n_t = len(train_correct)
    n_h = len(hold_correct)
    if n_t == 0 or n_h == 0:
        return float("nan"), (float("nan"), float("nan")), np.array([])
    diffs = np.empty(n_resamples, dtype=np.float64)
    for i in range(n_resamples):
        t_idx = rng.integers(0, n_t, size=n_t)
        h_idx = rng.integers(0, n_h, size=n_h)
        t_acc = float(train_correct[t_idx].mean())
        h_acc = float(hold_correct[h_idx].mean())
        diffs[i] = t_acc - h_acc
    observed = float(train_correct.mean()) - float(hold_correct.mean())
    lo, hi = float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))
    return observed, (lo, hi), diffs


def _hold_acc_bootstrap_ci(
    hold_correct: np.ndarray, *, n_resamples: int, seed: int,
) -> tuple[float, tuple[float, float]]:
    rng = np.random.default_rng(seed)
    n = len(hold_correct)
    if n == 0:
        return float("nan"), (float("nan"), float("nan"))
    accs = np.empty(n_resamples, dtype=np.float64)
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        accs[i] = float(hold_correct[idx].mean())
    return float(hold_correct.mean()), (
        float(np.quantile(accs, 0.025)),
        float(np.quantile(accs, 0.975)),
    )


def _load_preds(jsonl_path: Path) -> tuple[list[dict], list[dict]]:
    train, hold = [], []
    with jsonl_path.open() as f:
        for line in f:
            rec = json.loads(line)
            (train if rec["fold"] == "train" else hold).append(rec)
    return train, hold


def _correct_array(records: list[dict]) -> np.ndarray:
    return np.array(
        [1.0 if (r["p_home"] >= 0.5) == r["actual_home_won"] else 0.0
         for r in records],
        dtype=np.float64,
    )


def _coldstart_mask(records: list[dict]) -> np.ndarray:
    return np.array(
        [bool(r["home_cold_start"] or r["away_cold_start"]) for r in records],
        dtype=bool,
    )


def _week_mask(records: list[dict], *, predicate) -> np.ndarray:
    return np.array([bool(predicate(int(r["week_number"]))) for r in records], dtype=bool)


def _slice_stats(
    label: str,
    train_records: list[dict],
    hold_records: list[dict],
    train_mask: np.ndarray,
    hold_mask: np.ndarray,
    *,
    n_resamples: int,
    seed: int,
) -> dict:
    train_correct = _correct_array(train_records)[train_mask]
    hold_correct = _correct_array(hold_records)[hold_mask]
    gap, (gap_lo, gap_hi), _ = _two_sample_diff_bootstrap(
        train_correct, hold_correct, n_resamples=n_resamples, seed=seed,
    )
    hold_acc, (hold_lo, hold_hi) = _hold_acc_bootstrap_ci(
        hold_correct, n_resamples=n_resamples, seed=seed + 7,
    )
    return {
        "slice": label,
        "n_train": int(len(train_correct)),
        "n_holdout": int(len(hold_correct)),
        "train_accuracy": float(train_correct.mean()) if len(train_correct) else float("nan"),
        "holdout_accuracy": hold_acc,
        "holdout_accuracy_ci": [hold_lo, hold_hi],
        "gap_train_minus_holdout": gap,
        "gap_ci_95": [gap_lo, gap_hi],
        "gap_ci_straddles_zero": (
            (gap_lo <= 0.0 <= gap_hi)
            if not (np.isnan(gap_lo) or np.isnan(gap_hi)) else None
        ),
    }


def _find_latest_step1a_dir(reports_root: Path) -> Path:
    p = reports_root / "boys-soccer-step1a-gap-diagnostic"
    if not p.exists():
        raise FileNotFoundError(f"no Step 1a runs under {p}")
    subdirs = sorted([d for d in p.iterdir() if d.is_dir()], reverse=True)
    if not subdirs:
        raise FileNotFoundError(f"no run dirs under {p}")
    return subdirs[0]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python scripts/audit/boys_soccer_step1b_coldstart_split.py",
        description="Step 1b: Boys Soccer cold-start vs non-cold-start gap split (Phase 2 variant)",
    )
    p.add_argument("--step1a-dir", default=None,
                   help="Step 1a run dir. Defaults to most recent.")
    p.add_argument("--reports-root", default="reports/walk_forward")
    p.add_argument("--output-root", default="reports/walk_forward")
    p.add_argument("--config-label", default="boys-soccer-step1b-coldstart-split")
    p.add_argument("--n-bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    reports_root = Path(args.reports_root)
    step1a_dir = Path(args.step1a_dir) if args.step1a_dir else _find_latest_step1a_dir(reports_root)
    preds_path = step1a_dir / "predictions_phase2.jsonl"
    if not preds_path.exists():
        print(f"[step1b] ERROR — predictions_phase2.jsonl not found at {preds_path}")
        return 2

    print(f"[step1b] reading: {preds_path}")
    train_records, hold_records = _load_preds(preds_path)
    print(f"[step1b] n_train={len(train_records)} n_hold={len(hold_records)}")

    train_cold_mask = _coldstart_mask(train_records)
    hold_cold_mask = _coldstart_mask(hold_records)
    train_warm_mask = ~train_cold_mask
    hold_warm_mask = ~hold_cold_mask

    train_w1_mask = _week_mask(train_records, predicate=lambda w: w == 1)
    hold_w1_mask = _week_mask(hold_records, predicate=lambda w: w == 1)
    train_wlate_mask = ~train_w1_mask
    hold_wlate_mask = ~hold_w1_mask

    t0 = time.time()

    slices = []
    slices.append(_slice_stats(
        "ALL", train_records, hold_records,
        np.ones(len(train_records), dtype=bool),
        np.ones(len(hold_records), dtype=bool),
        n_resamples=args.n_bootstrap, seed=args.seed,
    ))
    slices.append(_slice_stats(
        "COLD-START (either team prior_year_rating=None)",
        train_records, hold_records,
        train_cold_mask, hold_cold_mask,
        n_resamples=args.n_bootstrap, seed=args.seed + 1,
    ))
    slices.append(_slice_stats(
        "NON-COLD-START (both teams have prior_year_rating)",
        train_records, hold_records,
        train_warm_mask, hold_warm_mask,
        n_resamples=args.n_bootstrap, seed=args.seed + 2,
    ))
    slices.append(_slice_stats(
        "WEEK 1 only",
        train_records, hold_records,
        train_w1_mask, hold_w1_mask,
        n_resamples=args.n_bootstrap, seed=args.seed + 3,
    ))
    slices.append(_slice_stats(
        "WEEK 2+ only",
        train_records, hold_records,
        train_wlate_mask, hold_wlate_mask,
        n_resamples=args.n_bootstrap, seed=args.seed + 4,
    ))

    elapsed = time.time() - t0

    # Look up cold / warm gaps for the verdict logic
    by_label = {s["slice"]: s for s in slices}
    gap_cold = by_label["COLD-START (either team prior_year_rating=None)"]["gap_train_minus_holdout"]
    gap_warm = by_label["NON-COLD-START (both teams have prior_year_rating)"]["gap_train_minus_holdout"]
    ci_cold = by_label["COLD-START (either team prior_year_rating=None)"]["gap_ci_95"]
    ci_warm = by_label["NON-COLD-START (both teams have prior_year_rating)"]["gap_ci_95"]

    n_cold_hold = by_label["COLD-START (either team prior_year_rating=None)"]["n_holdout"]
    n_warm_hold = by_label["NON-COLD-START (both teams have prior_year_rating)"]["n_holdout"]

    # ----- artifacts -----
    now = datetime.utcnow()
    out_root = Path(args.output_root)
    run_dir = out_root / args.config_label / now.strftime("%Y-%m-%d-%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "diagnostic": "Step 1b — Boys Soccer Phase 2 cold-start vs non-cold-start gap split",
        "sport": SPORT,
        "source_step1a_dir": str(step1a_dir),
        "variant": "phase2_baseline_no_recent_form",
        "timestamp_utc": now.isoformat(),
        "bootstrap_n_resamples": args.n_bootstrap,
        "bootstrap_seed": args.seed,
        "slices": slices,
        "cold_start_holdout_share": (
            n_cold_hold / (n_cold_hold + n_warm_hold) if (n_cold_hold + n_warm_hold) else float("nan")
        ),
        "wall_time_sec": elapsed,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    # Markdown
    lines: list[str] = []
    lines.append("# Step 1b — Boys Soccer Phase 2 cold-start vs non-cold-start gap split")
    lines.append("")
    lines.append(f"Run timestamp (UTC): {now.isoformat()}")
    try:
        rel = step1a_dir.resolve().relative_to(REPO_ROOT)
        step1a_display = str(rel)
    except ValueError:
        step1a_display = str(step1a_dir)
    lines.append(f"Source Step 1a dir: `{step1a_display}`")
    lines.append(f"Variant: phase2_baseline_no_recent_form (the +0.0281 model — strict-rule trigger)")
    lines.append(f"Wall-clock: {elapsed:.1f} sec")
    lines.append("")
    lines.append("## Per-slice train-vs-holdout gap")
    lines.append("")
    lines.append("| Slice | n_train | n_holdout | train_acc | hold_acc | hold_acc 95% CI | gap | gap 95% CI | gap straddles 0 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|:---:|")
    for s in slices:
        if s["n_train"] == 0 or s["n_holdout"] == 0:
            lines.append(f"| {s['slice']} | {s['n_train']} | {s['n_holdout']} | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        h_ci = f"[{s['holdout_accuracy_ci'][0]:.4f}, {s['holdout_accuracy_ci'][1]:.4f}]"
        g_ci = f"[{s['gap_ci_95'][0]:+.4f}, {s['gap_ci_95'][1]:+.4f}]"
        straddle = "YES" if s["gap_ci_straddles_zero"] else "no"
        lines.append(
            f"| {s['slice']} | {s['n_train']} | {s['n_holdout']} | "
            f"{s['train_accuracy']:.4f} | {s['holdout_accuracy']:.4f} | {h_ci} | "
            f"{s['gap_train_minus_holdout']:+.4f} | {g_ci} | {straddle} |"
        )
    lines.append("")
    lines.append(f"Holdout cold-start share: {summary['cold_start_holdout_share']:.4f}")
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    cold_excludes_zero = (
        ci_cold[0] is not None
        and not np.isnan(ci_cold[0])
        and (ci_cold[0] > 0 or ci_cold[1] < 0)
    )
    warm_excludes_zero = (
        ci_warm[0] is not None
        and not np.isnan(ci_warm[0])
        and (ci_warm[0] > 0 or ci_warm[1] < 0)
    )

    if cold_excludes_zero and not warm_excludes_zero:
        lines.append(
            "**Cold-start gap CI excludes 0; non-cold-start gap CI straddles 0.** "
            "The +0.0281 Phase 2 gap concentrates in cold-start games. Division-median "
            "fallback IS load-bearing for those games. Option A (Firecrawl PDF parse + "
            "refresh_team_divisions for 2025 Soccer) is **retrospectively justified for "
            "the cold-start subset** — recommend proceeding with Steps 3-5 as scoped to "
            "cold-start coverage improvement, with re-fit confirming cold-start "
            "subset accuracy specifically improves."
        )
    elif warm_excludes_zero and not cold_excludes_zero:
        lines.append(
            "**Non-cold-start gap CI excludes 0; cold-start gap CI straddles 0.** "
            "The +0.0281 gap lives in the non-cold-start subset. Division-coverage "
            "improvement (Option A) would NOT address the source of the gap. The gap "
            "has a different cause; investigate further before any Option-A-style "
            "remediation. Cold-start handling can be deferred."
        )
    elif cold_excludes_zero and warm_excludes_zero:
        lines.append(
            "**Both subset gap CIs exclude 0.** The +0.0281 gap is broad-based — present "
            "in both cold-start and non-cold-start games. Compare the magnitudes: if "
            f"|gap_cold|={abs(gap_cold):.4f} is materially larger than |gap_warm|={abs(gap_warm):.4f}, "
            "cold-start handling is part of the story but not all of it; if comparable, "
            "the gap is uniformly distributed and not driven by cold-start. Either way, "
            "Option A alone wouldn't close it."
        )
    else:
        lines.append(
            "**Both subset gap CIs straddle 0.** The +0.0281 gap does not survive "
            "subsetting in either direction — it appears to be a small overall effect "
            "that disperses into noise within each subset. **Boys-Soccer-specific noise; "
            "Option A is NOT justified by this diagnostic.** Phase 4c can proceed without "
            "Option A remediation. The Phase 2 +0.0281 anomaly stays on the open-questions "
            "log as 'uncharacterized but bounded' rather than 'data drift.'"
        )

    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "- Same bootstrap method as Step 1a (two-sample independent — train and holdout "
        "are disjoint, paired bootstrap undefined)."
    )
    lines.append(
        "- Cold-start definition: `EITHER team has prior_year_rating = None`. A team is "
        "cold-start in any week if the prior-season final rating is missing. The runner "
        "uses division-median fallback in this case for week 1; from week 2 onward, the "
        "in-season engine rating populates regardless."
    )
    lines.append(
        "- Week-1 slice is reported separately because Reese's prompt phrased the "
        "concern as 'early-season, prior-year-missing teams' — these are partially-but-"
        "not-fully collinear conditions (week 1 includes warm-start teams too)."
    )
    lines.append(
        "- p-values are not reported per subset because the strict-rule trigger has "
        "already fired at Step 1a; Step 1b is *characterization*, not gatekeeping."
    )
    lines.append("")
    lines.append("External-release status: INTERNAL only. No external numbers leave the office "
                 "pre-candidate-final per decisions.md TASK 3 output discipline.")
    (run_dir / "report.md").write_text("\n".join(lines))

    # ----- console -----
    print()
    print("=" * 90)
    print(f"{'slice':55} {'n_h':>5} {'train':>7} {'hold':>7} {'gap':>8}  {'95% CI':>22}  straddle0")
    for s in slices:
        if s["n_holdout"] == 0:
            continue
        g_ci = f"[{s['gap_ci_95'][0]:+.4f}, {s['gap_ci_95'][1]:+.4f}]"
        straddle = "YES" if s["gap_ci_straddles_zero"] else "no"
        print(
            f"{s['slice']:55} {s['n_holdout']:>5} {s['train_accuracy']:>7.4f} "
            f"{s['holdout_accuracy']:>7.4f} {s['gap_train_minus_holdout']:>+8.4f}  "
            f"{g_ci:>22}  {straddle}"
        )
    print()
    print(f"[step1b] holdout cold-start share = {summary['cold_start_holdout_share']:.4f}")
    print(f"[step1b] artifacts -> {run_dir}")
    print(f"[step1b] wall-clock: {elapsed:.1f} sec")
    print()
    print("Halting after Step 1b per Reese 2026-05-27 sequencing.")
    print("Do not chain into Boys Soccer leakage audit without sign-off.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
