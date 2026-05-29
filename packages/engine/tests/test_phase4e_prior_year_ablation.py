"""Tests for Phase 4e prior-year carryover (β₅) ablation runner.

Reese 2026-05-29 design decisions:
  - Stricter null: β₃ + β₄ + β₅ all pinned in the ablation; reference
    has β₅ free with β₄ pinned (so β₄ cannot absorb β₅'s signal).
  - Two measurements per sport: weeks_1_3 (PRIMARY) and full_season
    (SECONDARY).
  - Cold-start games KEPT in holdout (they're the population β₅ targets).

Test coverage:
  - PHASE4E_REF_PINNED_INDICES and PHASE4E_ABL_PINNED_INDICES are
    correct + differ by exactly {5} + nest the Phase 4d β₃ pin.
  - _filter_rows_weeks_1_3 keeps weeks 1-3 and drops weeks >=4.
  - _filter_rows_weeks_1_3 handles empty input, single-week input, and
    weeks-0 edge.
  - _measure_phase4e_lift returns a degenerate-zero Phase4eMeasurement
    on empty holdout.
  - _measure_phase4e_lift labels match the input label argument.
  - Phase4eMeasurement / SportPhase4eResult / Phase4eResult dataclass
    fields are present (smoke).
  - Two FDR flows (primary + secondary) increment separately.
"""
from __future__ import annotations

from dataclasses import is_dataclass

import pytest

from engine.prediction.model import GameState
from engine.prediction.config import PredictionConfig
from engine.validator.runner_v2 import (
    PHASE4E_ABL_PINNED_INDICES,
    PHASE4E_REF_PINNED_INDICES,
    Phase4eMeasurement,
    Phase4eResult,
    SportPhase4eResult,
    GameTrainingRow,
    _filter_rows_weeks_1_3,
    _measure_phase4e_lift,
)


# ---------------------------------------------------------------------------
# Pin-index constants
# ---------------------------------------------------------------------------
def test_phase4e_ref_pinned_indices_pins_3_and_4_only():
    """Reference fit pins β₃ (Phase 4c disposition) + β₄ (cannot absorb β₅).

    β₅ stays FREE so its coefficient is fit from data.
    """
    assert set(PHASE4E_REF_PINNED_INDICES) == {3, 4}
    assert 5 not in PHASE4E_REF_PINNED_INDICES


def test_phase4e_abl_pinned_indices_pins_3_4_and_5():
    """Ablation pins β₃ + β₄ + β₅ (stricter null)."""
    assert set(PHASE4E_ABL_PINNED_INDICES) == {3, 4, 5}


def test_phase4e_ref_abl_differ_by_exactly_beta_5():
    """The only difference between reference and ablation fits is β₅."""
    diff = set(PHASE4E_ABL_PINNED_INDICES) - set(PHASE4E_REF_PINNED_INDICES)
    assert diff == {5}, f"unexpected diff: {diff}"


def test_phase4e_indices_contain_phase4c_pin():
    """β₃ stays pinned across all post-Phase-4c fits (no margin slot)."""
    assert 3 in PHASE4E_REF_PINNED_INDICES
    assert 3 in PHASE4E_ABL_PINNED_INDICES


# ---------------------------------------------------------------------------
# _filter_rows_weeks_1_3
# ---------------------------------------------------------------------------
def _row(week: int, *, prior_h: float | None = 1.0, prior_a: float | None = 1.0):
    return GameTrainingRow(
        home_state=GameState(
            rating=0.0, margin_signal=0.0, off_signal=0.0, def_signal=0.0,
            prior_year_rating=prior_h, recent_form_signal=0.0,
            week_number=week, season_year=2025,
        ),
        away_state=GameState(
            rating=0.0, margin_signal=0.0, off_signal=0.0, def_signal=0.0,
            prior_year_rating=prior_a, recent_form_signal=0.0,
            week_number=week, season_year=2025,
        ),
        is_neutral_site=False,
        is_mercy=False,
        home_won=False,
    )


def test_filter_rows_weeks_1_3_keeps_weeks_1_through_3():
    rows = [_row(1), _row(2), _row(3)]
    out = _filter_rows_weeks_1_3(rows)
    assert len(out) == 3
    assert {r.home_state.week_number for r in out} == {1, 2, 3}


