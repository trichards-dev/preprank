"""Tests for the calibration forecast computation module.

Per `confidence_disclosure_ux_options_2026-05-29.md` (memory) Specs 1, 2, 5
and `forecast_api_design_2026-05-29.md` Q4 revision.

Coverage:
  - Tier brackets verbatim from Spec 2 (boundary tests)
  - CI clip to [0, 100]
  - Predicted-decile indexing (right edge inclusive on D9 only)
  - Underpowered tail-bin fallback (Football D1 / BBB D10 specifically)
  - Source-caveat sport-isolation (only Baseball at v1.0)
  - Premium-detail block shape
  - ForecastResult dataclass shape
"""
from __future__ import annotations

from dataclasses import is_dataclass

import pytest

from engine.calibration.forecast import (
    TAIL_MIN_N,
    TIER_CONFIDENT_PICK_MAX_HW,
    TIER_LEAN_MAX_HW,
    TIER_TOSS_UP_MAX_HW,
    ForecastResult,
    _predicted_decile,
    build_premium_detail,
    compute_forecast,
    confidence_tier,
)
from engine.calibration.source_caveats import (
    SOURCE_CAVEATS,
    SourceCaveat,
    get_source_caveat,
)


# ---------------------------------------------------------------------------
# Tier bracket constants — Spec 2 verbatim
# ---------------------------------------------------------------------------
def test_tier_brackets_match_spec_2_verbatim():
    """Bracket constants exactly per the locked UX spec."""
    assert TIER_CONFIDENT_PICK_MAX_HW == 5
    assert TIER_LEAN_MAX_HW == 10
    assert TIER_TOSS_UP_MAX_HW == 15


def test_tail_min_n_matches_phase6_floor():
    """TAIL_MIN_N must match runner_v2.PHASE6_TAIL_MIN_N = 139."""
    from engine.validator.runner_v2 import PHASE6_TAIL_MIN_N
    assert TAIL_MIN_N == PHASE6_TAIL_MIN_N
    assert TAIL_MIN_N == 139


# ---------------------------------------------------------------------------
# confidence_tier boundary tests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("half_width,expected_code,expected_label", [
    (0,  "confident_pick", "Confident pick"),
    (3,  "confident_pick", "Confident pick"),
    (5,  "confident_pick", "Confident pick"),  # boundary
    (6,  "lean",           "Lean"),            # boundary
    (8,  "lean",           "Lean"),
    (10, "lean",           "Lean"),            # boundary
    (11, "toss_up",        "Toss-up"),         # boundary
    (13, "toss_up",        "Toss-up"),
    (15, "toss_up",        "Toss-up"),         # boundary
    (16, "long_shot",      "Long shot"),       # boundary
    (30, "long_shot",      "Long shot"),
    (99, "long_shot",      "Long shot"),
])
def test_confidence_tier_boundaries(half_width, expected_code, expected_label):
    code, label = confidence_tier(half_width)
    assert code == expected_code
    assert label == expected_label


# ---------------------------------------------------------------------------
# _predicted_decile
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("p,expected", [
    (0.00, 0),   # left edge of D1
    (0.05, 0),
    (0.099, 0),
    (0.10, 1),   # left edge of D2
    (0.50, 5),
    (0.89, 8),
    (0.90, 9),   # left edge of D10
    (0.95, 9),
    (1.00, 9),   # right edge inclusive on D10
])
def test_predicted_decile_mapping(p, expected):
    assert _predicted_decile(p) == expected


def test_predicted_decile_handles_out_of_range():
    """Clamp behavior on out-of-range p values."""
    assert _predicted_decile(-0.1) == 0
    assert _predicted_decile(1.5) == 9


