"""Tests for ``engine.prediction.model`` — v2 logistic-regression model.

Coverage maps to the verification checklist in ``docs/model_specification.md``
"Implementation contract" plus a few extras for the smaller invariants.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from engine.prediction.config import PredictionConfig
from engine.prediction.model import (
    COEF_NAMES,
    FitConvergenceError,
    GameState,
    GameTrainingRow,
    MissingCoefficientsError,
    _decay,
    _feature_vector,
    _pyc,
    fit_sport,
    predict_game_v3,
)
from engine.win_probability import win_probability_v2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_synthetic_games(
    n: int,
    true_beta: list[float],
    *,
    seed: int = 7,
    neutral_fraction: float = 0.5,
) -> list[GameTrainingRow]:
    """Generate ``n`` games whose outcomes follow the model exactly.

    Features are drawn from controlled distributions so the design
    matrix is well-conditioned. Outcomes are Bernoulli draws from the
    true logistic. ``neutral_fraction`` defaults to 0.5 so β₀ and β₂
    are cleanly identified — in real data HFA_indicator is ~always 1
    making the two collinear, but for recovery tests we balance them.

    ``true_beta`` is padded with zeros at the tail to length
    ``N_FEATURES`` — this keeps test data forward-compatible when
    coefficient slots are added (β₆ added 2026-05-26 for Phase 4b).
    """
    # Forward-compatible padding: existing tests pass length-6 true_beta;
    # newly-added slots default to 0 in the data-generating model.
    from engine.prediction.model import N_FEATURES

    padded = list(true_beta) + [0.0] * (N_FEATURES - len(true_beta))
    if len(padded) > N_FEATURES:
        raise AssertionError(
            f"true_beta length {len(true_beta)} exceeds N_FEATURES={N_FEATURES}"
        )

    rng = np.random.default_rng(seed)
    rows: list[GameTrainingRow] = []
    for _ in range(n):
        # Δrating ~ N(0, 5) covers the realistic range of HS power-rating diffs
        h_rating = rng.normal(0.0, 5.0)
        a_rating = rng.normal(0.0, 5.0)
        # Other signals: smaller spread so β fits are stable per-feature
        h_margin = rng.normal(0.0, 1.0)
        a_margin = rng.normal(0.0, 1.0)
        h_off = rng.normal(0.0, 1.0)
        a_off = rng.normal(0.0, 1.0)
        h_def = rng.normal(0.0, 1.0)
        a_def = rng.normal(0.0, 1.0)
        h_form = rng.normal(0.0, 1.0)
        a_form = rng.normal(0.0, 1.0)
        # Prior-year ratings: present for ~half the rows; missing for the rest
        h_prior = rng.normal(0.0, 5.0) if rng.random() < 0.5 else None
        a_prior = rng.normal(0.0, 5.0) if rng.random() < 0.5 else None
        # Week 1-3 only for Δf_pyc to be non-zero; otherwise the feature
        # is always 0 and β₅ would be unidentified
        week = int(rng.integers(1, 4))
        is_neutral = bool(rng.random() < neutral_fraction)

        home = GameState(
            rating=h_rating,
            margin_signal=h_margin,
            off_signal=h_off,
            def_signal=h_def,
            prior_year_rating=h_prior,
            recent_form_signal=h_form,
            week_number=week,
        )
        away = GameState(
            rating=a_rating,
            margin_signal=a_margin,
            off_signal=a_off,
            def_signal=a_def,
            prior_year_rating=a_prior,
            recent_form_signal=a_form,
            week_number=week,
        )
        x = _feature_vector(home, away, is_neutral_site=is_neutral)
        z = float(np.array(padded, dtype=np.float64) @ x)
        p_home = 1.0 / (1.0 + math.exp(-z))
        outcome = bool(rng.random() < p_home)
        rows.append(
            GameTrainingRow(
                home_state=home,
                away_state=away,
                is_neutral_site=is_neutral,
                is_mercy=False,
                home_won=outcome,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Coefficient recovery on synthetic data
# ---------------------------------------------------------------------------


def test_fit_recovers_known_betas_on_synthetic_data():
    """Spec verification test #1: β̂ within tolerance of true β on 8k games.

    Tolerances are realistic 95%-CI envelopes for the sample size, not
    asymptotic. With ``neutral_fraction=0.5`` β₀ and β₂ are cleanly
    identified (in real data they're quasi-collinear because HFA is
    nearly always 1; the recovery test rebalances).
    """
    true_beta = [-0.10, 0.50, 0.30, 0.10, 0.20, 0.05]
    rows = _make_synthetic_games(8000, true_beta, seed=42)

    # Tiny L2 so we test recovery rather than the regularizer's pull.
    result = fit_sport("Synthetic", rows, l2_lambda_per_game=1e-5)

    assert result.converged is True
    assert result.n_train_games == 8000
    tolerances = {
        "beta_0": 0.10,
        "beta_1": 0.05,
        "beta_2": 0.10,
        "beta_3": 0.10,
        "beta_4": 0.10,
        "beta_5": 0.10,
    }
    # Padded true_beta for forward-compat with newly-added slots
    padded_true = list(true_beta) + [0.0] * (len(COEF_NAMES) - len(true_beta))
    default_tol = 0.10
    for i, name in enumerate(COEF_NAMES):
        recovered = result.coefficients[name]
        diff = abs(recovered - padded_true[i])
        tol = tolerances.get(name, default_tol)
        assert diff < tol, (
            f"{name}: |{recovered:.4f} - {padded_true[i]:.4f}| = {diff:.4f} "
            f"(tolerance {tol:.2f})"
        )


def test_fit_with_single_dominant_feature_recovers_cleanly():
    """Pure Δrating recovery — most-likely real-world fit on Phase-3 baseline.

    With only β₀ and β₁ nonzero in the data-generating model, the fit
    should nail β₁ within 0.05. β₀ has a wider band because the fitter
    has 6 free parameters trying to absorb 1 small intercept; checking
    the held-out predicted-prob accuracy is the stronger guarantee.
    """
    true_beta = [-0.05, 0.40, 0.0, 0.0, 0.0, 0.0]
    rows = _make_synthetic_games(8000, true_beta, seed=11)

    result = fit_sport("Football", rows, l2_lambda_per_game=1e-5)

    assert result.converged is True
    assert abs(result.coefficients["beta_1"] - true_beta[1]) < 0.05
    # The unused β slots should sit near zero
    for name in ("beta_3", "beta_4", "beta_5"):
        assert abs(result.coefficients[name]) < 0.10


def test_fitted_model_matches_data_generating_predictions_on_holdout():
    """Stronger functional test: fit on train, score on held-out games.

    Compare fitted-model P(home_wins) against the true data-generating
    P(home_wins) for each held-out game. Mean absolute error should be
    well under 5% — this is the prediction quality the spec actually
    cares about, more robust than per-coefficient recovery.
    """
    true_beta = [-0.10, 0.50, 0.30, 0.10, 0.20, 0.05]
    train = _make_synthetic_games(8000, true_beta, seed=42)
    holdout = _make_synthetic_games(2000, true_beta, seed=43)

    result = fit_sport("Synthetic", train, l2_lambda_per_game=1e-5)
    config = PredictionConfig(
        model_coefficients_by_sport={"Synthetic": result.coefficients}
    )

    padded_true = list(true_beta) + [0.0] * (len(COEF_NAMES) - len(true_beta))
    errors = []
    for row in holdout:
        p_fitted = predict_game_v3(
            row.home_state,
            row.away_state,
            "Synthetic",
            config,
            is_neutral_site=row.is_neutral_site,
        )
        x = _feature_vector(
            row.home_state, row.away_state, is_neutral_site=row.is_neutral_site
        )
        z_true = float(np.array(padded_true, dtype=np.float64) @ x)
        p_true = 1.0 / (1.0 + math.exp(-z_true))
        errors.append(abs(p_fitted - p_true))

    mae = sum(errors) / len(errors)
    assert mae < 0.02, f"Holdout MAE between fitted and true predictions = {mae:.4f}"


# ---------------------------------------------------------------------------
# Default-config regression (legacy fallback)
# ---------------------------------------------------------------------------


def test_predict_v3_matches_legacy_when_no_coefficients_fitted():
    """Spec verification test #2: empty coefficients → win_probability_v2."""
    config = PredictionConfig()
    home = GameState(rating=12.3, week_number=5)
    away = GameState(rating=8.7, week_number=5)

    pred = predict_game_v3(home, away, "Football", config, is_neutral_site=False)
    legacy = win_probability_v2(home.rating, away.rating, config, sport="Football")

    assert pred == pytest.approx(legacy, abs=1e-12)


