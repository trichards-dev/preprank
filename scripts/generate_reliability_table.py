"""Generate the per-sport per-decile reliability table for the forecast API.

Reads the Phase 6 K-fold isotonic run summary and writes a lean JSON
blob consumed by /api/v1/games/{id}/forecast at runtime. Run once per
Phase 6 audit cycle (NOT per engine refit per the API design Q2
decision).

Per `confidence_disclosure_ux_options_2026-05-29.md` Specs 2 + 5 and
`forecast_api_design_2026-05-29.md`:
  - 10 deciles per sport
  - Each decile entry carries: n_games, mean_predicted, mean_observed,
    gap (abs of mean_predicted - mean_observed), bin_lower, bin_upper
  - The calibration_run_id is captured to thread through to API
    responses for ops debugging + transparency

Output: data/calibration/phase6_reliability_table.json
Input:  reports/walk_forward/wf-phase6-calibration-kfold-tail-power-n139/<run>/summary.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT = (
    REPO_ROOT
    / "reports"
    / "walk_forward"
    / "wf-phase6-calibration-kfold-tail-power-n139"
    / "2026-05-29-1744"
    / "summary.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "data" / "calibration" / "phase6_reliability_table.json"


def _decile_entry(b: dict) -> dict:
    """Reduce a Phase6BinReliability dict to the lean shape the API consumes."""
    return {
        "bin_lower": float(b["bin_lower"]),
        "bin_upper": float(b["bin_upper"]),
        "n_games": int(b["n_games"]),
        "mean_predicted": (
            float(b["mean_predicted"]) if b.get("mean_predicted") is not None else None
        ),
        "mean_observed": (
            float(b["mean_observed"]) if b.get("mean_observed") is not None else None
        ),
        "gap": float(b["abs_gap"]),
    }


def build_reliability_table(summary: dict) -> dict[str, Any]:
    """Build the lean per-sport per-decile table for API consumption."""
    sports_out: dict[str, Any] = {}
    for sport_name, sr in summary.get("sports", {}).items():
        # Use the POST-isotonic bins (K-fold CV recalibrated) — these are
        # the ones the auto-slip rule fires on; they're the data layer the
        # forecast endpoint reasons about.
        iso_bins = sr.get("isotonic_bins") or []
        sports_out[sport_name] = {
            "isotonic_slope": float(sr["isotonic_slope"]),
            "isotonic_slope_in_band": bool(sr["isotonic_slope_in_band"]),
            "deciles": [_decile_entry(b) for b in iso_bins],
            "tail_miscalibration_after_isotonic": bool(
                sr.get("tail_miscalibration_after_isotonic", False)
            ),
            "model_coefficients": dict(sr.get("fit", {}).get("coefficients", {})),
        }
    return {
        "schema_version": 1,
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "calibration_run_id": summary.get("config_label"),
        "run_timestamp": str(summary.get("timestamp", "")),
        "train_seasons": summary.get("train_seasons", []),
        "holdout_seasons": summary.get("holdout_seasons", []),
        "sports": sports_out,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python scripts/generate_reliability_table.py")
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                   help=f"Phase 6 summary.json (default: {DEFAULT_INPUT.relative_to(REPO_ROOT)})")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                   help=f"Output table JSON (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})")
    args = p.parse_args(argv)

    if not args.input.exists():
        print(f"[reliability_table] input not found: {args.input}", file=sys.stderr)
        return 1

    summary = json.loads(args.input.read_text())
    table = build_reliability_table(summary)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(table, indent=2))

    print(f"[reliability_table] {len(table['sports'])} sports written to {args.output}")
    print(f"[reliability_table] calibration_run_id = {table['calibration_run_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