# ---------------------------------------------------------------------------
# compute_forecast — full path
# ---------------------------------------------------------------------------
def _sample_table_well_populated() -> dict:
    """A small reliability table with all bins well-populated.

    Under Option D (binomial sampling CI): n=1000 per bin produces
    CI half-widths of ~1-3pp across most predictions, keeping
    most test predictions in the "Confident pick" tier for clean
    expectations.
    """
    return {
        "schema_version": 1,
        "calibration_run_id": "test-fixture",
        "sports": {
            "TestSport": {
                "isotonic_slope": 0.98,
                "isotonic_slope_in_band": True,
                "deciles": [
                    {"bin_lower": i/10, "bin_upper": (i+1)/10,
                     "n_games": 1000, "mean_predicted": (i + 0.5)/10,
                     "mean_observed": (i + 0.5)/10, "gap": 0.03}
                    for i in range(10)
                ],
                "model_coefficients": {"beta_1": 0.1, "beta_6": 0.05},
                "tail_miscalibration_after_isotonic": False,
            }
        }
    }


def test_compute_forecast_returns_integer_percent_fields():
    """All probability fields are integer percentages."""
    table = _sample_table_well_populated()
    result = compute_forecast(0.65, "TestSport", table)
    assert isinstance(result.home_win_probability, int)
    assert isinstance(result.home_win_probability_ci_low, int)
    assert isinstance(result.home_win_probability_ci_high, int)
    assert result.home_win_probability == 65


def test_compute_forecast_ci_clips_to_zero_lower_bound():
    """CI lower bound clipped at 0 when prediction near 0% + nonzero CI."""
    table = _sample_table_well_populated()
    # D1: n=1000, p_obs=0.05 → hw = 1.96 × √(0.05·0.95/1000) ≈ 1.4pp → 1pp
    # p_pct=1 → ci_low = max(0, 1-1) = 0
    result = compute_forecast(0.01, "TestSport", table)
    assert result.home_win_probability_ci_low == 0
    # Upper bound should not exceed p_pct + half_width
    assert result.home_win_probability_ci_high <= 5


def test_compute_forecast_ci_clips_to_100_upper_bound():
    """CI upper bound clipped at 100 when prediction near 100% + nonzero CI."""
    table = _sample_table_well_populated()
    # D10: n=1000, p_obs=0.95 → hw ≈ 1.4pp → 1pp
    result = compute_forecast(0.99, "TestSport", table)
    assert result.home_win_probability_ci_high == 100
    assert result.home_win_probability_ci_low >= 95


def test_compute_forecast_tier_label_set():
    """Confident pick fires for well-populated mid bins."""
    table = _sample_table_well_populated()
    # D6: n=1000, p_obs=0.65 → hw = 1.96 × √(0.65·0.35/1000) ≈ 3pp
    result = compute_forecast(0.65, "TestSport", table)
    assert result.confidence_tier == "confident_pick"
    assert result.confidence_tier_label == "Confident pick"


def test_compute_forecast_unknown_sport_returns_zero_ci():
    """Sport not in table → n=0, CI half_width=0, CI = [p_pct, p_pct]."""
    table = _sample_table_well_populated()
    result = compute_forecast(0.5, "NotASport", table)
    assert result.home_win_probability == 50
    assert result.home_win_probability_ci_low == 50
    assert result.home_win_probability_ci_high == 50


# ---------------------------------------------------------------------------
# Option D — binomial sampling CI semantics
# ---------------------------------------------------------------------------
def test_binomial_ci_widens_when_bin_n_is_small():
    """A bin with n=32 should produce a wider CI than n=1000."""
    # Use Football D1 from real Phase 6 data: n=32, p_obs=0.094
    table_small_n = {
        "sports": {
            "S": {
                "isotonic_slope_in_band": True,
                "deciles": [
                    {"bin_lower": 0.0, "bin_upper": 0.1,
                     "n_games": 32, "mean_predicted": 0.05,
                     "mean_observed": 0.094, "gap": 0.044},
                ] + [
                    {"bin_lower": i/10, "bin_upper": (i+1)/10,
                     "n_games": 1000, "mean_predicted": (i + 0.5)/10,
                     "mean_observed": (i + 0.5)/10, "gap": 0.01}
                    for i in range(1, 10)
                ],
                "model_coefficients": {},
            }
        }
    }
    small_n_result = compute_forecast(0.03, "S", table_small_n)
    large_n_result = compute_forecast(0.55, "S", table_small_n)

    small_n_width = small_n_result.home_win_probability_ci_high - small_n_result.home_win_probability_ci_low
    large_n_width = large_n_result.home_win_probability_ci_high - large_n_result.home_win_probability_ci_low

    # n=32 + p_obs=0.094 → hw ≈ 10pp → width ≥ 10pp (with possible clip to 0)
    # n=1000 + p_obs=0.55 → hw ≈ 3pp → width ≤ 6pp
    assert small_n_width > large_n_width