def test_predict_v3_per_sport_fallback_isolated():
    """Fitting coefficients for one sport must not affect another sport's predictions."""
    config = PredictionConfig(
        model_coefficients_by_sport={
            "Football": {"beta_0": 0.5, "beta_1": 0.3, "beta_2": 0.2},
        }
    )
    home = GameState(rating=5.0)
    away = GameState(rating=0.0)

    football_pred = predict_game_v3(home, away, "Football", config)
    baseball_pred = predict_game_v3(home, away, "Baseball", config)
    baseball_legacy = win_probability_v2(home.rating, away.rating, config, sport="Baseball")

    assert football_pred != pytest.approx(baseball_pred, abs=1e-6)
    assert baseball_pred == pytest.approx(baseball_legacy, abs=1e-12)


# ---------------------------------------------------------------------------
# Bounded outputs / numerical guarantees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "h_rating,a_rating,h_margin,a_margin,prior",
    [
        (1000.0, -1000.0, 0.0, 0.0, None),       # very large Δrating (logit saturates to 1.0)
        (-1000.0, 1000.0, 0.0, 0.0, None),       # very large negative (saturates to 0.0)
        (0.0, 0.0, 0.0, 0.0, None),               # all-zero features
        (0.0, 0.0, 100.0, -100.0, None),          # large margin signal
        (0.0, 0.0, 0.0, 0.0, 50.0),               # prior-year rating present
    ],
)
def test_predict_v3_outputs_bounded(h_rating, a_rating, h_margin, a_margin, prior):
    """Spec verification test #3: predictions finite and in [0, 1] under pathological inputs.

    Saturation to exactly 0.0 or 1.0 IS acceptable at extreme logit
    values (float64 σ(z) hits the boundary by ±36). The contract is:
    finite + within [0,1], not strictly in (0,1).
    """
    config = PredictionConfig(
        model_coefficients_by_sport={
            "Football": {
                "beta_0": -0.1,
                "beta_1": 0.5,
                "beta_2": 0.4,
                "beta_3": 0.2,
                "beta_4": 0.1,
                "beta_5": 0.05,
            }
        }
    )
    home = GameState(rating=h_rating, margin_signal=h_margin, prior_year_rating=prior, week_number=1)
    away = GameState(rating=a_rating, margin_signal=a_margin, week_number=1)
    p = predict_game_v3(home, away, "Football", config)
    assert math.isfinite(p)
    assert 0.0 <= p <= 1.0


