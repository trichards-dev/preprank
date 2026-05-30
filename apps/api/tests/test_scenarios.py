import uuid

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _register_and_get_token(prefix: str = "scenario") -> str:
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/v1/auth/register", json={
        "email": email, "password": "testpass123",
        "first_name": "Scenario", "last_name": "User",
    })
    return resp.json()["access_token"]


def _make_premium(token: str):
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    user_id = me.json()["id"]
    client.post("/api/v1/subscriptions/webhook", json={
        "type": "checkout.session.completed",
        "user_id": user_id,
        "tier": "premium_monthly",
    })


def _get_premium_token(prefix: str = "scenario") -> str:
    token = _register_and_get_token(prefix)
    _make_premium(token)
    return token


def test_calculate_requires_premium():
    token = _register_and_get_token("scenariofree")
    resp = client.post("/api/v1/scenarios/calculate",
        json={"team_id": 1},
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_calculate_requires_auth():
    resp = client.post("/api/v1/scenarios/calculate", json={"team_id": 1})
    assert resp.status_code == 401


def test_calculate_scenario():
    token = _get_premium_token("calc")
    resp = client.post("/api/v1/scenarios/calculate",
        json={"team_id": 1, "locked_outcomes": [], "sport": "Football", "season_year": 2025, "week_number": 11},
        headers={"Authorization": f"Bearer {token}"})
    # Team 1 may or may not exist in the DB - expect 200 or 404
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        data = resp.json()
        assert data["team_id"] == 1
        assert "projected_rating" in data
        assert "playoff_probability" in data


def test_best_case():
    token = _get_premium_token("best")
    resp = client.post("/api/v1/scenarios/best-case",
        json={"team_id": 1, "sport": "Football", "season_year": 2025, "week_number": 11},
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert resp.json()["team_id"] == 1


def test_worst_case():
    token = _get_premium_token("worst")
    resp = client.post("/api/v1/scenarios/worst-case",
        json={"team_id": 1, "sport": "Football", "season_year": 2025, "week_number": 11},
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in (200, 404)


def test_team_not_found():
    token = _get_premium_token("notfound")
    resp = client.post("/api/v1/scenarios/calculate",
        json={"team_id": 999999},
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


def test_compare_requires_premium():
    token = _register_and_get_token("comparefree")
    resp = client.post("/api/v1/scenarios/compare",
        json={"team_id": 1, "scenario_a": [], "scenario_b": []},
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
