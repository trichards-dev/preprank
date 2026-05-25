"""Walk-forward validator entry point per the v2 plan's modified-(b) regime.

Reese's 2026-05-25 spec: drop 2021 (pre-2022-restructure for Football),
train on [2022, 2023, 2024], validate on [2025]. A single fold rather
than the originally-proposed 3-fold walk-forward — the regime-change
boundary at 2022 makes the older folds load-bearing on phantom-Div-V
data that's now been cleaned out.

This module is intentionally thin: it wraps the existing
``runner.run_validation`` with the right defaults and surfaces the
walk-forward shape so feature-phase work can call into it without
re-deriving the fold rules.

No model accuracy numbers are emitted until the OOS-fix re-scrape lands
and the post-fix baseline runs clean (per Reese's Path C constraint).
This module is the wiring; ``scripts/baseline_run.py`` is the CLI.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.prediction.config import PredictionConfig

from . import runner as _runner

# Modified-(b) regime per 2026-05-25 spec
WF_DEFAULT_DROP: list[int] = [2021]
WF_DEFAULT_TRAIN: list[int] = [2022, 2023, 2024]
WF_DEFAULT_HOLDOUT: list[int] = [2025]


@dataclass
class WalkForwardConfig:
    """All knobs that distinguish a walk-forward run.

    `train_seasons` and `holdout_seasons` are explicit so future work
    can swap to a true k-fold by varying these.

    Compound configs are stitched together by `scripts/baseline_run.py`
    (and successors) rather than hardcoded here so the framework stays
    feature-agnostic.
    """
    config_label: str
    prediction_config: PredictionConfig
    train_seasons: list[int] = field(default_factory=lambda: list(WF_DEFAULT_TRAIN))
    holdout_seasons: list[int] = field(default_factory=lambda: list(WF_DEFAULT_HOLDOUT))
    drop_seasons: list[int] = field(default_factory=lambda: list(WF_DEFAULT_DROP))
    sports: list[str] | None = None    # None = all sports per validator.data.ALL_SPORTS
    persist_predictions: bool = False  # off by default; turn on for the canonical baseline


def seasons_for_run(cfg: WalkForwardConfig) -> list[int]:
    """Concrete season list passed to the underlying runner — train + holdout
    minus drop. The runner internally treats holdout as validation; train
    seasons are the (eventually) coefficient-fitting set."""
    keep = set(cfg.train_seasons + cfg.holdout_seasons) - set(cfg.drop_seasons)
    return sorted(keep)


def run(cfg: WalkForwardConfig, output_root: str | None = None):
    """Execute one walk-forward run.

    DOES NOT execute any numbers reporting on its own. The caller (e.g.
    `scripts/baseline_run.py`) decides what to do with the returned
    object. Per Reese's Path C: no model-accuracy numbers leave the
    system until the OOS-fix re-scrape lands.

    Returns whatever `runner.run_validation` returns.
    """
    return _runner.run_validation(
        config_label=cfg.config_label,
        prediction_config=cfg.prediction_config,
        seasons=seasons_for_run(cfg),
        holdout_seasons=cfg.holdout_seasons,
        sports=cfg.sports,
        persist_predictions=cfg.persist_predictions,
        output_root=output_root,
    )