# ---------------------------------------------------------------------------
# HFA polarity
# ---------------------------------------------------------------------------


def test_hfa_shifts_home_advantage_symmetrically():
    """Spec verification test #4: HFA term raises home prob, swap → lower prob.

    Two evenly-matched teams with β₂>0: the team labeled "home" wins
    more often than 50%; swap the labels and the new home team wins
    more often than 50%. The two probabilities should NOT sum to 1
    (which would only hold if β₂=0).
    """
    config = PredictionConfig(
        model_coefficients_by_sport={
            "Football": {"beta_0": 0.0, "beta_1": 0.5, "beta_2": 0.4},
        }
    )
    team_a = GameState(rating=0.0)
    team_b = GameState(rating=0.0)

    p_a_home = predict_game_v3(team_a, team_b, "Football", config)
    p_b_home = predict_game_v3(team_b, team_a, "Football", config)

    assert p_a_home > 0.5
    assert p_b_home > 0.5
    assert p_a_home + p_b_home != pytest.approx(1.0, abs=1e-6)


def test_neutral_site_neutralizes_hfa():
    """At a neutral site, two equally-rated teams should be 50/50."""
    config = PredictionConfig(
        model_coefficients_by_sport={
            "Football": {"beta_0": 0.0, "beta_1": 0.5, "beta_2": 0.4},
        }
    )
    team_a = GameState(rating=0.0)
    team_b = GameState(rating=0.0)

    p = predict_game_v3(team_a, team_b, "Football", config, is_neutral_site=True)
    assert p == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# Cold-start handling
