import uuid

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import User, RefreshToken

client = TestClient(app)


def _unique_email(prefix: str = "test") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def setup_module():
    """Clean auth tables before running tests."""
    db = SessionLocal()
    db.query(RefreshToken).delete()
    db.query(User).delete()
    db.commit()
    db.close()


def test_register():
    resp = client.post("/api/v1/auth/register", json={
        "email": _unique_email("reg"),
        "password": "testpass123",
        "first_name": "Test",
        "last_name": "User",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_register_duplicate_email():
    email = _unique_email("dupe")
    client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "testpass123",
        "first_name": "Dupe",
        "last_name": "User",
    })
    resp = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "testpass123",
        "first_name": "Dupe",
        "last_name": "User",
    })
    assert resp.status_code == 400


def test_login():
    email = _unique_email("login")
    client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "testpass123",
        "first_name": "Login",
        "last_name": "User",
    })
    resp = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "testpass123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password():
    email = _unique_email("wrongpw")
    client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "testpass123",
        "first_name": "Wrong",
        "last_name": "User",
    })
    resp = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


def test_get_me():
    email = _unique_email("me")
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "testpass123",
        "first_name": "Me",
        "last_name": "User",
    })
    token = reg.json()["access_token"]
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == email
    assert resp.json()["subscription_tier"] == "free"


def test_get_me_no_token():
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_refresh_token():
    email = _unique_email("refresh")
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "testpass123",
        "first_name": "Refresh",
        "last_name": "User",
    })
    refresh = reg.json()["refresh_token"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    assert "access_token" in resp.json()
    # Old token should be revoked
    resp2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp2.status_code == 401


def test_update_me():
    email = _unique_email("update")
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "testpass123",
        "first_name": "Old",
        "last_name": "Name",
    })
    token = reg.json()["access_token"]
    resp = client.patch("/api/v1/auth/me",
        json={"first_name": "New"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "New"
