"""Integration + drift tests for /api/v1/games/{game_id}/forecast.

Per `forecast_api_design_2026-05-29.md` (memory): drift tests on
response shape, source-data caveat sport-isolation, tier brackets
matching engine.calibration.forecast verbatim.

Most tests use TestClient against the seeded DB (test_integration.py
pattern). The drift tests are pure-Python — no DB required.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.forecast import (
    ConfidenceTier,
    ForecastBlock,
    ForecastUnavailableReason,
    GameForecastResponse,
    PremiumDetail,
    SourceDataCaveat,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Drift tests — pure Python, no DB required
# ---------------------------------------------------------------------------
def test_drift_tier_brackets_match_engine_constants():
    """ConfidenceTier literal values must match engine.calibration.forecast
    enum codes verbatim.
    """
    from engine.calibration.forecast import confidence_tier
    # The Literal type's args carry the allowed values
    expected_codes = set(ConfidenceTier.__args__)  # type: ignore[attr-defined]
    actual_codes = {confidence_tier(hw)[0] for hw in (0, 6, 11, 16)}
    assert expected_codes == actual_codes


def test_drift_forecast_unavailable_reason_enum_values():
    """The Pydantic Literal enum matches the design doc reasons exactly."""
    expected = {
        "INSUFFICIENT_PRIOR_DATA",
        "RECENTLY_SCHEDULED",
        "SPORT_CALIBRATION_PENDING",
        "COLD_START_TEAM",
        "OTHER",
    }
    actual = set(ForecastUnavailableReason.__args__)  # type: ignore[attr-defined]
    assert actual == expected


def test_drift_source_data_caveat_sport_isolation():
    """Only Baseball returns a non-None caveat at v1.0."""
    from engine.calibration.source_caveats import get_source_caveat
    assert get_source_caveat("Baseball") is not None
    for sport in ("Football", "Volleyball", "Boys Basketball",
                  "Girls Basketball", "Softball", "Boys Soccer", "Girls Soccer"):
        assert get_source_caveat(sport) is None, f"{sport} unexpectedly has a caveat"


def test_drift_response_shape_has_required_top_level_fields():
    """Response schema carries all design-doc fields."""
    fields = GameForecastResponse.model_fields
    for required in (
        "game_id", "sport", "season_year", "week_number", "status",
        "home_team", "away_team", "forecast", "forecast_unavailable_reason",
        "source_data_caveat", "premium_detail", "calibration_run_id",
        "computed_at",
    ):
        assert required in fields, f"missing field: {required}"


def test_drift_forecast_block_has_required_fields():
    fields = ForecastBlock.model_fields
    for required in (
        "home_win_probability", "home_win_probability_ci_low",
        "home_win_probability_ci_high", "confidence_tier",
        "confidence_tier_label",
    ):
        assert required in fields


def test_drift_premium_detail_has_required_fields():
    fields = PremiumDetail.model_fields
    for required in (
        "factor_contributions", "home_typical_decile", "away_typical_decile",
        "predicted_decile", "predicted_decile_reliability",
        "methodology_deep_link",
    ):
        assert required in fields
    # Phase 3.3.4b: raw model_coefficients MUST NOT leak through schema
    assert "model_coefficients" not in fields


# ---------------------------------------------------------------------------
# Integration tests — require seeded DB
# ---------------------------------------------------------------------------
def test_forecast_404_on_missing_game():
    resp = client.get("/api/v1/games/99999999/forecast")
    assert resp.status_code == 404


def test_forecast_200_returns_valid_shape_or_unavailable():
    """For an existing game in the seeded DB, endpoint returns 200 with
    either a valid forecast or forecast_unavailable_reason populated."""
    # Use rankings to discover a known team/game; if no games seeded
    # for Football, the test is skipped gracefully.
    games_resp = client.get("/api/v1/games/?season_year=2025&sport=Football&limit=1")
    if games_resp.status_code != 200:
        pytest.skip("Games endpoint not accessible")
    games = games_resp.json()
    if not games:
        pytest.skip("No 2025 Football games in seeded DB")

    game_id = games[0]["id"]
    resp = client.get(f"/api/v1/games/{game_id}/forecast")
    assert resp.status_code == 200
    body = resp.json()
    # Shape contract
    assert body["game_id"] == game_id
    assert "sport" in body
    assert "home_team" in body and "id" in body["home_team"] and "name" in body["home_team"]
    assert "away_team" in body
    assert "calibration_run_id" in body
    assert "computed_at" in body
    # forecast block either populated or unavailable_reason set
    if body["forecast"] is None:
        assert body["forecast_unavailable_reason"] is not None
    else:
        f = body["forecast"]
        assert 0 <= f["home_win_probability"] <= 100
        assert 0 <= f["home_win_probability_ci_low"] <= f["home_win_probability"] <= f["home_win_probability_ci_high"] <= 100
        assert f["confidence_tier"] in ("confident_pick", "lean", "toss_up", "long_shot")


def test_forecast_anonymous_has_no_premium_detail():
    """Anonymous request returns premium_detail=null."""
    games_resp = client.get("/api/v1/games/?season_year=2025&sport=Football&limit=1")
    if games_resp.status_code != 200 or not games_resp.json():
        pytest.skip("No games to test")
    game_id = games_resp.json()[0]["id"]
    resp = client.get(f"/api/v1/games/{game_id}/forecast")
    assert resp.status_code == 200
    assert resp.json()["premium_detail"] is None


def test_forecast_baseball_carries_source_data_caveat():
    """Baseball game returns the source-data caveat block."""
    games_resp = client.get("/api/v1/games/?season_year=2025&sport=Baseball&limit=1")
    if games_resp.status_code != 200 or not games_resp.json():
        pytest.skip("No Baseball games in seeded DB")
    game_id = games_resp.json()[0]["id"]
    resp = client.get(f"/api/v1/games/{game_id}/forecast")
    assert resp.status_code == 200
    body = resp.json()
    caveat = body["source_data_caveat"]
    assert caveat is not None
    assert caveat["code"] == "baseball_winner_first_recording"
    assert "LHSAA source-page recording conventions" in caveat["prose"]


@pytest.mark.parametrize("sport", ["Football", "Volleyball", "Boys Basketball",
                                    "Girls Basketball", "Softball",
                                    "Boys Soccer", "Girls Soccer"])
def test_forecast_non_baseball_sports_have_no_caveat(sport):
    """Non-Baseball sports return source_data_caveat=null."""
    games_resp = client.get(f"/api/v1/games/?season_year=2025&sport={sport}&limit=1")
    if games_resp.status_code != 200 or not games_resp.json():
        pytest.skip(f"No {sport} games in seeded DB")
    game_id = games_resp.json()[0]["id"]
    resp = client.get(f"/api/v1/games/{game_id}/forecast")
    assert resp.status_code == 200
    assert resp.json()["source_data_caveat"] is None


def test_forecast_cache_hit_returns_same_payload():
    """Second request to same game_id should return cached payload."""
    games_resp = client.get("/api/v1/games/?season_year=2025&sport=Football&limit=1")
    if games_resp.status_code != 200 or not games_resp.json():
        pytest.skip("No games to test")
    game_id = games_resp.json()[0]["id"]
    r1 = client.get(f"/api/v1/games/{game_id}/forecast")
    r2 = client.get(f"/api/v1/games/{game_id}/forecast")
    assert r1.status_code == 200 and r2.status_code == 200
    # computed_at should be identical (cache hit) or very close
    b1, b2 = r1.json(), r2.json()
    assert b1["forecast"] == b2["forecast"]
    assert b1["source_data_caveat"] == b2["source_data_caveat"]
