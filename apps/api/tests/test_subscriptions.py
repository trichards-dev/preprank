import uuid

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _register_and_get_token(prefix: str = "sub") -> str:
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/v1/auth/register", json={
        "email": email, "password": "testpass123",
        "first_name": "Test", "last_name": "User",
    })
    return resp.json()["access_token"]


def _make_premium(token: str):
    """Use mock webhook to upgrade user."""
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    user_id = me.json()["id"]
    client.post("/api/v1/subscriptions/webhook", json={
        "type": "checkout.session.completed",
        "user_id": user_id,
        "tier": "premium_monthly",
    })


def test_checkout_requires_auth():
    resp = client.post("/api/v1/subscriptions/checkout", json={"tier": "premium_monthly"})
    assert resp.status_code == 401


def test_checkout_returns_session():
    token = _register_and_get_token("checkout")
    resp = client.post("/api/v1/subscriptions/checkout",
        json={"tier": "premium_monthly"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["price"] == 4.99


def test_webhook_upgrades_user():
    token = _register_and_get_token("webhook")
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    user_id = me.json()["id"]

    resp = client.post("/api/v1/subscriptions/webhook", json={
        "type": "checkout.session.completed",
        "user_id": user_id,
        "tier": "annual",
    })
    assert resp.status_code == 200

    status = client.get("/api/v1/subscriptions/status",
        headers={"Authorization": f"Bearer {token}"})
    assert status.json()["tier"] == "annual"
    assert status.json()["is_active"] is True


def test_cancel_subscription():
    token = _register_and_get_token("cancel")
    _make_premium(token)

    resp = client.post("/api/v1/subscriptions/cancel",
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["tier"] == "free"


def test_premium_gating_blocks_free_user():
    token = _register_and_get_token("free")
    # Game impact requires premium
    resp = client.get("/api/v1/simulations/game/1/impact",
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_premium_gating_allows_premium_user():
    token = _register_and_get_token("premium")
    _make_premium(token)
    # Game impact should not return 403 (may 404 if no data, that's fine)
    resp = client.get("/api/v1/simulations/game/1/impact",
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code != 403


def test_favorites_crud():
    token = _register_and_get_token("favs")
    headers = {"Authorization": f"Bearer {token}"}

    # Add favorite
    resp = client.post("/api/v1/favorites/", json={"entity_type": "team", "entity_id": 1}, headers=headers)
    assert resp.status_code == 201
    fav_id = resp.json()["id"]

    # List favorites
    resp = client.get("/api/v1/favorites/", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # Duplicate should fail
    resp = client.post("/api/v1/favorites/", json={"entity_type": "team", "entity_id": 1}, headers=headers)
    assert resp.status_code == 409

    # Delete
    resp = client.delete(f"/api/v1/favorites/{fav_id}", headers=headers)
    assert resp.status_code == 204
