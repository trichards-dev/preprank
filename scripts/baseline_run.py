"""Canonical baseline-run CLI for the v2 walk-forward validator.

Per Reese's 2026-05-25 Path C spec, this is the STRUCTURE of the baseline
run. It is intentionally NOT invoked here — the actual baseline numbers
will only be generated AFTER the OOS-fix re-scrape lands and the post-fix
data is verified clean. Until then this script is the wiring that future
work (TASK 4 feature phases) will measure lift against.

Usage (post-OOS-fix-rescrape, NOT until then):

    python scripts/baseline_run.py --config-label wf-baseline-v2 \
        [--persist-predictions]

Output: reports/walk_forward/<config_label>/<run-id>/{summary.json,
per_game_log.csv, reliability_plot.png, report.md}.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow direct invocation outside an installed package
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "packages", "engine", "src"))

from dotenv import load_dotenv

from engine.prediction.config import PredictionConfig
from engine.validator.walk_forward import WalkForwardConfig, run as run_wf


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / "apps" / "api" / ".env")

    p = argparse.ArgumentParser(prog="python scripts/baseline_run.py")
    p.add_argument("--config-label", default="wf-baseline-v2",
                   help="config_label tag for predictions table + report dir")
    p.add_argument("--sports", default=None,
                   help="comma-list of sport names; default = all")
    p.add_argument("--persist-predictions", action="store_true",
                   help="write per-game predictions to game_predictions table")
    p.add_argument("--output-root", default="reports/walk_forward",
                   help="root output directory for per-config artifacts")
    args = p.parse_args(argv)

    # Baseline = no feature flags enabled; pure rating-diff prediction.
    # Future phase-comparison runs flip flags on individual features.
    baseline_prediction = PredictionConfig()

    wf_cfg = WalkForwardConfig(
        config_label=args.config_label,
        prediction_config=baseline_prediction,
        sports=args.sports.split(",") if args.sports else None,
        persist_predictions=args.persist_predictions,
    )

    print(f"[baseline_run] config_label={wf_cfg.config_label}")
    print(f"[baseline_run] train={wf_cfg.train_seasons}, holdout={wf_cfg.holdout_seasons}, drop={wf_cfg.drop_seasons}")
    print(f"[baseline_run] sports={wf_cfg.sports or 'all'}")
    print()
    print("=" * 60)
    print("This is the STRUCTURE for the baseline run.")
    print("Per the 2026-05-25 Path C spec, the actual baseline numbers")
    print("are not generated until the OOS-fix re-scrape lands.")
    print("=" * 60)
    print()

    result = run_wf(wf_cfg, output_root=args.output_root)
    print(f"[baseline_run] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
