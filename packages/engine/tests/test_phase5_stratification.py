"""Tests for Phase 5 Q1-Q4 competitive stratification runner.

Reese 2026-05-29 directive: same discipline as Phase 4d/4e. The
stratify primitive itself is unit-tested in test_validator_framework.py;
these tests cover the Phase 5 runner wiring + dataclass surface.
"""
from __future__ import annotations

from dataclasses import is_dataclass
from datetime import datetime

import pytest

from engine.validator.runner_v2 import (
    PHASE5_PINNED_INDICES,
    Phase5Result,
    SportPhase5Result,
)


# ---------------------------------------------------------------------------
# Pin-index constant
# ---------------------------------------------------------------------------
def test_phase5_pinned_indices_pins_beta_3_only():
    """Phase 5 fit pins β₃ (Phase 4c disposition) and leaves β₄/β₅/β₆ free.

    This matches the engine candidate-final config: β₃ pinned at 0; the
    other slots fit to whatever the regression lands at given the
    promoted features from Phase 4d Step 4 + Phase 4e.
    """
    assert set(PHASE5_PINNED_INDICES) == {3}


def test_phase5_pinned_indices_does_not_pin_beta_4():
    """β₄ stays FREE so Massey signal contributes per the Phase 4d
    disposition (audit-triggered sports get the lift; Football
    collapses to 0 naturally; Boys Basketball lands in noise band).
    """
    assert 4 not in PHASE5_PINNED_INDICES


def test_phase5_pinned_indices_does_not_pin_beta_5():
    """β₅ stays FREE so prior-year-carryover signal contributes per the
    Phase 4e disposition.
    """
    assert 5 not in PHASE5_PINNED_INDICES


def test_phase5_pinned_indices_does_not_pin_beta_6():
    """β₆ stays FREE per Phase 4b recent-form promotion."""
    assert 6 not in PHASE5_PINNED_INDICES


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------
def test_sport_phase5_result_holds_quartiles_and_overall_metrics():
    assert is_dataclass(SportPhase5Result)
    fields = SportPhase5Result.__dataclass_fields__
    for required in (
        "sport", "fit", "n_holdout",
        "overall_accuracy", "overall_brier", "quartiles",
    ):
        assert required in fields, f"missing field: {required}"


def test_phase5_result_holds_sports_dict_and_warnings():
    assert is_dataclass(Phase5Result)
    fields = Phase5Result.__dataclass_fields__
    for required in (
        "config_label", "run_id", "timestamp",
        "train_seasons", "holdout_seasons", "drop_seasons",
        "sports", "fit_warnings",
    ):
        assert required in fields, f"missing field: {required}"


def test_phase5_result_constructs_with_defaults():
    r = Phase5Result(
        config_label="x", run_id="rid",
        timestamp=datetime(2026, 5, 29),
        train_seasons=[2022, 2023, 2024],
        holdout_seasons=[2025],
        drop_seasons=[2021],
    )
    assert r.sports == {}
    assert r.fit_warnings == []


def test_sport_phase5_result_quartiles_default_is_empty_list():
    """Each instance gets its own list (no mutable default leak)."""
    # Constructed via dataclass with required fields. We don't need a
    # FitResult instance for this test — just verify the field default.
    from engine.validator.runner_v2 import SportPhase5Result
    # Inspect the dataclass field default
    field = SportPhase5Result.__dataclass_fields__["quartiles"]
    # Default uses field(default_factory=list) so checking factory:
    assert field.default_factory is list  # type: ignore[comparison-overlap]
