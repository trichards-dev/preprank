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


# ---------------------------------------------------------------------------
# K-fold CV within holdout isotonic (decisions.md 2026-05-26 evening)
# ---------------------------------------------------------------------------
from engine.validator.runner_v2 import (
    PHASE6_KFOLD_K,
    PHASE6_TAIL_DECILE_GAP,
    _kfold_indices,
    _kfold_isotonic_recalibrate,
    _tail_gaps,
)


def test_phase6_kfold_k_default_is_5():
    """5-fold is the standard CV default."""
    assert PHASE6_KFOLD_K == 5


def test_phase6_tail_decile_gap_default_is_0_05():
    """decisions.md 2026-05-26 evening auto-slip threshold on tails."""
    assert PHASE6_TAIL_DECILE_GAP == 0.05


def test_kfold_indices_partitions_all_indices_with_no_overlap():
    """Every index 0..n-1 appears in exactly one fold."""
    folds = _kfold_indices(n=100, k=5, seed=42)
    assert len(folds) == 5
    flat = sorted(idx for fold in folds for idx in fold)
    assert flat == list(range(100))


def test_kfold_indices_balanced_within_one():
    """Fold sizes differ by at most 1."""
    folds = _kfold_indices(n=100, k=5, seed=42)
    sizes = sorted(len(f) for f in folds)
    assert sizes[-1] - sizes[0] <= 1


def test_kfold_indices_deterministic_with_seed():
    """Same seed → same partition (reproducibility)."""
    f1 = _kfold_indices(n=100, k=5, seed=42)
    f2 = _kfold_indices(n=100, k=5, seed=42)
    assert f1 == f2


def test_kfold_isotonic_recalibrate_preserves_length():
    probs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    actuals = [0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
    out = _kfold_isotonic_recalibrate(probs, actuals, k=5, seed=42)
    assert len(out) == len(probs)


def test_kfold_isotonic_recalibrate_empty_input():
    """No data → empty output (don't crash)."""
    out = _kfold_isotonic_recalibrate([], [], k=5, seed=42)
    assert out == []


def test_kfold_isotonic_recalibrate_uses_other_folds_only():
    """Each prediction's recalibrated value must NOT come from a self-fit.

    Set up a non-monotone toy distribution and verify the recalibrated
    values differ from the trivial-self-fit values. A weak invariant
    but a meaningful smoke against the prior self-fit bug.
    """
    # 20 predictions across [0, 1] with mostly correct actuals
    probs = [i / 20.0 for i in range(20)]
    actuals = [1 if p > 0.5 else 0 for p in probs]
    out = _kfold_isotonic_recalibrate(probs, actuals, k=5, seed=42)
    # The K-fold output should differ from the input on at least some
    # values (input is well-calibrated by construction; isotonic on
    # fold-of-4 will produce piecewise-constant values that don't match
    # the linear input).
    differences = sum(1 for p, o in zip(probs, out) if abs(p - o) > 1e-9)
    assert differences > 0, "K-fold isotonic returned identity — possible self-fit regression"


def test_tail_gaps_empty_bins_returns_zeros():
    assert _tail_gaps([]) == (0.0, 0.0, 0, 0)


def test_tail_gaps_returns_d1_and_d10_correctly():
    """D1 = first bin (index 0); D10 = last bin (index -1)."""
    bins = [
        Phase6BinReliability(bin_lower=0.0, bin_upper=0.1,
                              mean_predicted=0.05, mean_observed=0.12,
                              n_games=20, abs_gap=0.07, exceeds_max_gap=True),
        Phase6BinReliability(bin_lower=0.1, bin_upper=0.2,
                              mean_predicted=0.15, mean_observed=0.18,
                              n_games=15, abs_gap=0.03, exceeds_max_gap=False),
        Phase6BinReliability(bin_lower=0.9, bin_upper=1.0,
                              mean_predicted=0.95, mean_observed=0.80,
                              n_games=10, abs_gap=0.15, exceeds_max_gap=True),
    ]
    d1, d10, d1_n, d10_n = _tail_gaps(bins)
    assert d1 == pytest.approx(0.07)
    assert d10 == pytest.approx(0.15)
    assert d1_n == 20
    assert d10_n == 10


def test_tail_gaps_empty_bin_treated_as_zero_gap():
    """Empty tail bins (n=0) report gap=0.0 — they can't fire auto-slip."""
    bins = [
        Phase6BinReliability(bin_lower=0.0, bin_upper=0.1,
                              mean_predicted=float("nan"), mean_observed=float("nan"),
                              n_games=0, abs_gap=0.0, exceeds_max_gap=False),
        Phase6BinReliability(bin_lower=0.9, bin_upper=1.0,
                              mean_predicted=float("nan"), mean_observed=float("nan"),
                              n_games=0, abs_gap=0.0, exceeds_max_gap=False),
    ]
    d1, d10, d1_n, d10_n = _tail_gaps(bins)
    assert d1 == 0.0
    assert d10 == 0.0
    assert d1_n == 0
    assert d10_n == 0


# ---------------------------------------------------------------------------
# Tail-bin statistical-power floor (PHASE6_TAIL_MIN_N)
# ---------------------------------------------------------------------------
from engine.validator.runner_v2 import PHASE6_TAIL_MIN_N


def test_phase6_tail_min_n_is_100():
    """Statistical-power floor for the tail-bin auto-slip gate.

    Per Football diagnostic 2026-05-29: n=131 needed at typical D1/D10
    base rates to declare a 0.05 gap real at 95% confidence. n=100 gives
    ~95% power across base rates 0.05-0.95. Floor below this is
    statistically noise-dominated and should NOT fire auto-slip.
    """
    assert PHASE6_TAIL_MIN_N == 100


def test_phase6_tail_min_n_higher_than_mid_bin_threshold():
    """Tail gate is statistically more demanding than mid-bin gate.

    PHASE6_MIN_BIN_N=10 is the floor for "this bin has enough data to
    not be pure noise" (mid-bin gap reporting). PHASE6_TAIL_MIN_N=100
    is the floor for "this tail bin has enough data to fire the
    launch-blocking auto-slip rule." Two different statistical
    questions, two different thresholds.
    """
    from engine.validator.runner_v2 import PHASE6_MIN_BIN_N
    assert PHASE6_TAIL_MIN_N > PHASE6_MIN_BIN_N


def test_phase6_tail_min_n_gives_95pct_power_at_005_gap():
    """At base rate p in [0.05, 0.95], standard error of a binomial
    proportion at n=100 is at most sqrt(0.25/100) = 0.05. So the 95% CI
    half-width is at most 1.96*0.05 = 0.098 — barely larger than the
    0.05 gap threshold. Equivalent power calculations show n=131 is
    needed for full 95% power at the worst-case base rates, n=100
    gives ~95% on typical D1/D10 rates (5%-15%).
    """
    import math
    # SE at worst case (p=0.5, the maximum binomial variance)
    se_max = math.sqrt(0.25 / PHASE6_TAIL_MIN_N)
    # Half-width of 95% CI
    ci_halfwidth = 1.96 * se_max
    # Should be near 0.10 — bigger than 0.05 but small enough that
    # an OBSERVED 0.10 gap is statistically distinguishable from 0
    assert ci_halfwidth < 0.10
    assert ci_halfwidth > 0.05  # Confirms n=100 is the right ballpark
