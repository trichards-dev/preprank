"""CLI for Phase 4a: per-sport HFA ablation vs Phase 2 baseline.

Per Reese 2026-05-26 evening Phase 4a sign-off:
  - Reference: Phase 2 baseline (all 6 beta fitted per sport, including beta_2)
  - Ablation: same fit, but beta_2 constrained to 0 (other beta refit)
  - Per-sport paired-bootstrap CI on (accuracy_lift, brier_lift)
  - Benjamini-Hochberg FDR across the 8 per-sport tests at alpha=0.05
  - Halt at Phase 4a boundary regardless of outcome

Output: reports/walk_forward/<config_label>/<YYYY-MM-DD-HHMM>/{summary.json, report.md}

Formatting per Reese 2026-05-26: plain text only, no emoji glyphs in
table cells.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "packages", "engine", "src"))

from dotenv import load_dotenv

from engine.validator.runner_v2 import (
    Phase4aResult,
    run_phase4a_hfa_ablation,
)


TRAIN_SEASONS = [2022, 2023, 2024]
HOLDOUT_SEASONS = [2025]
DROP_SEASONS = [2021]


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


def _write_summary(run_dir: Path, result: Phase4aResult) -> None:
    (run_dir / "summary.json").write_text(
        json.dumps(_to_dict(result), indent=2, default=str)
    )


def _write_markdown(run_dir: Path, result: Phase4aResult) -> None:
    lines: list[str] = []
    lines.append(f"# Phase 4a HFA Ablation - {result.config_label}")
    lines.append("")
    lines.append(f"Run ID: `{result.run_id}` - Timestamp: {result.timestamp.isoformat()}")
    lines.append(f"Train: {result.train_seasons}  Holdout: {result.holdout_seasons}  Drop: {result.drop_seasons}")
    lines.append("")
    lines.append(f"Sports with significant per-sport HFA lift (FDR-corrected at alpha=0.05): "
                 f"{result.n_significant_after_fdr} of {len(result.sports)}")
    lines.append("")

    lines.append("## Per-sport HFA ablation results")
    lines.append("")
    lines.append("| Sport | beta_2 | Baseline acc | Ablation acc | Acc lift (95% CI) | Brier lift (95% CI) | p (1-sided) | FDR sig |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|:---:|")
    for sport_name, sr in sorted(result.sports.items()):
        sig_label = "YES" if sr.significant_after_fdr else "no"
        acc_ci = f"[{sr.accuracy_lift_ci[0]:+.4f}, {sr.accuracy_lift_ci[1]:+.4f}]"
        brier_ci = f"[{sr.brier_lift_ci[0]:+.5f}, {sr.brier_lift_ci[1]:+.5f}]"
        lines.append(
            f"| {sport_name} | {sr.fit_baseline.coefficients['beta_2']:+.4f} | "
            f"{sr.baseline_accuracy:.4f} | {sr.ablation_accuracy:.4f} | "
            f"{sr.accuracy_lift:+.4f} {acc_ci} | "
            f"{sr.brier_lift:+.5f} {brier_ci} | "
            f"{sr.p_value_one_sided:.4f} | {sig_label} |"
        )
    lines.append("")

    lines.append("## Baseline-vs-ablation coefficient comparison")
    lines.append("")
    for sport_name, sr in sorted(result.sports.items()):
        lines.append(f"### {sport_name}")
        lines.append(f"")
        lines.append(f"|       | baseline | ablation |")
        lines.append(f"|-------|---------:|---------:|")
        for c in ["beta_0", "beta_1", "beta_2", "beta_3", "beta_4", "beta_5"]:
            b = sr.fit_baseline.coefficients.get(c, 0.0)
            a = sr.fit_ablation.coefficients.get(c, 0.0)
            lines.append(f"| {c} | {b:+.4f} | {a:+.4f} |")
        lines.append("")

    if result.fit_warnings:
        lines.append("## Fit warnings")
        for w in result.fit_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("External-release status: INTERNAL only. Per decisions.md 2026-05-26 "
                 "TASK 3 output conditions, no external accuracy claim until residual "
                 "Football Cat 1 is closed AND Phase 6 per-decile reliability audit "
                 "completes.")
    lines.append("")
    lines.append("Halt at Phase 4a boundary regardless of outcome per Reese 2026-05-26 "
                 "evening sign-off conditions.")

    (run_dir / "report.md").write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / "apps" / "api" / ".env")

    p = argparse.ArgumentParser(prog="python scripts/phase4a_hfa_fit.py")
    p.add_argument("--config-label", default="wf-phase4a-hfa-ablation")
    p.add_argument("--sports", default=None)
    p.add_argument("--output-root", default="reports/walk_forward")
    p.add_argument("--n-bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--fdr-alpha", type=float, default=0.05)
    args = p.parse_args(argv)

    sports = args.sports.split(",") if args.sports else None
    print(f"[phase4a] config_label={args.config_label}")
    print(f"[phase4a] train={TRAIN_SEASONS} holdout={HOLDOUT_SEASONS} drop={DROP_SEASONS}")
    print(f"[phase4a] sports={sports or 'all'}")
    print(f"[phase4a] FDR alpha={args.fdr_alpha}")
    print()

    result = run_phase4a_hfa_ablation(
        train_seasons=TRAIN_SEASONS,
        holdout_seasons=HOLDOUT_SEASONS,
        drop_seasons=DROP_SEASONS,
        sports=sports,
        config_label=args.config_label,
        n_bootstrap=args.n_bootstrap,
        seed=args.seed,
        fdr_alpha=args.fdr_alpha,
    )

    out_root = Path(args.output_root)
    run_dir = out_root / args.config_label / result.timestamp.strftime("%Y-%m-%d-%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_summary(run_dir, result)
    _write_markdown(run_dir, result)

    print(f"[phase4a] artifacts -> {run_dir}")
    print()
    print("=" * 60)
    print(f"Sports with significant per-sport HFA lift after FDR "
          f"(alpha={args.fdr_alpha}): {result.n_significant_after_fdr} of {len(result.sports)}")
    print()
    for sport_name, sr in sorted(result.sports.items()):
        sig = "SIG" if sr.significant_after_fdr else "  -"
        print(f"  [{sig}] {sport_name:18} beta_2={sr.fit_baseline.coefficients['beta_2']:+.4f} "
              f"acc_lift={sr.accuracy_lift:+.4f} "
              f"[{sr.accuracy_lift_ci[0]:+.4f}, {sr.accuracy_lift_ci[1]:+.4f}] "
              f"p={sr.p_value_one_sided:.4f}")
    print()
    print("Halting at Phase 4a boundary regardless of outcome.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