def test_binomial_ci_at_known_values_football_d1():
    """Football D1 (n=32, p_obs=0.094) should produce ~10pp half-width.

    Sanity check against the preview math in the Option D approval.
    """
    table = {
        "sports": {
            "Football": {
                "isotonic_slope_in_band": True,
                "deciles": [
                    {"bin_lower": 0.0, "bin_upper": 0.1,
                     "n_games": 32, "mean_predicted": 0.05,
                     "mean_observed": 0.094, "gap": 0.044},
                ] + [
                    {"bin_lower": i/10, "bin_upper": (i+1)/10,
                     "n_games": 500, "mean_predicted": (i + 0.5)/10,
                     "mean_observed": (i + 0.5)/10, "gap": 0.01}
                    for i in range(1, 10)
                ],
                "model_coefficients": {},
            }
        }
    }
    result = compute_forecast(0.03, "Football", table)
    # Expected: hw = round(100 * 1.96 * sqrt(0.094 * 0.906 / 32)) = round(10.1) = 10pp
    # p_pct=3 → ci = [max(0, 3-10), min(100, 3+10)] = [0, 13]
    # Width = 13pp
    width = result.home_win_probability_ci_high - result.home_win_probability_ci_low
    assert 9 <= width <= 14  # tolerance for round-trip
    # Tier should be Lean (6-10pp half-width)
    assert result.confidence_tier == "lean"
    # bin_underpowered flag should fire (n=32 < 139)
    assert result.bin_underpowered is True
    assert result.bin_n_games == 32


def test_binomial_ci_at_known_values_volleyball_d9():
    """Volleyball D9 (n=430, p_obs=0.84) should produce ~3pp → Confident pick."""
    table = {
        "sports": {
            "Volleyball": {
                "isotonic_slope_in_band": True,
                "deciles": [
                    {"bin_lower": i/10, "bin_upper": (i+1)/10,
                     "n_games": 100, "mean_predicted": (i + 0.5)/10,
                     "mean_observed": (i + 0.5)/10, "gap": 0.01}
                    for i in range(8)
                ] + [
                    # D9: well-populated, high p_obs
                    {"bin_lower": 0.8, "bin_upper": 0.9,
                     "n_games": 430, "mean_predicted": 0.85,
                     "mean_observed": 0.84, "gap": 0.01},
                    {"bin_lower": 0.9, "bin_upper": 1.0,
                     "n_games": 200, "mean_predicted": 0.95,
                     "mean_observed": 0.95, "gap": 0.01},
                ],
                "model_coefficients": {},
            }
        }
    }
    result = compute_forecast(0.85, "Volleyball", table)
    # hw = 1.96 × √(0.84·0.16/430) ≈ 3.5pp → 3pp or 4pp
    assert result.confidence_tier == "confident_pick"
    assert result.bin_underpowered is False
    assert result.bin_n_games == 430


def test_compute_forecast_underpowered_bin_flag_fires_when_n_below_floor():
    """bin_underpowered = True when n < TAIL_MIN_N (139)."""
    table = {
        "sports": {
            "S": {
                "isotonic_slope_in_band": True,
                "deciles": [
                    {"bin_lower": i/10, "bin_upper": (i+1)/10,
                     "n_games": 50,  # below floor
                     "mean_predicted": (i + 0.5)/10,
                     "mean_observed": (i + 0.5)/10, "gap": 0.05}
                    for i in range(10)
                ],
                "model_coefficients": {},
            }
        }
    }
    result = compute_forecast(0.5, "S", table)
    assert result.bin_underpowered is True
    assert result.bin_n_games == 50


def test_compute_forecast_bin_n_reported_in_result():
    """ForecastResult exposes bin_n_games for downstream use."""
    table = _sample_table_well_populated()
    result = compute_forecast(0.5, "TestSport", table)
    assert result.bin_n_games == 1000
    assert result.bin_underpowered is False


