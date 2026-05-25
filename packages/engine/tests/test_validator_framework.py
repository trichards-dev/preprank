"""Unit tests for the v2 walk-forward validator framework.

Covers: walk_forward.py, stratify.py, calibration.py, fdr.py.
No DB access; synthetic fixtures only. Per Reese's 2026-05-25 Path C
constraint, no real model accuracy numbers are computed here either.
"""
from __future__ import annotations

import math

from engine.validator.calibration import (
    IsotonicRegressor,
    calibration_slope_intercept,
    needs_recalibration,
)
from engine.validator.fdr import benjamini_hochberg, family_decision
from engine.validator.stratify import quartile_split, stratify
from engine.validator.walk_forward import (
    WF_DEFAULT_DROP,
    WF_DEFAULT_HOLDOUT,
    WF_DEFAULT_TRAIN,
    WalkForwardConfig,
    seasons_for_run,
)


# ---------------------------------------------------------------------------
# walk_forward.py
# ---------------------------------------------------------------------------
def test_default_walk_forward_drops_2021_keeps_22_25():
    cfg = WalkForwardConfig(
        config_label="x",
        prediction_config=None,  # not used by seasons_for_run
    )
    assert seasons_for_run(cfg) == [2022, 2023, 2024, 2025]
    assert WF_DEFAULT_DROP == [2021]
    assert WF_DEFAULT_TRAIN == [2022, 2023, 2024]
    assert WF_DEFAULT_HOLDOUT == [2025]


def test_walk_forward_seasons_can_be_overridden():
    cfg = WalkForwardConfig(
        config_label="x",
        prediction_config=None,
        train_seasons=[2020, 2021],
        holdout_seasons=[2022],
        drop_seasons=[],
    )
    assert seasons_for_run(cfg) == [2020, 2021, 2022]


# ---------------------------------------------------------------------------
# stratify.py
# ---------------------------------------------------------------------------
def test_quartile_split_with_uniform_distribution():
    # 100 evenly-spaced values 0..99 → quartile breaks at 25, 50, 75
    breaks = quartile_split([float(i) for i in range(100)])
    assert breaks == [25.0, 50.0, 75.0]


def test_stratify_splits_into_4_quartiles_by_abs_rating_diff():
    from engine.validator.predictor import PredictionRecord
    # 100 predictions with rating_diff 0..99; all "home wins"
    predictions = [
        PredictionRecord(
            game_id=i, home_team_id=1, away_team_id=2,
            home_win_probability=0.5 + (i / 200.0),
            predicted_home_score=None, predicted_away_score=None,
            predicted_spread=None,
            home_rating_pregame=float(i), away_rating_pregame=0.0,
            home_cold_start=False, away_cold_start=False,
            actual_home_won=True, sport="Football", season_year=2025,
            week_number=10,
        )
        for i in range(100)
    ]
    results = stratify(predictions, n_bootstrap=50, seed=42)
    assert len(results) == 4
    # Boundary inclusion makes exact 25-per-bucket impossible; verify
    # bucket sizes are within ±2 of 25 each and total to 100.
    sizes = [r.n_games for r in results]
    assert sum(sizes) == 100
    for s in sizes:
        assert abs(s - 25) <= 2
    assert results[0].quartile == 1
    assert 0.0 <= results[0].rating_diff_min <= results[0].rating_diff_max <= 25.0
    assert results[3].quartile == 4
    assert results[3].rating_diff_min >= 75.0


def test_stratify_handles_empty():
    assert stratify([]) == []


# ---------------------------------------------------------------------------
# calibration.py
# ---------------------------------------------------------------------------
def test_calibration_slope_intercept_perfect_fit():
    # Perfect calibration: observed = predicted
    preds = [0.1, 0.3, 0.5, 0.7, 0.9]
    obs = [0, 0, 1, 1, 1]
    fit = calibration_slope_intercept(preds, obs)
    # Best linear fit through (0.1, 0), (0.3, 0), (0.5, 1), (0.7, 1), (0.9, 1)
    # mean_x = 0.5, mean_y = 0.6; slope = sum((x-0.5)(y-0.6)) / sum((x-0.5)^2)
    assert fit.n_games == 5
    assert math.isclose(fit.slope, 1.5, abs_tol=0.01)
    assert math.isclose(fit.intercept, -0.15, abs_tol=0.01)


def test_needs_recalibration_thresholds():
    perfect = type("F", (), {"slope": 1.0})()
    flat = type("F", (), {"slope": 0.80})()
    steep = type("F", (), {"slope": 1.20})()
    assert needs_recalibration(perfect) is False
    assert needs_recalibration(flat) is True
    assert needs_recalibration(steep) is True


def test_isotonic_regressor_monotone_output():
    # Train on monotonically-increasing pairs
    preds = [0.1, 0.2, 0.4, 0.6, 0.8, 0.95]
    actuals = [0, 0, 0, 1, 1, 1]
    iso = IsotonicRegressor.fit(preds, actuals)
    transformed = iso.transform([0.05, 0.3, 0.5, 0.7, 0.99])
    # Output should be monotonically non-decreasing
    for i in range(1, len(transformed)):
        assert transformed[i] >= transformed[i - 1]


def test_isotonic_regressor_violators_get_pooled():
    # Train on a violator: pred 0.3 has actual 1, pred 0.7 has actual 0
    preds = [0.1, 0.3, 0.7, 0.9]
    actuals = [0, 1, 0, 1]
    iso = IsotonicRegressor.fit(preds, actuals)
    # PAV should pool (0.3, 1) and (0.7, 0) → both become 0.5
    transformed = iso.transform([0.3, 0.7])
    assert transformed[0] == transformed[1] == 0.5


# ---------------------------------------------------------------------------
# fdr.py
# ---------------------------------------------------------------------------
def test_benjamini_hochberg_classical_example():
    # 8 p-values at alpha=0.05. Hand check:
    #   k=1: 0.001 ≤ (1/8)*0.05 = 0.006 ✓
    #   k=2: 0.008 ≤ (2/8)*0.05 = 0.013 ✓
    #   k=3: 0.039 > (3/8)*0.05 = 0.019  ✗
    #   ... rest also exceed their thresholds
    # Largest k with p_(k) ≤ (k/m)*alpha is k=2, so we reject first 2.
    pvals = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
    flags = benjamini_hochberg(pvals, alpha=0.05)
    assert flags == [True, True, False, False, False, False, False, False]


def test_benjamini_hochberg_empty():
    assert benjamini_hochberg([], alpha=0.05) == []


def test_benjamini_hochberg_all_significant():
    flags = benjamini_hochberg([0.001, 0.002, 0.003], alpha=0.05)
    assert flags == [True, True, True]


def test_benjamini_hochberg_none_significant():
    flags = benjamini_hochberg([0.9, 0.95, 0.99], alpha=0.05)
    assert flags == [False, False, False]


def test_family_decision_routing():
    assert family_decision([True, True, True]) == "all-accept"
    assert family_decision([True, False, True]) == "some-accept"
    assert family_decision([False, False, False]) == "none-accept"
    assert family_decision([]) == "none-accept"
