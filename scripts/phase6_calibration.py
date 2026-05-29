"""CLI for Phase 6: calibration + per-decile reliability audit.

Per decisions.md 2026-05-26 launch-date lock: Phase 6 is the GATE for
engine candidate-final. Auto-slip rule (Sept 1 → Sept 15) fires on
uncorrectable tail miscalibration AFTER isotonic recalibration.

Acceptance criteria per sport:
  - slope ∈ [0.85, 1.15]
  - max |mean_predicted - mean_observed| ≤ 0.05 per decile bin
    (only bins with n_games ≥ 10 — small bins are noise)

If raw fit fails either gate, isotonic recalibration is applied and
post-iso state is re-evaluated. PASS = final-state slope-in-band AND
zero exceeding bins. FAIL on any sport surfaces the auto-slip trigger
for Reese's review.

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
    PHASE6_MAX_BIN_GAP,
    PHASE6_MIN_BIN_N,
    PHASE6_SLOPE_BAND,
    Phase6Result,
    run_phase6_calibration,
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
    if isinstance(obj, float) and obj != obj:  # NaN
        return None
    return obj


def _write_summary(run_dir: Path, result: Phase6Result) -> None:
    (run_dir / "summary.json").write_text(
        json.dumps(_to_dict(result), indent=2, default=str)
    )


def _fmt_bin_table(bins: list, label: str) -> list[str]:
    lines: list[str] = [f"#### {label}", ""]
    lines.append("| Decile | n | mean_pred | mean_obs | |gap| | exceeds? |")
    lines.append("|---:|---:|---:|---:|---:|:---:|")
    for i, b in enumerate(bins, start=1):
        if b.n_games == 0:
            lines.append(f"| {i} ({b.bin_lower:.1f}-{b.bin_upper:.1f}) | 0 | — | — | — | — |")
            continue
        flag = "❗" if b.exceeds_max_gap else " "
        lines.append(
            f"| {i} ({b.bin_lower:.1f}-{b.bin_upper:.1f}) | "
            f"{b.n_games} | {b.mean_predicted:.4f} | {b.mean_observed:.4f} | "
            f"{b.abs_gap:.4f} | {flag} |"
        )
    lines.append("")
    return lines


def _write_markdown(run_dir: Path, result: Phase6Result, wall_time_sec: float) -> None:
    lines: list[str] = []
    lines.append(f"# Phase 6 Calibration + Per-Decile Reliability - {result.config_label}")
    lines.append("")
    lines.append(f"Run ID: `{result.run_id}` - Timestamp: {result.timestamp.isoformat()}")
    lines.append(f"Train: {result.train_seasons}  Holdout: {result.holdout_seasons}  Drop: {result.drop_seasons}")
    lines.append(f"Wall-clock: {wall_time_sec/60:.1f} min")
    lines.append("")
    lines.append(f"Acceptance gates per sport (decisions.md 2026-05-26):")
    lines.append(f"- calibration slope ∈ [{PHASE6_SLOPE_BAND[0]:.2f}, {PHASE6_SLOPE_BAND[1]:.2f}]")
    lines.append(f"- max |gap| ≤ {PHASE6_MAX_BIN_GAP:.2f} per decile bin (n_bin ≥ {PHASE6_MIN_BIN_N})")
    lines.append(f"- post-isotonic-recalibration state is the gate; auto-slip fires if uncorrectable")
    lines.append("")
    lines.append(f"## Verdict: {result.n_passing} of {len(result.sports)} sports PASS")
    lines.append("")
    if result.n_failing > 0:
        lines.append(f"**{result.n_failing} sport(s) FAIL acceptance — AUTO-SLIP TRIGGER for Reese's review.**")
    else:
        lines.append("**All sports PASS acceptance — engine candidate-final unblocked on calibration.**")
    lines.append("")

    lines.append("## Headline table (post-K-fold-isotonic = the gate)")
    lines.append("")
    lines.append("| Sport | n_holdout | overall_acc | iso slope | iso exceed | iso D1 gap (n) | iso D10 gap (n) | tail miscal? | VERDICT |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|:---:|:---:|")
    for sport_name, sr in sorted(result.sports.items()):
        verdict = "✓ PASS" if sr.passes_acceptance else "✗ FAIL"
        tail_flag = "**YES**" if sr.tail_miscalibration_after_isotonic else "no"
        lines.append(
            f"| {sport_name} | {sr.n_holdout} | "
            f"{sr.overall_accuracy:.4f} | "
            f"{sr.isotonic_slope:.3f} | {sr.isotonic_n_bins_exceeding_gap} | "
            f"{sr.isotonic_d1_gap:.4f} ({sr.isotonic_d1_n}) | "
            f"{sr.isotonic_d10_gap:.4f} ({sr.isotonic_d10_n}) | "
            f"{tail_flag} | {verdict} |"
        )
    lines.append("")

    # Raw comparison table for context
    lines.append("## Raw (pre-isotonic) state for comparison")
    lines.append("")
    lines.append("| Sport | raw slope | in band? | raw exceed | raw D1 gap (n) | raw D10 gap (n) |")
    lines.append("|---|---:|:---:|---:|---:|---:|")
    for sport_name, sr in sorted(result.sports.items()):
        in_band = "✓" if sr.raw_slope_in_band else "✗"
        lines.append(
            f"| {sport_name} | {sr.raw_slope:.3f} | {in_band} | "
            f"{sr.raw_n_bins_exceeding_gap} | "
            f"{sr.raw_d1_gap:.4f} ({sr.raw_d1_n}) | "
            f"{sr.raw_d10_gap:.4f} ({sr.raw_d10_n}) |"
        )
    lines.append("")

    lines.append("## Per-sport reliability bins (raw + isotonic)")
    lines.append("")
    for sport_name, sr in sorted(result.sports.items()):
        lines.append(f"### {sport_name}  (raw slope = {sr.raw_slope:.4f}, intercept = {sr.raw_intercept:.4f})")
        lines.append("")
        lines.extend(_fmt_bin_table(sr.raw_bins, "Raw bins"))
        if sr.isotonic_applied:
            lines.append(f"#### Isotonic recalibration applied")
            lines.append("")
            lines.append(f"Post-iso slope = {sr.isotonic_slope:.4f}, intercept = {sr.isotonic_intercept:.4f}")
            lines.append("")
            lines.extend(_fmt_bin_table(sr.isotonic_bins, "Isotonic bins"))
        else:
            lines.append("_Isotonic not applied: raw fit already passes acceptance._")
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
    if result.n_failing > 0:
        lines.append(f"**AUTO-SLIP TRIGGER**: {result.n_failing} sport(s) failed Phase 6 acceptance after "
                     f"isotonic recalibration. Per decisions.md 2026-05-26 evening Phase 6 framing "
                     f"correction, this fires the Sept 1 → Sept 15 auto-slip rule pending Reese's review.")
    else:
        lines.append("Engine candidate-final state on calibration: CLEARED.")
    lines.append("")

    (run_dir / "report.md").write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

    p = argparse.ArgumentParser(prog="python scripts/phase6_calibration.py")
    p.add_argument("--config-label", default="wf-phase6-calibration")
    p.add_argument("--sports", default=None,
                   help="Comma-separated sport names; defaults to all 8")
    p.add_argument("--output-root", default="reports/walk_forward")
    p.add_argument("--n-bins", type=int, default=10, help="reliability bins (default 10 = deciles)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    sports = args.sports.split(",") if args.sports else None
    print(f"[phase6] config_label={args.config_label}")
    print(f"[phase6] train={TRAIN_SEASONS} holdout={HOLDOUT_SEASONS} drop={DROP_SEASONS}")
    print(f"[phase6] sports={sports or 'all 8'}")
    print(f"[phase6] slope band [{PHASE6_SLOPE_BAND[0]:.2f}, {PHASE6_SLOPE_BAND[1]:.2f}]  |  max bin gap {PHASE6_MAX_BIN_GAP:.2f}  |  min bin n {PHASE6_MIN_BIN_N}")
    print()

    t0 = time.time()
    result = run_phase6_calibration(
        train_seasons=TRAIN_SEASONS,
        holdout_seasons=HOLDOUT_SEASONS,
        drop_seasons=DROP_SEASONS,
        sports=sports,
        config_label=args.config_label,
        n_bins=args.n_bins,
        seed=args.seed,
    )
    elapsed = time.time() - t0

    out_root = Path(args.output_root)
    run_dir = out_root / args.config_label / result.timestamp.strftime("%Y-%m-%d-%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_summary(run_dir, result)
    _write_markdown(run_dir, result, elapsed)

    print(f"[phase6] artifacts -> {run_dir}")
    print(f"[phase6] wall-clock: {elapsed/60:.1f} min")
    print()
    print("=" * 70)
    print(f"VERDICT: {result.n_passing} of {len(result.sports)} sports PASS")
    print()
    auto_slip_sports: list[str] = []
    for sport_name, sr in sorted(result.sports.items()):
        verdict = "PASS" if sr.passes_acceptance else "FAIL"
        tail = "  TAIL-MISCAL" if sr.tail_miscalibration_after_isotonic else ""
        print(f"  [{verdict}] {sport_name:18}  "
              f"raw_slope={sr.raw_slope:.3f} (exceed={sr.raw_n_bins_exceeding_gap})  "
              f"iso_slope={sr.isotonic_slope:.3f} (exceed={sr.isotonic_n_bins_exceeding_gap})  "
              f"iso_D1={sr.isotonic_d1_gap:.3f}({sr.isotonic_d1_n}) "
              f"iso_D10={sr.isotonic_d10_gap:.3f}({sr.isotonic_d10_n}){tail}")
        if sr.tail_miscalibration_after_isotonic:
            auto_slip_sports.append(sport_name)
    print()
    if auto_slip_sports:
        print(f"[phase6] AUTO-SLIP TRIGGER fires per decisions.md 2026-05-26 evening:")
        print(f"[phase6]   Tail miscalibration after K-fold isotonic on: {auto_slip_sports}")
        print(f"[phase6]   Sept 1 → Sept 15 auto-slip rule fires AS DESIGNED.")
    elif result.n_failing > 0:
        print(f"[phase6] {result.n_failing} sport(s) FAIL non-tail acceptance (mid-bin gaps or slope band).")
        print(f"[phase6] These do NOT fire the auto-slip rule (decisions.md ties auto-slip to tail bins only).")
    else:
        print("[phase6] All sports PASS — engine candidate-final on calibration: CLEARED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