# ---------------------------------------------------------------------------


def test_predict_handles_missing_prior_year_rating():
    """Spec verification test #5: prior_year_rating=None → finite prediction."""
    config = PredictionConfig(
        model_coefficients_by_sport={
            "Football": {"beta_0": 0.0, "beta_1": 0.5, "beta_5": 0.3},
        }
    )
    home = GameState(rating=3.0, prior_year_rating=None, week_number=1)
    away = GameState(rating=0.0, prior_year_rating=None, week_number=1)
    p = predict_game_v3(home, away, "Football", config)
    assert math.isfinite(p)
    assert 0.0 < p < 1.0


def test_pyc_zero_when_prior_year_rating_missing():
    s = GameState(rating=0.0, prior_year_rating=None, week_number=1)
    assert _pyc(s) == 0.0


# ---------------------------------------------------------------------------
# Decay schedule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "week,expected",
    [
        (1, 1.0),
        (2, 2.0 / 3.0),
        (3, 1.0 / 3.0),
        (4, 0.0),
        (5, 0.0),
        (10, 0.0),
        (0, 1.0),          # defensive: pre-season clamps to week 1
        (-1, 1.0),
    ],
)
def test_decay_schedule(week, expected):
    assert _decay(week) == pytest.approx(expected, abs=1e-12)


# ---------------------------------------------------------------------------
# Recalibration
# ---------------------------------------------------------------------------


def test_isotonic_recalibration_applied_when_params_present():
    """A linear isotonic curve compresses raw probabilities toward 0.5."""
    config = PredictionConfig(
        model_coefficients_by_sport={
            "Football": {"beta_0": 0.0, "beta_1": 0.5},
        },
        recalibration_params_by_sport={
            "Football": {
                "method": "isotonic",
                "breakpoints": [0.0, 0.5, 1.0],
                "values":      [0.2, 0.5, 0.8],
            }
        },
    )
    home_strong = GameState(rating=10.0)
    away = GameState(rating=0.0)
    p_with = predict_game_v3(home_strong, away, "Football", config)
    # Same matchup with recalibration stripped
    config_no_recal = config.model_copy(update={"recalibration_params_by_sport": {}})
    p_without = predict_game_v3(home_strong, away, "Football", config_no_recal)

    assert p_with < p_without          # compressed toward 0.5 (down from extremes)
    assert 0.0 < p_with < 1.0


def test_malformed_recalibration_params_falls_back_to_raw():
    """Missing breakpoints → falls back; no exception."""
    config = PredictionConfig(
        model_coefficients_by_sport={
            "Football": {"beta_0": 0.0, "beta_1": 0.5},
        },
        recalibration_params_by_sport={"Football": {"method": "isotonic"}},
    )
    home = GameState(rating=5.0)
    away = GameState(rating=0.0)
    p = predict_game_v3(home, away, "Football", config)
    assert 0.0 < p < 1.0


# ---------------------------------------------------------------------------
# Mercy weighting
# ---------------------------------------------------------------------------