def test_filter_rows_weeks_1_3_drops_weeks_4_and_higher():
    """β₅ structurally fires only weeks 1-3 via _decay()."""
    rows = [_row(1), _row(2), _row(3), _row(4), _row(5), _row(11)]
    out = _filter_rows_weeks_1_3(rows)
    assert {r.home_state.week_number for r in out} == {1, 2, 3}


def test_filter_rows_weeks_1_3_drops_week_zero_and_negative():
    """Edge cases on week_number lower bound."""
    rows = [_row(0), _row(-1), _row(1)]
    out = _filter_rows_weeks_1_3(rows)
    assert [r.home_state.week_number for r in out] == [1]


def test_filter_rows_weeks_1_3_empty_input():
    assert _filter_rows_weeks_1_3([]) == []


# ---------------------------------------------------------------------------
# _measure_phase4e_lift
# ---------------------------------------------------------------------------
def test_measure_phase4e_lift_empty_holdout_returns_degenerate_zero():
    """No holdout rows → measurement with n_holdout=0 and p=1.0."""
    cfg = PredictionConfig()
    m = _measure_phase4e_lift(
        "weeks_1_3", [], "Football", cfg, cfg, n_bootstrap=10, seed=1,
    )
    assert m.label == "weeks_1_3"
    assert m.n_holdout == 0
    assert m.accuracy_lift == 0.0
    assert m.brier_lift == 0.0
    assert m.p_value_one_sided == 1.0
    assert m.significant_after_fdr is False


def test_measure_phase4e_lift_label_threads_through():
    """The label argument lands on the returned Phase4eMeasurement."""
    cfg = PredictionConfig()
    m1 = _measure_phase4e_lift(
        "weeks_1_3", [], "Football", cfg, cfg, n_bootstrap=10, seed=1,
    )
    m2 = _measure_phase4e_lift(
        "full_season", [], "Football", cfg, cfg, n_bootstrap=10, seed=1,
    )
    assert m1.label == "weeks_1_3"
    assert m2.label == "full_season"


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------
def test_phase4e_measurement_is_dataclass_with_label_and_significance():
    assert is_dataclass(Phase4eMeasurement)
    m = Phase4eMeasurement(
        label="weeks_1_3", n_holdout=10,
        baseline_accuracy=0.6, ablation_accuracy=0.55,
        accuracy_lift=0.05, accuracy_lift_ci=(0.01, 0.09),
        baseline_brier=0.2, ablation_brier=0.22,
        brier_lift=-0.02, brier_lift_ci=(-0.04, 0.0),
        p_value_one_sided=0.01,
    )
    assert m.significant_after_fdr is False  # default


def test_sport_phase4e_result_holds_both_measurements_and_diagnostic():
    """SportPhase4eResult must surface weeks_1_3 + full_season + _pyc=0 share."""
    assert is_dataclass(SportPhase4eResult)
    fields = SportPhase4eResult.__dataclass_fields__
    for required in (
        "weeks_1_3", "full_season",
        "n_pyc_zero_holdout",
        "n_pyc_zero_genuine_coldstart",
        "n_pyc_zero_data_gap",
    ):
        assert required in fields, f"missing field: {required}"


def test_phase4e_result_has_separate_primary_and_secondary_fdr_counts():
    """Phase4eResult tracks FDR-significance separately for the two
    measurement scopes (primary = weeks_1_3, secondary = full_season).
    """
    assert is_dataclass(Phase4eResult)
    fields = Phase4eResult.__dataclass_fields__
    assert "n_significant_after_fdr_primary" in fields
    assert "n_significant_after_fdr_secondary" in fields
    # Default counts start at 0
    from datetime import datetime
    r = Phase4eResult(
        config_label="x", run_id="rid", timestamp=datetime(2026, 5, 29),
        train_seasons=[2022], holdout_seasons=[2025], drop_seasons=[2021],
    )
    assert r.n_significant_after_fdr_primary == 0
    assert r.n_significant_after_fdr_secondary == 0
