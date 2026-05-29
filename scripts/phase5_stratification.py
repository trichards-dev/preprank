"""CLI for Phase 5: Q1-Q4 competitive stratification.

Per v2 plan §5 + Reese 2026-05-29 autonomous queue directive:
  - Fit per-sport with β₃ pinned, β₄/β₅/β₆ free (engine candidate-final
    coefficient configuration).
  - Predict holdout games.
  - Stratify by abs(home_rating - away_rating) into Q1-Q4.
  - Report per-sport per-quartile accuracy + Brier with bootstrap CIs.
  - Headline = Q1 lower-CI (the toss-up bucket; hardest predictions
    and the gate for Phase 7 marketing-claims rigor).

Output: reports/walk_forward/<config_label>/<YYYY-MM-DD-HHMM>/{summary.json, report.md}
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))

from dotenv import load_dotenv

from engine.validator.runner_v2 import (
    Phase5Result,
    run_phase5_stratification,
)


TRAIN_SEASONS = [2022, 2023, 2024]
HOLDOUT_SEASONS = [2025]
DROP_SEASONS = [2021]

# Pro benchmarks for Phase 7 framing reference (NOT for "we beat them"
# claims per decisions.md 2026-05-26 marketing-claims-package rewrite).
PRO_BENCHMARKS = {
    "NFL": 0.686,
    "MLB": 0.571,
    "NBA tourney": 0.72,
    "Club soccer": 0.616,
}


def _to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return _to_dict(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _write_summary(run_dir: Path, result: Phase5Result) -> None:
    (run_dir / "summary.json").write_text(
        json.dumps(_to_dict(result), indent=2, default=str)
    )


def _write_markdown(run_dir: Path, result: Phase5Result, wall_time_sec: float) -> None:
    lines: list[str] = []
    lines.append(f"# Phase 5 Q1-Q4 Stratification - {result.config_label}")
    lines.append("")
    lines.append(f"Run ID: `{result.run_id}` - Timestamp: {result.timestamp.isoformat()}")
    lines.append(f"Train: {result.train_seasons}  Holdout: {result.holdout_seasons}  Drop: {result.drop_seasons}")
    lines.append(f"Wall-clock: {wall_time_sec/60:.1f} min")
    lines.append("")
    lines.append("Fit configuration (engine candidate-final):")
    lines.append("- β₃ PINNED to 0 (Phase 4c disposition)")
    lines.append("- β₄ FREE (Phase 4d Step 4 disposition for audit-triggered sports)")
    lines.append("- β₅ FREE (Phase 4e disposition)")
    lines.append("- β₆ FREE (Phase 4b promotion)")
    lines.append("")
    lines.append("Q1 = closest games (toss-ups, hardest predictions)")
    lines.append("Q4 = biggest blowouts (easiest)")
    lines.append("")

    # Headline table — Q1 (where the rigor lives)
    lines.append("## HEADLINE: Q1 (toss-ups) per sport")
    lines.append("")
    lines.append("| Sport | Q1 n | Q1 accuracy (95% CI) | Q1 Brier (95% CI) | overall acc |")
    lines.append("|---|---:|---:|---:|---:|")
    for sport_name, sr in sorted(result.sports.items()):
        if not sr.quartiles:
            lines.append(f"| {sport_name} | — | — | — | {sr.overall_accuracy:.4f} |")
            continue
        q1 = sr.quartiles[0]
        acc_ci = f"[{q1.accuracy_ci_low:.4f}, {q1.accuracy_ci_high:.4f}]"
        brier_ci = f"[{q1.brier_ci_low:.4f}, {q1.brier_ci_high:.4f}]"
        lines.append(
            f"| {sport_name} | {q1.n_games} | "
            f"{q1.accuracy:.4f} {acc_ci} | "
            f"{q1.brier:.4f} {brier_ci} | "
            f"{sr.overall_accuracy:.4f} |"
        )
    lines.append("")

    # Per-sport Q1-Q4 breakdown
    lines.append("## Per-sport Q1-Q4 breakdown")
    lines.append("")
    for sport_name, sr in sorted(result.sports.items()):
        lines.append(f"### {sport_name}")
        lines.append("")
        lines.append(f"n_holdout = {sr.n_holdout}  overall_acc = {sr.overall_accuracy:.4f}  overall_brier = {sr.overall_brier:.4f}")
        lines.append("")
        lines.append("| Q | n | acc | acc 95% CI | brier | brier 95% CI | |rating_diff| range |")
        lines.append("|---:|---:|---:|---:|---:|---:|---|")
        for q in sr.quartiles:
            lines.append(
                f"| Q{q.quartile} | {q.n_games} | {q.accuracy:.4f} | "
                f"[{q.accuracy_ci_low:.4f}, {q.accuracy_ci_high:.4f}] | "
                f"{q.brier:.4f} | "
                f"[{q.brier_ci_low:.4f}, {q.brier_ci_high:.4f}] | "
                f"[{q.rating_diff_min:.3f}, {q.rating_diff_max:.3f}] |"
            )
        lines.append("")

    # Q1 vs pro benchmarks
    lines.append("## Q1 lower-CI vs pro benchmarks (rigor framing — NOT 'beats them')")
    lines.append("")
    lines.append("Per decisions.md 2026-05-26 marketing-claims rewrite, pro benchmarks are "
                 "context for what HS-level accuracy means, NEVER 'we beat them.' Reported "
                 "here for internal calibration only.")
    lines.append("")
    lines.append("| Sport | Q1 acc lower CI | NFL 0.686 | MLB 0.571 | NBA-tour 0.72 | Club soccer 0.616 |")
    lines.append("|---|---:|:---:|:---:|:---:|:---:|")
    for sport_name, sr in sorted(result.sports.items()):
        if not sr.quartiles:
            continue
        q1_lo = sr.quartiles[0].accuracy_ci_low
        marks = []
        for bench in (0.686, 0.571, 0.72, 0.616):
            marks.append("✓" if q1_lo > bench else " ")
        lines.append(
            f"| {sport_name} | {q1_lo:.4f} | {marks[0]} | {marks[1]} | {marks[2]} | {marks[3]} |"
        )
    lines.append("")

    if result.fit_warnings:
        lines.append("## Fit warnings")
        for w in result.fit_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("External-release status: INTERNAL only.")
    lines.append("")
    lines.append("Phase 5 = descriptive stratification. No ablation, no FDR. Output feeds "
                 "Phase 7 marketing-claims rigor framing.")

    (run_dir / "report.md").write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

    p = argparse.ArgumentParser(prog="python scripts/phase5_stratification.py")
    p.add_argument("--config-label", default="wf-phase5-stratification")
    p.add_argument("--sports", default=None,
                   help="Comma-separated sport names; defaults to all 8")
    p.add_argument("--output-root", default="reports/walk_forward")
    p.add_argument("--n-bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    sports = args.sports.split(",") if args.sports else None
    print(f"[phase5] config_label={args.config_label}")
    print(f"[phase5] train={TRAIN_SEASONS} holdout={HOLDOUT_SEASONS} drop={DROP_SEASONS}")
    print(f"[phase5] sports={sports or 'all 8'}")
    print(f"[phase5] β₃ pinned; β₄/β₅/β₆ free (engine candidate-final config)")
    print()

    t0 = time.time()
    result = run_phase5_stratification(
        train_seasons=TRAIN_SEASONS,
        holdout_seasons=HOLDOUT_SEASONS,
        drop_seasons=DROP_SEASONS,
        sports=sports,
        config_label=args.config_label,
        n_bootstrap=args.n_bootstrap,
        seed=args.seed,
    )
    elapsed = time.time() - t0

    out_root = Path(args.output_root)
    run_dir = out_root / args.config_label / result.timestamp.strftime("%Y-%m-%d-%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_summary(run_dir, result)
    _write_markdown(run_dir, result, elapsed)

    print(f"[phase5] artifacts -> {run_dir}")
    print(f"[phase5] wall-clock: {elapsed/60:.1f} min")
    print()
    print("=" * 70)
    print("Q1 (toss-ups) per sport — the headline:")
    for sport_name, sr in sorted(result.sports.items()):
        if not sr.quartiles:
            continue
        q1 = sr.quartiles[0]
        print(f"  {sport_name:18} Q1 n={q1.n_games:4d} acc={q1.accuracy:.4f} "
              f"[{q1.accuracy_ci_low:.4f}, {q1.accuracy_ci_high:.4f}] "
              f"brier={q1.brier:.4f}  overall_acc={sr.overall_accuracy:.4f}")
    print()
    print("Halting at Phase 5 boundary - proceeding to Phase 6 per autonomous queue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
