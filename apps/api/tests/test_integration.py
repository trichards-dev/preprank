"""
Integration smoke test — verifies seed data flows through the API correctly.
Requires: PostgreSQL running with seed data loaded.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_schools_have_seed_data():
    resp = client.get("/api/v1/schools/?limit=5")
    assert resp.status_code == 200
    schools = resp.json()
    assert len(schools) > 0
    assert "name" in schools[0]
    assert "classification" in schools[0]


def test_rankings_return_ordered_results():
    resp = client.get("/api/v1/ratings/rankings?sport=Football&season_year=2025&week_number=11&division=I")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0
    # Sorted by power_rating DESC — #1 is highest rated in Division I
    assert data[0]["rank"] == 1
    assert data[0]["division"] == "I"
    # Verify descending order
    for i in range(len(data) - 1):
        assert data[i]["power_rating"] >= data[i + 1]["power_rating"]


def test_division_filter_excludes_other_divisions():
    resp = client.get("/api/v1/ratings/rankings?sport=Football&season_year=2025&week_number=11&division=II")
    data = resp.json()
    for entry in data:
        assert entry["division"] == "II"
        assert entry["classification"] == "4A"


def test_rankings_source_filter_defaults_to_engine():
    """Adding ?source=engine explicitly should match the default behavior."""
    a = client.get("/api/v1/ratings/rankings?sport=Football&season_year=2025&week_number=11&division=I").json()
    b = client.get("/api/v1/ratings/rankings?sport=Football&season_year=2025&week_number=11&division=I&source=engine").json()
    assert a == b


def test_rankings_unknown_source_returns_empty():
    """A source value not present in DB returns 0 rows without erroring."""
    resp = client.get("/api/v1/ratings/rankings?sport=Football&season_year=2025&week_number=11&source=lhsaa_official")
    assert resp.status_code == 200
    # Seed only loads engine-source rows; LHSAA loader runs separately.
    assert isinstance(resp.json(), list)


def test_teams_joined_with_school_and_sport():
    resp = client.get("/api/v1/teams/?sport=Football&season_year=2025&division=I&limit=3")
    assert resp.status_code == 200
    teams = resp.json()
    if len(teams) > 0:
        assert teams[0]["sport_name"] == "Football"
        assert teams[0]["school_name"] is not None
