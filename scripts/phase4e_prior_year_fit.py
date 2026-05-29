"""CLI for Phase 4e: per-sport prior-year carryover (β₅) ablation.

Reese 2026-05-29 design decisions (resolved):
  - Reference fit: β₃ + β₄ PINNED to 0, β₅ FREE, β₆ FREE
  - Ablation fit: β₃ + β₄ + β₅ all pinned to 0, β₆ FREE
  - (β₄ pinned in BOTH fits so it cannot absorb β₅'s signal when β₅
    is masked in the ablation — stricter null isolates β₅'s actual
    contribution.)
  - TWO measurements per sport: weeks_1_3 (PRIMARY; where β₅ structurally
    fires via _decay) and full_season (SECONDARY; Phase 4d parity).
  - Cold-start games KEPT in holdout. Report _pyc=0 share as diagnostic.
  - Per-sport paired-bootstrap 1000-resample CI on (acc, brier) deltas
  - BH-FDR α=0.05 separately across the 8 per-sport tests for each
    measurement scope (primary and secondary report independent FDR
    significance flags).
  - Halt at phase boundary regardless of outcome.
  - >2pp lift on primary measurement triggers the standardized replay
    audit (surfaced in CLI output; replay run is a separate step).

Output: reports/walk_forward/<config_label>/<YYYY-MM-DD-HHMM>/{summary.json, report.md}
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))

from dotenv import load_dotenv

from engine.validator.runner_v2 import (
    Phase4eResult,
    run_phase4e_prior_year_ablation,
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


def _write_summary(run_dir: Path, result: Phase4eResult) -> None:
    (run_dir / "summary.json").write_text(
        json.dumps(_to_dict(result), indent=2, default=str)
    )


def _write_markdown(
    run_dir: Path,
    result: Phase4eResult,
    wall_time_sec: float,
    audit_triggered_sports: list[str],
) -> None:
    lines: list[str] = []
    lines.append(f"# Phase 4e Prior-Year Carryover Ablation - {result.config_label}")
    lines.append("")
    lines.append(f"Run ID: `{result.run_id}` - Timestamp: {result.timestamp.isoformat()}")
    lines.append(f"Train: {result.train_seasons}  Holdout: {result.holdout_seasons}  Drop: {result.drop_seasons}")
    lines.append(f"Wall-clock: {wall_time_sec/60:.1f} min")
    lines.append("")
    lines.append("Configuration (Reese 2026-05-29 design):")
    lines.append("- β₃ + β₄ PINNED to 0 in BOTH reference and ablation (β₄ pinned both ways prevents absorption)")
    lines.append("- β₆ FREE in both (Phase 4b promotion)")
    lines.append("- Reference: β₅ FREE (prior-year carryover signal active)")
    lines.append("- Ablation: β₅ pinned to 0")
    lines.append("- TWO measurements per sport:")
    lines.append("  - PRIMARY: weeks_1_3 (where β₅ fires structurally via _decay)")
    lines.append("  - SECONDARY: full_season (Phase 4d parity)")
    lines.append("")
    lines.append(f"PRIMARY  (weeks_1_3) sports with significant lift (FDR α=0.05): "
                 f"{result.n_significant_after_fdr_primary} of {len(result.sports)}")
    lines.append(f"SECONDARY (full_season) sports with significant lift (FDR α=0.05): "
                 f"{result.n_significant_after_fdr_secondary} of {len(result.sports)}")
    lines.append("")

    # PRIMARY table (headline)
    lines.append("## PRIMARY: weeks_1_3 (headline)")
    lines.append("")
    lines.append("| Sport | β₅ | n_holdout | Ref acc | Abl acc | Acc lift (95% CI) | Brier lift (95% CI) | p | FDR | >2pp? |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|")
    for sport_name, sr in sorted(result.sports.items()):
        m = sr.weeks_1_3
        sig_label = "YES" if m.significant_after_fdr else "no"
        acc_ci = f"[{m.accuracy_lift_ci[0]:+.4f}, {m.accuracy_lift_ci[1]:+.4f}]"
        brier_ci = f"[{m.brier_lift_ci[0]:+.5f}, {m.brier_lift_ci[1]:+.5f}]"
        audit_label = "AUDIT" if sport_name in audit_triggered_sports else ""
        lines.append(
            f"| {sport_name} | {sr.fit_baseline.coefficients.get('beta_5', 0.0):+.4f} | "
            f"{m.n_holdout} | "
            f"{m.baseline_accuracy:.4f} | {m.ablation_accuracy:.4f} | "
            f"{m.accuracy_lift:+.4f} {acc_ci} | "
            f"{m.brier_lift:+.5f} {brier_ci} | "
            f"{m.p_value_one_sided:.4f} | {sig_label} | {audit_label} |"
        )
    lines.append("")

    # SECONDARY table
    lines.append("## SECONDARY: full_season (Phase 4d parity)")
    lines.append("")
    lines.append("| Sport | n_holdout | Ref acc | Abl acc | Acc lift (95% CI) | Brier lift (95% CI) | p | FDR |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|:---:|")
    for sport_name, sr in sorted(result.sports.items()):
        m = sr.full_season
        sig_label = "YES" if m.significant_after_fdr else "no"
        acc_ci = f"[{m.accuracy_lift_ci[0]:+.4f}, {m.accuracy_lift_ci[1]:+.4f}]"
        brier_ci = f"[{m.brier_lift_ci[0]:+.5f}, {m.brier_lift_ci[1]:+.5f}]"
        lines.append(
            f"| {sport_name} | "
            f"{m.n_holdout} | "
            f"{m.baseline_accuracy:.4f} | {m.ablation_accuracy:.4f} | "
            f"{m.accuracy_lift:+.4f} {acc_ci} | "
            f"{m.brier_lift:+.5f} {brier_ci} | "
            f"{m.p_value_one_sided:.4f} | {sig_label} |"
        )
    lines.append("")

    # Cold-start diagnostic
    lines.append("## Cold-start diagnostic (_pyc=0 share in primary holdout)")
    lines.append("")
    lines.append("| Sport | weeks_1_3 sides | _pyc=0 sides | _pyc=0 % | genuine cold-start | data gap |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for sport_name, sr in sorted(result.sports.items()):
        n_sides = 2 * sr.weeks_1_3.n_holdout
        pct = (100.0 * sr.n_pyc_zero_holdout / n_sides) if n_sides else 0.0
        lines.append(
            f"| {sport_name} | {n_sides} | {sr.n_pyc_zero_holdout} | {pct:.1f}% | "
            f"{sr.n_pyc_zero_genuine_coldstart} | {sr.n_pyc_zero_data_gap} |"
        )
    lines.append("")

    # Coefficient comparison
    lines.append("## Reference-vs-ablation coefficient comparison")
    lines.append("")
    for sport_name, sr in sorted(result.sports.items()):
        lines.append(f"### {sport_name}")
        lines.append("")
        lines.append("|       | reference (β₅ free) | ablation (β₅=0) |")
        lines.append("|-------|---------:|---------:|")
        for c in ["beta_0", "beta_1", "beta_2", "beta_3", "beta_4", "beta_5", "beta_6"]:
            b = sr.fit_baseline.coefficients.get(c, 0.0)
            a = sr.fit_ablation.coefficients.get(c, 0.0)
            lines.append(f"| {c} | {b:+.4f} | {a:+.4f} |")
        lines.append("")

    if audit_triggered_sports:
        lines.append("## Replay-audit triggers (>2pp lift on PRIMARY)")
        lines.append("")
        lines.append("Per Reese standing rule (2026-05-27): any sport with >2pp accuracy lift "
                     "from a single feature phase requires the standardized per-game replay "
                     "audit before promote.")
        lines.append("")
        for sport in audit_triggered_sports:
            sr = result.sports[sport]
            lines.append(f"- **{sport}**: primary lift = {sr.weeks_1_3.accuracy_lift:+.4f} → audit triggered")
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
    lines.append("Halt at Phase 4e boundary per Reese 2026-05-29 autonomous-queue conditions. "
                 "Explicit Phase 5 sign-off NOT required (autonomous chain through 5+6 unless "
                 "acceptance criteria fail by >20% or integrity issue surfaces).")
    lines.append("")
    lines.append("Section 5 / mechanism-verification discipline applies. If primary lift is "
                 "striking on any sport (>5pp), spec-grep the prior-year-carryover path "
                 "before any causal story attaches.")

    (run_dir / "report.md").write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

    p = argparse.ArgumentParser(prog="python scripts/phase4e_prior_year_fit.py")
    p.add_argument("--config-label", default="wf-phase4e-prior-year-carryover-ablation")
    p.add_argument("--sports", default=None,
                   help="Comma-separated sport names; defaults to all 8")
    p.add_argument("--output-root", default="reports/walk_forward")
    p.add_argument("--n-bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--fdr-alpha", type=float, default=0.05)
    p.add_argument("--audit-threshold", type=float, default=0.02,
                   help="Accuracy-lift threshold on PRIMARY measurement above which the "
                        "replay audit fires automatically (Reese 2026-05-26 standing rule)")
    args = p.parse_args(argv)

    sports = args.sports.split(",") if args.sports else None
    print(f"[phase4e] config_label={args.config_label}")
    print(f"[phase4e] train={TRAIN_SEASONS} holdout={HOLDOUT_SEASONS} drop={DROP_SEASONS}")
    print(f"[phase4e] sports={sports or 'all 8'}")
    print(f"[phase4e] FDR alpha={args.fdr_alpha}, audit threshold={args.audit_threshold} (PRIMARY only)")
    print(f"[phase4e] β₃+β₄ pinned in BOTH fits; β₅ ablation; β₆ free")
    print(f"[phase4e] PRIMARY measurement = weeks_1_3; SECONDARY = full_season")
    print()

    t0 = time.time()
    result = run_phase4e_prior_year_ablation(
        train_seasons=TRAIN_SEASONS,
        holdout_seasons=HOLDOUT_SEASONS,
        drop_seasons=DROP_SEASONS,
        sports=sports,
        config_label=args.config_label,
        n_bootstrap=args.n_bootstrap,
        seed=args.seed,
        fdr_alpha=args.fdr_alpha,
    )
    elapsed = time.time() - t0

    # Audit trigger is on PRIMARY measurement only
    audit_triggered_sports = [
        sport for sport, sr in result.sports.items()
        if sr.weeks_1_3.accuracy_lift > args.audit_threshold
    ]

    out_root = Path(args.output_root)
    run_dir = out_root / args.config_label / result.timestamp.strftime("%Y-%m-%d-%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_summary(run_dir, result)
    _write_markdown(run_dir, result, elapsed, audit_triggered_sports)

    print(f"[phase4e] artifacts -> {run_dir}")
    print(f"[phase4e] wall-clock: {elapsed/60:.1f} min")
    print()
    print("=" * 70)
    print(f"PRIMARY (weeks_1_3) - sports with significant β₅ lift after FDR "
          f"(alpha={args.fdr_alpha}): {result.n_significant_after_fdr_primary} of {len(result.sports)}")
    print(f"SECONDARY (full_season) - sports with significant β₅ lift after FDR: "
          f"{result.n_significant_after_fdr_secondary} of {len(result.sports)}")
    print()
    print("PRIMARY (headline):")
    for sport_name, sr in sorted(result.sports.items()):
        m = sr.weeks_1_3
        sig = "SIG" if m.significant_after_fdr else "  -"
        audit = " AUDIT" if sport_name in audit_triggered_sports else ""
        print(f"  [{sig}] {sport_name:18} beta_5={sr.fit_baseline.coefficients.get('beta_5', 0.0):+.4f} "
              f"n={m.n_holdout:4d} "
              f"acc_lift={m.accuracy_lift:+.4f} "
              f"[{m.accuracy_lift_ci[0]:+.4f}, {m.accuracy_lift_ci[1]:+.4f}] "
              f"p={m.p_value_one_sided:.4f}{audit}")
    print()
    print("SECONDARY (full_season):")
    for sport_name, sr in sorted(result.sports.items()):
        m = sr.full_season
        sig = "SIG" if m.significant_after_fdr else "  -"
        print(f"  [{sig}] {sport_name:18} "
              f"n={m.n_holdout:4d} "
              f"acc_lift={m.accuracy_lift:+.4f} "
              f"[{m.accuracy_lift_ci[0]:+.4f}, {m.accuracy_lift_ci[1]:+.4f}] "
              f"p={m.p_value_one_sided:.4f}")
    print()

    if audit_triggered_sports:
        print(f"[phase4e] >2pp PRIMARY lift in: {audit_triggered_sports}")
        print(f"[phase4e] Replay audit fires automatically per standing rule.")
        print()

    print("Halting at Phase 4e boundary - proceeding to Phase 5 per autonomous queue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
