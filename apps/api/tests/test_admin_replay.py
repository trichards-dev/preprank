"""Tests for the Replay QA admin tool.

These tests require:
  - An empty (or at least clean) `users` and `replay_tester_sessions` table.
  - At least one `sports` row (any id) for the FK to resolve.

They follow the convention used by `test_auth.py` / `test_subscriptions.py`:
register users via `/api/v1/auth/register`, then flip `is_admin` directly in
the DB to elevate them. If your local DB isn't seeded with at least one Sport,
the create/list/CSV tests will be skipped — the gating tests still run.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import ReplayTesterSession, Sport, User

client = TestClient(app)


def _unique_email(prefix: str = "admin") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _register(prefix: str) -> tuple[str, int]:
    email = _unique_email(prefix)
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "testpass123",
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["id"]


def _make_admin(user_id: int) -> None:
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user_id).first()
        assert u is not None
        u.is_admin = True
        db.commit()
    finally:
        db.close()


def _existing_sport_id_or_skip() -> int:
    db = SessionLocal()
    try:
        sport = db.query(Sport).first()
        if sport is None:
            pytest.skip("No sports row in DB; seed the DB to run this test")
        return sport.id
    finally:
        db.close()


def _cleanup_user_sessions(user_id: int) -> None:
    db = SessionLocal()
    try:
        db.query(ReplayTesterSession).filter(
            ReplayTesterSession.user_id == user_id
        ).delete()
        db.commit()
    finally:
        db.close()


def test_non_admin_gets_404_on_post():
    token, _ = _register("nonadmin")
    resp = client.post(
        "/api/v1/admin/replay/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "sport_id": 1,
            "season_year": 2025,
            "week_number": 1,
            "task_text": "test",
        },
    )
    assert resp.status_code == 404


def test_anon_gets_401_or_404():
    resp = client.post(
        "/api/v1/admin/replay/sessions",
        json={
            "sport_id": 1,
            "season_year": 2025,
            "week_number": 1,
            "task_text": "test",
        },
    )
    assert resp.status_code in (401, 404)


def test_admin_can_create_session():
    sport_id = _existing_sport_id_or_skip()
    token, user_id = _register("admincreate")
    _make_admin(user_id)
    _cleanup_user_sessions(user_id)

    resp = client.post(
        "/api/v1/admin/replay/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "sport_id": sport_id,
            "season_year": 2024,
            "week_number": 5,
            "task_text": "Rank Division I teams after Week 5",
            "task_completed": True,
            "time_to_complete_seconds": 42,
            "bug_found": False,
            "feature_gap_text": "Want SOS column on ratings page",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["task_text"] == "Rank Division I teams after Week 5"
    assert data["user_id"] == user_id
    assert "id" in data
    assert "created_at" in data

    db = SessionLocal()
    try:
        row = (
            db.query(ReplayTesterSession)
            .filter(ReplayTesterSession.id == data["id"])
            .first()
        )
        assert row is not None
        assert row.user_id == user_id
        assert row.season_year == 2024
    finally:
        db.close()


def test_admin_can_list_own_sessions():
    sport_id = _existing_sport_id_or_skip()
    token, user_id = _register("adminlist")
    _make_admin(user_id)
    _cleanup_user_sessions(user_id)

    for week in (1, 2, 3):
        client.post(
            "/api/v1/admin/replay/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "sport_id": sport_id,
                "season_year": 2024,
                "week_number": week,
                "task_text": f"Task week {week}",
            },
        )

    resp = client.get(
        "/api/v1/admin/replay/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload, list)
    own = [s for s in payload if s["user_id"] == user_id]
    assert len(own) >= 3


def test_admin_can_export_csv():
    sport_id = _existing_sport_id_or_skip()
    token, user_id = _register("admincsv")
    _make_admin(user_id)
    _cleanup_user_sessions(user_id)

    client.post(
        "/api/v1/admin/replay/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "sport_id": sport_id,
            "season_year": 2024,
            "week_number": 1,
            "task_text": "csv export check",
        },
    )

    resp = client.get(
        "/api/v1/admin/replay/sessions.csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")

    body = resp.text
    lines = [line for line in body.splitlines() if line.strip()]
    assert len(lines) >= 2  # header + at least one row
    header = lines[0].split(",")
    expected_columns = [
        "id",
        "user_id",
        "user_email",
        "sport_id",
        "sport_name",
        "season_year",
        "week_number",
        "task_text",
        "task_completed",
        "time_to_complete_seconds",
        "bug_found",
        "bug_severity",
        "feature_gap_text",
        "screenshot_url",
        "created_at",
    ]
    assert header == expected_columns


def test_bug_severity_required_when_bug_found_is_true():
    token, user_id = _register("adminvalid")
    _make_admin(user_id)

    resp = client.post(
        "/api/v1/admin/replay/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "sport_id": 1,
            "season_year": 2024,
            "week_number": 1,
            "task_text": "validator test",
            "bug_found": True,
            # bug_severity intentionally omitted
        },
    )
    assert resp.status_code == 422