# ---------------------------------------------------------------------------
# Source-data caveat sport-isolation (Spec 1a)
# ---------------------------------------------------------------------------
def test_baseball_returns_source_caveat():
    cv = get_source_caveat("Baseball")
    assert cv is not None
    assert cv.code == "baseball_winner_first_recording"
    assert "LHSAA source-page recording conventions" in cv.prose


@pytest.mark.parametrize("sport", [
    "Football", "Volleyball", "Boys Basketball", "Girls Basketball",
    "Softball", "Boys Soccer", "Girls Soccer",
])
def test_non_baseball_sports_return_no_caveat(sport):
    """Drift test: only Baseball has a v1.0 source caveat."""
    assert get_source_caveat(sport) is None


def test_source_caveats_keyed_only_by_baseball_at_v10():
    """Drift test: the SOURCE_CAVEATS dict has exactly one entry at v1.0."""
    assert set(SOURCE_CAVEATS.keys()) == {"Baseball"}


def test_source_caveat_dataclass_immutable():
    """SourceCaveat is frozen — can't be mutated by callers."""
    cv = SOURCE_CAVEATS["Baseball"]
    assert isinstance(cv, SourceCaveat)
    with pytest.raises((AttributeError, TypeError)):
        cv.code = "tampered"  # type: ignore


# ---------------------------------------------------------------------------
# Premium-detail block shape (Spec 5)
# ---------------------------------------------------------------------------
def test_premium_detail_contains_required_fields():
    """All Spec 5 fields populated in the premium_detail block."""
    table = _sample_table_well_populated()
    detail = build_premium_detail(
        sport_name="TestSport",
        home_team_id=101, away_team_id=202,
        predicted_decile=5,
        reliability_table=table,
        home_typical_decile=6,
        away_typical_decile=4,
    )
    assert "model_coefficients" in detail
    assert "home_typical_decile" in detail
    assert "away_typical_decile" in detail
    assert "predicted_decile" in detail
    assert "predicted_decile_reliability" in detail
    assert "methodology_deep_link" in detail
    assert detail["predicted_decile"] == 5
    assert detail["home_typical_decile"] == 6
    assert detail["away_typical_decile"] == 4


def test_premium_detail_methodology_link_format():
    """Methodology deep-link uses sport-slug + decile pattern."""
    table = _sample_table_well_populated()
    detail = build_premium_detail(
        sport_name="Football",
        home_team_id=1, away_team_id=2,
        predicted_decile=5,  # D6 (1-indexed in the URL)
        reliability_table=table,
    )
    assert detail["methodology_deep_link"] == "/methodology#football-d6"


def test_premium_detail_handles_multi_word_sport_in_link():
    """Sport names with spaces get hyphenated for the URL anchor."""
    table = _sample_table_well_populated()
    detail = build_premium_detail(
        sport_name="Boys Basketball",
        home_team_id=1, away_team_id=2,
        predicted_decile=0,
        reliability_table=table,
    )
    assert detail["methodology_deep_link"] == "/methodology#boys-basketball-d1"


def test_premium_detail_missing_decile_returns_none_for_reliability():
    """Out-of-range decile returns None for the reliability sub-block."""
    table = _sample_table_well_populated()
    detail = build_premium_detail(
        sport_name="TestSport",
        home_team_id=1, away_team_id=2,
        predicted_decile=99,  # out of range
        reliability_table=table,
    )
    assert detail["predicted_decile_reliability"] is None


# ---------------------------------------------------------------------------
# ForecastResult dataclass shape
# ---------------------------------------------------------------------------
def test_forecast_result_is_dataclass_with_required_fields():
    assert is_dataclass(ForecastResult)
    fields = ForecastResult.__dataclass_fields__
    for required in (
        "home_win_probability",
        "home_win_probability_ci_low",
        "home_win_probability_ci_high",
        "confidence_tier",
        "confidence_tier_label",
        "predicted_decile",
        "bin_n_games",
        "bin_underpowered",
    ):
        assert required in fields, f"missing field: {required}"