def test_mercy_weight_affects_loss_via_fit_sport():
    """Down-weighting mercy games to 0 should reproduce a no-mercy fit."""
    true_beta = [0.0, 0.5, 0.0, 0.0, 0.0, 0.0]
    rng = np.random.default_rng(99)
    rows: list[GameTrainingRow] = []
    for _ in range(2000):
        h = GameState(rating=rng.normal(0.0, 5.0))
        a = GameState(rating=rng.normal(0.0, 5.0))
        z = 0.5 * (h.rating - a.rating)
        p = 1.0 / (1.0 + math.exp(-z))
        rows.append(
            GameTrainingRow(
                home_state=h,
                away_state=a,
                is_neutral_site=False,
                is_mercy=False,
                home_won=bool(rng.random() < p),
            )
        )
    # Add 200 noisy "mercy" rows whose outcomes are random (50/50 noise)
    for _ in range(200):
        h = GameState(rating=rng.normal(0.0, 5.0))
        a = GameState(rating=rng.normal(0.0, 5.0))
        rows.append(
            GameTrainingRow(
                home_state=h,
                away_state=a,
                is_neutral_site=False,
                is_mercy=True,
                home_won=bool(rng.random() < 0.5),
            )
        )

    fit_full = fit_sport("S", rows, mercy_weight=1.0, l2_lambda_per_game=1e-5)
    fit_no_mercy = fit_sport("S", rows, mercy_weight=0.0, l2_lambda_per_game=1e-5)

    # Dropping mercy noise should pull β₁ closer to the true 0.5
    assert abs(fit_no_mercy.coefficients["beta_1"] - 0.5) <= abs(
        fit_full.coefficients["beta_1"] - 0.5
    )


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_fit_sport_raises_on_empty_train_games():
    with pytest.raises(ValueError, match="empty train_games"):
        fit_sport("Football", [])


