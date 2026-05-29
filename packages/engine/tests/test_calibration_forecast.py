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
    """A small reliability table with all bins well above TAIL_MIN_N."""
    return {
        "schema_version": 1,
        "calibration_run_id": "test-fixture",
        "sports": {
            "TestSport": {
                "isotonic_slope": 0.98,
                "isotonic_slope_in_band": True,
                "deciles": [
                    {"bin_lower": i/10, "bin_upper": (i+1)/10,
                     "n_games": 200, "mean_predicted": (i + 0.5)/10,
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
    """CI lower bound clipped at 0."""
    table = _sample_table_well_populated()
    # gap 0.03 → half_width 3pp; p_pct=1 → ci_low = max(0, 1-3) = 0
    result = compute_forecast(0.01, "TestSport", table)
    assert result.home_win_probability_ci_low == 0
    assert result.home_win_probability_ci_high == 4


def test_compute_forecast_ci_clips_to_100_upper_bound():
    """CI upper bound clipped at 100."""
    table = _sample_table_well_populated()
    # gap 0.03 → half_width 3pp; p_pct=99 → ci_high = min(100, 99+3) = 100
    result = compute_forecast(0.99, "TestSport", table)
    assert result.home_win_probability_ci_high == 100
    assert result.home_win_probability_ci_low == 96


def test_compute_forecast_tier_label_set():
    """Tier label is one of the four canonical strings."""
    table = _sample_table_well_populated()
    result = compute_forecast(0.65, "TestSport", table)
    # gap 0.03 → half_width 3 → Confident pick
    assert result.confidence_tier == "confident_pick"
    assert result.confidence_tier_label == "Confident pick"


def test_compute_forecast_unknown_sport_returns_zero_ci():
    """Sport not in table → gap=0, CI = [p_pct, p_pct]."""
    table = _sample_table_well_populated()
    result = compute_forecast(0.5, "NotASport", table)
    assert result.home_win_probability == 50
    assert result.home_win_probability_ci_low == 50
    assert result.home_win_probability_ci_high == 50


# ---------------------------------------------------------------------------
# Underpowered tail-bin fallback
# ---------------------------------------------------------------------------
def test_underpowered_tail_uses_adjacent_bin_when_slope_in_band():
    """Football D1 n=32 should fall back to D2's gap when slope is in band."""
    table = {
        "sports": {
            "Football": {
                "isotonic_slope_in_band": True,
                "deciles": [
                    # D1: n=32 (below TAIL_MIN_N=139), gap=0.08
                    {"bin_lower": 0.0, "bin_upper": 0.1,
                     "n_games": 32, "mean_predicted": 0.05,
                     "mean_observed": 0.13, "gap": 0.08},
                    # D2: n=197 (well above floor), gap=0.01
                    {"bin_lower": 0.1, "bin_upper": 0.2,
                     "n_games": 197, "mean_predicted": 0.15,
                     "mean_observed": 0.16, "gap": 0.01},
                ] + [
                    {"bin_lower": i/10, "bin_upper": (i+1)/10,
                     "n_games": 100, "mean_predicted": (i + 0.5)/10,
                     "mean_observed": (i + 0.5)/10, "gap": 0.02}
                    for i in range(2, 10)
                ],
                "model_coefficients": {},
            }
        }
    }
    # p=0.05 falls in D1 (n=32, below floor). Fallback to D2 (n=197 > floor).
    result = compute_forecast(0.05, "Football", table)
    assert result.underpowered_tail_fallback_used is True
    # half-width should be from D2 (0.01) → 1pp, NOT from D1 (0.08) → 8pp
    assert result.home_win_probability_ci_high - result.home_win_probability_ci_low <= 2


def test_well_populated_decile_does_not_use_fallback():
    """When bin is well-populated, no fallback."""
    table = _sample_table_well_populated()
    result = compute_forecast(0.5, "TestSport", table)
    assert result.underpowered_tail_fallback_used is False


def test_underpowered_does_not_use_fallback_when_slope_out_of_band():
    """If the sport's overall calibration is bad, don't paper over with adjacent bins.

    Surfacing the wider CI honestly is more useful than swapping in
    a healthier bin's gap.
    """
    table = {
        "sports": {
            "BadSport": {
                "isotonic_slope_in_band": False,  # out of band
                "deciles": [
                    {"bin_lower": 0.0, "bin_upper": 0.1,
                     "n_games": 30, "mean_predicted": 0.05,
                     "mean_observed": 0.20, "gap": 0.15},
                ] + [
                    {"bin_lower": i/10, "bin_upper": (i+1)/10,
                     "n_games": 200, "mean_predicted": (i + 0.5)/10,
                     "mean_observed": (i + 0.5)/10, "gap": 0.02}
                    for i in range(1, 10)
                ],
                "model_coefficients": {},
            }
        }
    }
    result = compute_forecast(0.05, "BadSport", table)
    assert result.underpowered_tail_fallback_used is False
    # The raw 15pp gap surfaces honestly. p=5%, half-width=15pp,
    # so CI is [max(0, 5-15), min(100, 5+15)] = [0, 20] — width 20pp,
    # reflecting the full 15pp half-width on the upper side (lower
    # side clipped to 0 by floor). Compare to well-populated sports
    # where width would be ~6pp (3pp half-width).
    assert result.home_win_probability_ci_high - result.home_win_probability_ci_low >= 15
    # And the tier label reflects the wide gap (Toss-up at hw=15)
    assert result.confidence_tier in ("toss_up", "long_shot")


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
        "underpowered_tail_fallback_used",
    ):
        assert required in fields, f"missing field: {required}"
