from fastapi.testclient import TestClient
from app.main import app
from app.routers import ratings as ratings_router
from app.schemas.ratings import LatestWeekOut

client = TestClient(app)


def test_list_rankings_returns_200():
    response = client.get("/api/v1/ratings/rankings?sport=Football&season_year=2025&week_number=11")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_rankings_filter_by_division():
    response = client.get("/api/v1/ratings/rankings?sport=Football&season_year=2025&week_number=11&division=I")
    assert response.status_code == 200
    for entry in response.json():
        assert entry["division"] == "I"


def test_list_rankings_ordered_by_rank():
    response = client.get("/api/v1/ratings/rankings?sport=Football&season_year=2025&week_number=11&division=I")
    data = response.json()
    if len(data) >= 2:
        for i in range(len(data) - 1):
            assert data[i]["rank"] <= data[i + 1]["rank"]


def test_get_team_ratings_history():
    resp = client.get("/api/v1/ratings/rankings?sport=Football&season_year=2025&week_number=11&limit=1")
    data = resp.json()
    if len(data) == 0:
        return
    team_id = data[0]["team_id"]
    response = client.get(f"/api/v1/ratings/{team_id}?season_year=2025")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_team_ratings_not_found():
    response = client.get("/api/v1/ratings/999999?season_year=2025")
    assert response.status_code == 200
    assert response.json() == []


# --- /latest-week endpoint (Phase 3.4.2.fix) ---


def test_latest_week_schema_drift_guard():
    """CI-time guard against accidental field additions to LatestWeekOut.
    Mirrors the 3.3.4b model_coefficients guard pattern: the rankings
    endpoint must not start leaking new fields without a deliberate
    schema bump."""
    assert set(LatestWeekOut.model_fields.keys()) == {
        "sport",
        "season_year",
        "latest_week",
        "total_rankings",
    }, "Schema drift detected — unexpected fields in LatestWeekOut"


def test_latest_week_football_2025_returns_published_week():
    ratings_router._LATEST_WEEK_CACHE.clear()
    response = client.get(
        "/api/v1/ratings/latest-week?sport=Football&season_year=2025"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sport"] == "Football"
    assert body["season_year"] == 2025
    # On a seeded DB, Football should have a published week with rankings.
    # On an empty DB, we still get a 200 with latest_week=null — accept both.
    if body["latest_week"] is not None:
        assert body["latest_week"] >= 1
        assert body["total_rankings"] > 0
    else:
        assert body["total_rankings"] == 0


def test_latest_week_unknown_sport_returns_404():
    ratings_router._LATEST_WEEK_CACHE.clear()
    response = client.get(
        "/api/v1/ratings/latest-week?sport=Quidditch&season_year=2025"
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Sport not found"}


def test_latest_week_future_season_returns_null():
    """Valid sport + season outside seeded range → graceful 200 with null."""
    ratings_router._LATEST_WEEK_CACHE.clear()
    response = client.get(
        "/api/v1/ratings/latest-week?sport=Football&season_year=2099"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sport"] == "Football"
    assert body["season_year"] == 2099
    assert body["latest_week"] is None
    assert body["total_rankings"] == 0


def test_latest_week_cache_hit_returns_same_payload():
    ratings_router._LATEST_WEEK_CACHE.clear()
    r1 = client.get(
        "/api/v1/ratings/latest-week?sport=Football&season_year=2025"
    )
    r2 = client.get(
        "/api/v1/ratings/latest-week?sport=Football&season_year=2025"
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()
    # Cache key should be populated after the first call
    assert ("football", 2025, "engine") in ratings_router._LATEST_WEEK_CACHE