def test_fit_sport_warm_start_length_mismatch():
    rows = _make_synthetic_games(50, [0.0, 0.5, 0.0, 0.0, 0.0, 0.0], seed=1)
    with pytest.raises(ValueError, match="initial_coefficients length"):
        fit_sport("Football", rows, initial_coefficients=[0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_fit_is_deterministic_across_calls():
    """Same data + same starting point ⇒ same fitted β."""
    rows = _make_synthetic_games(1500, [0.0, 0.4, 0.2, 0.0, 0.0, 0.0], seed=5)
    a = fit_sport("X", rows, l2_lambda_per_game=1e-4)
    b = fit_sport("X", rows, l2_lambda_per_game=1e-4)
    for name in COEF_NAMES:
        assert a.coefficients[name] == pytest.approx(b.coefficients[name], abs=1e-10)


# ---------------------------------------------------------------------------
# Nested CV for λ
# ---------------------------------------------------------------------------


def test_nested_cv_runs_end_to_end_and_records_scores():
    """Default fit_sport path: λ chosen by 5-fold CV inside train."""
    rows = _make_synthetic_games(2000, [0.0, 0.4, 0.2, 0.0, 0.0, 0.0], seed=33)
    result = fit_sport("X", rows, cv_n_folds=5)

    assert result.converged is True
    assert result.selected_lambda_per_game > 0.0
    # Each grid candidate received a held-out NLL score
    assert len(result.lambda_cv_scores) >= 5
    # The selected λ achieved the minimum held-out NLL
    best = min(result.lambda_cv_scores.values())
    assert result.lambda_cv_scores[result.selected_lambda_per_game] == pytest.approx(best, abs=1e-12)


def test_nested_cv_is_deterministic_under_cv_seed():
    """Same cv_seed + same data ⇒ identical λ + identical fold scores."""
    rows = _make_synthetic_games(1500, [0.0, 0.4, 0.0, 0.0, 0.0, 0.0], seed=77)
    a = fit_sport("X", rows, cv_n_folds=4, cv_seed=42)
    b = fit_sport("X", rows, cv_n_folds=4, cv_seed=42)
    assert a.selected_lambda_per_game == b.selected_lambda_per_game
    for lam in a.lambda_cv_scores:
        assert a.lambda_cv_scores[lam] == pytest.approx(b.lambda_cv_scores[lam], abs=1e-9)


def test_nested_cv_raises_when_data_too_small_for_folds():
    rows = _make_synthetic_games(3, [0.0, 0.4, 0.0, 0.0, 0.0, 0.0], seed=1)
    with pytest.raises(FitConvergenceError, match="nested CV requires"):
        fit_sport("X", rows, cv_n_folds=5)


def test_nested_cv_respects_custom_grid():
    rows = _make_synthetic_games(800, [0.0, 0.4, 0.0, 0.0, 0.0, 0.0], seed=11)
    result = fit_sport("X", rows, lambda_grid=[1e-3, 1e-2])
    assert set(result.lambda_cv_scores.keys()) == {1e-3, 1e-2}
    assert result.selected_lambda_per_game in {1e-3, 1e-2}


# ---------------------------------------------------------------------------
# strict=True / explicit-fallback gate
# ---------------------------------------------------------------------------


def test_predict_v3_strict_raises_when_no_coefficients():
    """Spec verification: strict=True must NOT silently fall back to legacy."""
    config = PredictionConfig()
    home = GameState(rating=5.0)
    away = GameState(rating=0.0)
    with pytest.raises(MissingCoefficientsError, match="no fitted coefficients"):
        predict_game_v3(home, away, "Football", config, strict=True)


def test_predict_v3_non_strict_still_falls_back():
    """Default strict=False preserves backward compatibility."""
    config = PredictionConfig()
    home = GameState(rating=5.0)
    away = GameState(rating=0.0)
    p = predict_game_v3(home, away, "Football", config)  # strict default
    legacy = win_probability_v2(home.rating, away.rating, config, sport="Football")
    assert p == pytest.approx(legacy, abs=1e-12)


def test_predict_v3_strict_passes_when_coefficients_present():
    config = PredictionConfig(
        model_coefficients_by_sport={"Football": {"beta_0": 0.0, "beta_1": 0.4}}
    )
    home = GameState(rating=5.0)
    away = GameState(rating=0.0)
    p = predict_game_v3(home, away, "Football", config, strict=True)
    assert 0.0 < p < 1.0


# ---------------------------------------------------------------------------
# Constrained fit (Phase 4a HFA ablation)
# ---------------------------------------------------------------------------


def test_fixed_indices_constrains_those_betas_to_zero():
    """fixed_indices=[2] must produce β₂=0.0 exactly in the result."""
    true_beta = [-0.05, 0.4, 0.3, 0.0, 0.0, 0.0]
    rows = _make_synthetic_games(2000, true_beta, seed=51)
    result = fit_sport("X", rows, fixed_indices=[2], l2_lambda_per_game=1e-4)

    assert result.coefficients["beta_2"] == 0.0
    # Other coefficients refit freely
    assert abs(result.coefficients["beta_1"] - true_beta[1]) < 0.10


def test_fixed_indices_multiple_betas():
    true_beta = [0.0, 0.4, 0.3, 0.1, 0.0, 0.0]
    rows = _make_synthetic_games(1500, true_beta, seed=52)
    result = fit_sport("X", rows, fixed_indices=[2, 4, 5], l2_lambda_per_game=1e-4)

    assert result.coefficients["beta_2"] == 0.0
    assert result.coefficients["beta_4"] == 0.0
    assert result.coefficients["beta_5"] == 0.0


def test_fixed_indices_out_of_range_raises():
    rows = _make_synthetic_games(100, [0.0, 0.4, 0.0, 0.0, 0.0, 0.0], seed=1)
    with pytest.raises(ValueError, match="fixed_indices contains"):
        fit_sport("X", rows, fixed_indices=[99], l2_lambda_per_game=1e-4)


def test_fixed_indices_changes_other_betas_vs_unconstrained():
    """Ablation must actually refit the remaining coefficients —
    not just zero out β₂ on the joint fit."""
    true_beta = [0.05, 0.4, 0.3, 0.0, 0.0, 0.0]
    rows = _make_synthetic_games(2000, true_beta, seed=53, neutral_fraction=0.0)
    # All games have HFA_indicator=1, so β₀ and β₂ are perfectly collinear.
    # Unconstrained fit splits the home-bias between β₀ and β₂.
    # β₂=0 constraint should push the entire bias into β₀.
    unconstrained = fit_sport("X", rows, l2_lambda_per_game=1e-4)
    ablated = fit_sport("X", rows, fixed_indices=[2], l2_lambda_per_game=1e-4)

    # β₀_ablated should absorb β₂'s contribution from the unconstrained fit
    expected_b0 = (
        unconstrained.coefficients["beta_0"] + unconstrained.coefficients["beta_2"]
    )
    assert abs(ablated.coefficients["beta_0"] - expected_b0) < 0.05
