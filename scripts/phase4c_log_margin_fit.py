"""CLI for Phase 4c: per-sport log-margin (β₃) ablation vs Phase 4b reference.

Reese 2026-05-27 kickoff conditions:
  - Reference fit: model with log-margin feature (β₃ free, β₆ free)
  - Ablation fit: same fit but β₃ constrained to 0 (β₆ still free)
  - Per-sport paired-bootstrap 1000-resample CI on (acc, brier) deltas
  - Benjamini-Hochberg FDR across 8 per-sport tests at α=0.05
  - Halt at Phase 4c boundary regardless of outcome
  - No auto-chain into Phase 4d
  - >2pp lift in any single sport triggers the standardized per-game
    replay audit; surface without prompt

Output: reports/walk_forward/<config_label>/<YYYY-MM-DD-HHMM>/{summary.json, report.md}

Plain text formatting only (no emoji glyphs in table cells).
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
    Phase4cResult,
    run_phase4c_log_margin_ablation,
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


def _write_summary(run_dir: Path, result: Phase4cResult) -> None:
    (run_dir / "summary.json").write_text(
        json.dumps(_to_dict(result), indent=2, default=str)
    )


def _write_markdown(run_dir: Path, result: Phase4cResult, wall_time_sec: float, audit_triggered_sports: list[str]) -> None:
    lines: list[str] = []
    lines.append(f"# Phase 4c Log-Margin Ablation - {result.config_label}")
    lines.append("")
    lines.append(f"Run ID: `{result.run_id}` - Timestamp: {result.timestamp.isoformat()}")
    lines.append(f"Train: {result.train_seasons}  Holdout: {result.holdout_seasons}  Drop: {result.drop_seasons}")
    lines.append(f"Wall-clock: {wall_time_sec/60:.1f} min")
    lines.append("")
    lines.append(f"Sports with significant log-margin lift (FDR-corrected at alpha=0.05): "
                 f"{result.n_significant_after_fdr} of {len(result.sports)}")
    lines.append("")

    lines.append("## Per-sport log-margin ablation results")
    lines.append("")
    lines.append("| Sport | beta_3 | Ref acc | Ablation acc | Acc lift (95% CI) | Brier lift (95% CI) | p (1-sided) | FDR sig | >2pp? |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|:---:|:---:|")
    for sport_name, sr in sorted(result.sports.items()):
        sig_label = "YES" if sr.significant_after_fdr else "no"
        acc_ci = f"[{sr.accuracy_lift_ci[0]:+.4f}, {sr.accuracy_lift_ci[1]:+.4f}]"
        brier_ci = f"[{sr.brier_lift_ci[0]:+.5f}, {sr.brier_lift_ci[1]:+.5f}]"
        audit_label = "AUDIT" if sport_name in audit_triggered_sports else ""
        lines.append(
            f"| {sport_name} | {sr.fit_baseline.coefficients['beta_3']:+.4f} | "
            f"{sr.baseline_accuracy:.4f} | {sr.ablation_accuracy:.4f} | "
            f"{sr.accuracy_lift:+.4f} {acc_ci} | "
            f"{sr.brier_lift:+.5f} {brier_ci} | "
            f"{sr.p_value_one_sided:.4f} | {sig_label} | {audit_label} |"
        )
    lines.append("")

    lines.append("## Reference-vs-ablation coefficient comparison")
    lines.append("")
    for sport_name, sr in sorted(result.sports.items()):
        lines.append(f"### {sport_name}")
        lines.append("")
        lines.append("|       | reference (β₃ free) | ablation (β₃=0) |")
        lines.append("|-------|---------:|---------:|")
        for c in ["beta_0", "beta_1", "beta_2", "beta_3", "beta_4", "beta_5", "beta_6"]:
            b = sr.fit_baseline.coefficients.get(c, 0.0)
            a = sr.fit_ablation.coefficients.get(c, 0.0)
            lines.append(f"| {c} | {b:+.4f} | {a:+.4f} |")
        lines.append("")

    if audit_triggered_sports:
        lines.append("## Replay-audit triggers (>2pp lift)")
        lines.append("")
        lines.append("Per Reese 2026-05-27 standing rule: any sport with >2pp accuracy lift "
                     "from a single feature phase requires the standardized per-game replay "
                     "audit (20 stratified games, per-game evidence dump, bit-exact replay vs "
                     "production precompute, 3 failure-mode checks) before promote. "
                     "The audit is surfaced automatically — no prompt required.")
        lines.append("")
        for sport in audit_triggered_sports:
            sr = result.sports[sport]
            lines.append(f"- **{sport}**: lift = {sr.accuracy_lift:+.4f} → audit triggered")
        lines.append("")

    if result.fit_warnings:
        lines.append("## Fit warnings")
        for w in result.fit_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("External-release status: INTERNAL only. Per decisions.md 2026-05-26 "
                 "TASK 3 output conditions and engine-track session discipline, no "
                 "external numbers leave the office until engine candidate-final state.")
    lines.append("")
    lines.append("Halt at Phase 4c boundary per Reese 2026-05-27 kickoff conditions. "
                 "Explicit Phase 4d sign-off required before continuing.")
    lines.append("")
    lines.append("Section 5 / mechanism-verification discipline applies. Any striking "
                 "finding gets the mechanism check before any causal story is attached.")

    (run_dir / "report.md").write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

    p = argparse.ArgumentParser(prog="python scripts/phase4c_log_margin_fit.py")
    p.add_argument("--config-label", default="wf-phase4c-log-margin-ablation")
    p.add_argument("--sports", default=None,
                   help="Comma-separated sport names; defaults to all 8")
    p.add_argument("--output-root", default="reports/walk_forward")
    p.add_argument("--n-bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--fdr-alpha", type=float, default=0.05)
    p.add_argument("--audit-threshold", type=float, default=0.02,
                   help="Accuracy-lift threshold above which the replay audit fires "
                        "automatically (Reese 2026-05-26 standing rule = 0.02 = 2pp)")
    args = p.parse_args(argv)

    sports = args.sports.split(",") if args.sports else None
    print(f"[phase4c] config_label={args.config_label}")
    print(f"[phase4c] train={TRAIN_SEASONS} holdout={HOLDOUT_SEASONS} drop={DROP_SEASONS}")
    print(f"[phase4c] sports={sports or 'all 8'}")
    print(f"[phase4c] FDR alpha={args.fdr_alpha}, audit threshold={args.audit_threshold}")
    print()

    t0 = time.time()
    result = run_phase4c_log_margin_ablation(
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

    audit_triggered_sports = [
        sport for sport, sr in result.sports.items()
        if sr.accuracy_lift > args.audit_threshold
    ]

    out_root = Path(args.output_root)
    run_dir = out_root / args.config_label / result.timestamp.strftime("%Y-%m-%d-%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_summary(run_dir, result)
    _write_markdown(run_dir, result, elapsed, audit_triggered_sports)

    print(f"[phase4c] artifacts -> {run_dir}")
    print(f"[phase4c] wall-clock: {elapsed/60:.1f} min")
    print()
    print("=" * 70)
    print(f"Sports with significant log-margin lift after FDR "
          f"(alpha={args.fdr_alpha}): {result.n_significant_after_fdr} of {len(result.sports)}")
    print()
    for sport_name, sr in sorted(result.sports.items()):
        sig = "SIG" if sr.significant_after_fdr else "  -"
        audit = " AUDIT" if sport_name in audit_triggered_sports else ""
        print(f"  [{sig}] {sport_name:18} beta_3={sr.fit_baseline.coefficients['beta_3']:+.4f} "
              f"acc_lift={sr.accuracy_lift:+.4f} "
              f"[{sr.accuracy_lift_ci[0]:+.4f}, {sr.accuracy_lift_ci[1]:+.4f}] "
              f"p={sr.p_value_one_sided:.4f}{audit}")
    print()

    if audit_triggered_sports:
        print(f"[phase4c] >2pp lift in: {audit_triggered_sports}")
        print(f"[phase4c] Replay audit fires automatically per standing rule.")
        print()

    print("Halting at Phase 4c boundary - explicit Phase 4d sign-off required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
