"""Tests for Phase 6 calibration + per-decile reliability audit runner.

Per decisions.md 2026-05-26 launch-date lock: Phase 6 is the gate for
engine candidate-final. Auto-slip (Sept 1 → Sept 15) fires on
uncorrectable tail miscalibration AFTER isotonic recalibration.
"""
from __future__ import annotations

from dataclasses import is_dataclass
from datetime import datetime

import pytest

from engine.validator.runner_v2 import (
    PHASE6_MAX_BIN_GAP,
    PHASE6_MIN_BIN_N,
    PHASE6_PINNED_INDICES,
    PHASE6_SLOPE_BAND,
    Phase6BinReliability,
    Phase6Result,
    Phase6SportResult,
    _bins_to_phase6,
)


# ---------------------------------------------------------------------------
# Constants — gates from decisions.md 2026-05-26
# ---------------------------------------------------------------------------
def test_phase6_pinned_indices_pins_beta_3_only():
    """Same fit config as Phase 5 — engine candidate-final."""
    assert set(PHASE6_PINNED_INDICES) == {3}


def test_phase6_slope_band_is_0_85_to_1_15():
    """v2 plan §6.4 recalibration trigger band."""
    assert PHASE6_SLOPE_BAND == (0.85, 1.15)


def test_phase6_max_bin_gap_is_0_05():
    """decisions.md 2026-05-26 auto-slip gate."""
    assert PHASE6_MAX_BIN_GAP == 0.05


def test_phase6_min_bin_n_is_10():
    """Small bins are pure noise — exclude from gap check."""
    assert PHASE6_MIN_BIN_N == 10


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------
def test_phase6_bin_reliability_has_required_fields():
    assert is_dataclass(Phase6BinReliability)
    b = Phase6BinReliability(
        bin_lower=0.0, bin_upper=0.1,
        mean_predicted=0.05, mean_observed=0.08,
        n_games=20, abs_gap=0.03, exceeds_max_gap=False,
    )
    assert b.abs_gap == 0.03
    assert b.exceeds_max_gap is False


def test_phase6_sport_result_dataclass_has_raw_and_iso_fields():
    assert is_dataclass(Phase6SportResult)
    fields = Phase6SportResult.__dataclass_fields__
    for required in (
        "sport", "fit", "n_holdout",
        "raw_slope", "raw_intercept", "raw_slope_in_band",
        "raw_bins", "raw_n_bins_exceeding_gap",
        "isotonic_applied", "isotonic_slope", "isotonic_slope_in_band",
        "isotonic_bins", "isotonic_n_bins_exceeding_gap",
        "passes_acceptance",
    ):
        assert required in fields, f"missing field: {required}"


def test_phase6_result_dataclass_has_passing_failing_counts():
    assert is_dataclass(Phase6Result)
    fields = Phase6Result.__dataclass_fields__
    assert "n_passing" in fields
    assert "n_failing" in fields
    r = Phase6Result(
        config_label="x", run_id="rid",
        timestamp=datetime(2026, 5, 29),
        train_seasons=[2022], holdout_seasons=[2025], drop_seasons=[2021],
    )
    assert r.n_passing == 0
    assert r.n_failing == 0


# ---------------------------------------------------------------------------
# _bins_to_phase6
# ---------------------------------------------------------------------------
def test_bins_to_phase6_empty_bins_marked_not_exceeding():
    """Empty bins (n_games=0) don't count as exceeding."""
    bins_in = [
        {"bin_lower": 0.0, "bin_upper": 0.1,
         "mean_predicted": float("nan"), "mean_observed": float("nan"),
         "n_games": 0},
    ]
    out, n_exceed = _bins_to_phase6(bins_in)
    assert len(out) == 1
    assert out[0].exceeds_max_gap is False
    assert n_exceed == 0


def test_bins_to_phase6_large_bin_with_big_gap_exceeds():
    """n>=10 and |gap|>0.05 → flagged."""
    bins_in = [
        {"bin_lower": 0.1, "bin_upper": 0.2,
         "mean_predicted": 0.15, "mean_observed": 0.30,
         "n_games": 25},
    ]
    out, n_exceed = _bins_to_phase6(bins_in)
    assert len(out) == 1
    assert out[0].abs_gap == pytest.approx(0.15)
    assert out[0].exceeds_max_gap is True
    assert n_exceed == 1


def test_bins_to_phase6_small_bin_with_big_gap_does_not_exceed():
    """n<10 → noise, exclude even if |gap|>0.05."""
    bins_in = [
        {"bin_lower": 0.1, "bin_upper": 0.2,
         "mean_predicted": 0.15, "mean_observed": 0.30,
         "n_games": 7},
    ]
    out, n_exceed = _bins_to_phase6(bins_in)
    assert out[0].exceeds_max_gap is False
    assert n_exceed == 0


def test_bins_to_phase6_large_bin_with_small_gap_does_not_exceed():
    """n>=10 but |gap|<=0.05 → within tolerance."""
    bins_in = [
        {"bin_lower": 0.4, "bin_upper": 0.5,
         "mean_predicted": 0.45, "mean_observed": 0.48,
         "n_games": 30},
    ]
    out, n_exceed = _bins_to_phase6(bins_in)
    assert out[0].exceeds_max_gap is False
    assert n_exceed == 0


def test_bins_to_phase6_counts_multiple_exceeding_bins():
    bins_in = [
        {"bin_lower": 0.0, "bin_upper": 0.1,
         "mean_predicted": 0.05, "mean_observed": 0.13,  # gap 0.08
         "n_games": 20},
        {"bin_lower": 0.1, "bin_upper": 0.2,
         "mean_predicted": 0.15, "mean_observed": 0.16,  # gap 0.01
         "n_games": 30},
        {"bin_lower": 0.9, "bin_upper": 1.0,
         "mean_predicted": 0.95, "mean_observed": 0.80,  # gap 0.15
         "n_games": 25},
    ]
    out, n_exceed = _bins_to_phase6(bins_in)
    assert n_exceed == 2
    assert [b.exceeds_max_gap for b in out] == [True, False, True]
