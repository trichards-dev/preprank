"""CLI wrapper for the Phase 2 walk-forward fitted-baseline run.

Usage:

    python scripts/phase2_baseline_fitted.py [--sports Football,...]
        [--config-label wf-baseline-v2-fitted]
        [--output-root reports/walk_forward]
        [--n-bootstrap 1000]
        [--seed 42]

Output: ``reports/walk_forward/<config_label>/<YYYY-MM-DD-HHMM>/``
containing ``summary.json`` + ``report.md``.

Applies the Phase 2 HALT-rules from Reese 2026-05-26 sign-off:

- Overall holdout acc > 0.73 (no feature-side explanation) → HALT for leakage audit
- Train/holdout gap > 0.005 → HALT for fold-contamination audit
- Brier < 0.20 AND gap < 0.005 → auto-promote to Phase 4a

The modified-(b) regime is hardcoded: drop 2021, train [2022, 2023, 2024],
validate [2025]. Per decisions.md 2026-05-26 "Regime-change handling".
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

# Allow direct invocation outside an installed package
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "packages", "engine", "src"))

from dotenv import load_dotenv

from engine.validator.runner_v2 import (
    AUTO_PROMOTE_BRIER_CEILING,
    HALT_ACCURACY_UPPER_BOUND,
    MAX_TRAIN_HOLDOUT_GAP,
    Phase2Result,
    run_phase2_baseline,
)


TRAIN_SEASONS = [2022, 2023, 2024]
HOLDOUT_SEASONS = [2025]
DROP_SEASONS = [2021]


def _to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses/datetimes for json.dump."""
    if dataclasses.is_dataclass(obj):
        return _to_dict(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _write_summary(run_dir: Path, result: Phase2Result) -> None:
    payload = _to_dict(result)
    (run_dir / "summary.json").write_text(json.dumps(payload, indent=2, default=str))


def _write_markdown(run_dir: Path, result: Phase2Result) -> None:
    lines: list[str] = []
    lines.append(f"# Phase 2 Baseline (Fitted) — {result.config_label}")
    lines.append("")
    lines.append(f"Run ID: `{result.run_id}`  ·  Timestamp: {result.timestamp.isoformat()}")
    lines.append("")
    lines.append(f"Train seasons: {result.train_seasons}")
    lines.append(f"Holdout seasons: {result.holdout_seasons}")
    lines.append(f"Drop seasons: {result.drop_seasons}")
    lines.append("")

    if result.halt_triggers:
        lines.append("## HALT TRIGGERED")
        for t in result.halt_triggers:
            lines.append(f"- {t}")
        lines.append("")
    elif result.auto_promote_to_phase4a:
        lines.append("## Auto-promote to Phase 4a: YES")
        lines.append("Overall Brier under 0.20 AND train/holdout gap under 0.005.")
        lines.append("")
    else:
        lines.append("## Status: continue, no auto-promote")
        lines.append(
            f"Brier {result.overall_holdout_brier:.4f} vs ceiling {AUTO_PROMOTE_BRIER_CEILING:.2f}; "
            f"gap {result.overall_train_holdout_gap:.4f} vs ceiling {MAX_TRAIN_HOLDOUT_GAP:.4f}."
        )
        lines.append("")

    lines.append("## Overall")
    lines.append("")
    lines.append("| Metric | Train | Holdout (95% bootstrap CI) |")
    lines.append("|---|---:|---:|")
    lines.append(
        f"| Game-winner accuracy | {result.overall_train_accuracy:.4f} | "
        f"{result.overall_holdout_accuracy:.4f} "
        f"[{result.overall_holdout_accuracy_ci[0]:.4f}, "
        f"{result.overall_holdout_accuracy_ci[1]:.4f}] |"
    )
    lines.append(
        f"| Brier score | {result.overall_train_brier:.4f} | "
        f"{result.overall_holdout_brier:.4f} "
        f"[{result.overall_holdout_brier_ci[0]:.4f}, "
        f"{result.overall_holdout_brier_ci[1]:.4f}] |"
    )
    lines.append(f"")
    lines.append(f"Train/holdout accuracy gap: **{result.overall_train_holdout_gap:.4f}** "
                 f"(ceiling {MAX_TRAIN_HOLDOUT_GAP:.4f}).")
    lines.append(f"n_train={result.n_train}, n_holdout={result.n_holdout}.")
    lines.append("")

    lines.append("## Per-sport")
    lines.append("")
    lines.append("| Sport | n_train | n_hold | Train acc | Hold acc (95% CI) | Brier (95% CI) | Gap | Cal slope | λ | conv |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|")
    for sport_name, sr in sorted(result.sports.items()):
        acc_ci = f"[{sr.holdout_accuracy_ci[0]:.4f}, {sr.holdout_accuracy_ci[1]:.4f}]"
        bri_ci = f"[{sr.holdout_brier_ci[0]:.4f}, {sr.holdout_brier_ci[1]:.4f}]"
        conv = "✓" if sr.fit.converged else "⚠"
        lines.append(
            f"| {sport_name} | {sr.n_train} | {sr.n_holdout} | "
            f"{sr.train_accuracy:.4f} | {sr.holdout_accuracy:.4f} {acc_ci} | "
            f"{sr.holdout_brier:.4f} {bri_ci} | {sr.train_holdout_gap:.4f} | "
            f"{sr.calibration_slope:.3f} | "
            f"{sr.fit.selected_lambda_per_game:.0e} | {conv} |"
        )
    lines.append("")

    lines.append("## Fitted coefficients (audit trail)")
    lines.append("")
    for sport_name, sr in sorted(result.sports.items()):
        lines.append(f"### {sport_name}")
        for coef, val in sr.fit.coefficients.items():
            lines.append(f"- `{coef}` = {val:+.4f}")
        lines.append(
            f"- selected λ per game = {sr.fit.selected_lambda_per_game:.4e} "
            f"(grid scores: {sr.fit.lambda_cv_scores})"
        )
        lines.append(f"- iterations = {sr.fit.iterations}; message = {sr.fit.message!r}")
        lines.append("")

    if result.fit_warnings:
        lines.append("## Fit warnings")
        for w in result.fit_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**External-release status:** these numbers are INTERNAL only. "
                 "Per decisions.md 2026-05-26 'TASK 3 sign-off granted', no external "
                 "accuracy claim leaves the office until residual Football Cat 1 is "
                 "closed AND Phase 6 recalibration is applied (when triggered).")
    lines.append("")

    (run_dir / "report.md").write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / "apps" / "api" / ".env")

    p = argparse.ArgumentParser(prog="python scripts/phase2_baseline_fitted.py")
    p.add_argument("--config-label", default="wf-baseline-v2-fitted")
    p.add_argument("--sports", default=None, help="comma-list; default = all")
    p.add_argument("--output-root", default="reports/walk_forward")
    p.add_argument("--n-bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    sports = args.sports.split(",") if args.sports else None
    print(f"[phase2_baseline_fitted] config_label={args.config_label}")
    print(f"[phase2_baseline_fitted] train={TRAIN_SEASONS} holdout={HOLDOUT_SEASONS} drop={DROP_SEASONS}")
    print(f"[phase2_baseline_fitted] sports={sports or 'all'}")
    print()

    result = run_phase2_baseline(
        train_seasons=TRAIN_SEASONS,
        holdout_seasons=HOLDOUT_SEASONS,
        drop_seasons=DROP_SEASONS,
        sports=sports,
        config_label=args.config_label,
        n_bootstrap=args.n_bootstrap,
        seed=args.seed,
    )

    # Write outputs
    out_root = Path(args.output_root)
    run_dir = out_root / args.config_label / result.timestamp.strftime("%Y-%m-%d-%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_summary(run_dir, result)
    _write_markdown(run_dir, result)

    print(f"[phase2_baseline_fitted] artifacts → {run_dir}")
    print()
    print("=" * 60)
    print(f"Overall holdout accuracy: {result.overall_holdout_accuracy:.4f} "
          f"[{result.overall_holdout_accuracy_ci[0]:.4f}, "
          f"{result.overall_holdout_accuracy_ci[1]:.4f}]")
    print(f"Overall holdout Brier:    {result.overall_holdout_brier:.4f} "
          f"[{result.overall_holdout_brier_ci[0]:.4f}, "
          f"{result.overall_holdout_brier_ci[1]:.4f}]")
    print(f"Train/holdout gap:        {result.overall_train_holdout_gap:.4f}")
    print()
    if result.halt_triggers:
        print("⚠️  HALT TRIGGERED:")
        for t in result.halt_triggers:
            print(f"   - {t}")
        return 2
    elif result.auto_promote_to_phase4a:
        print("✓  Auto-promote to Phase 4a (Brier < 0.20 AND gap < 0.005)")
        return 0
    else:
        print("·  Continue without auto-promote.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
