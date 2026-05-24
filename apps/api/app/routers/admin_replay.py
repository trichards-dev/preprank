import csv
import io
from typing import Iterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.premium import require_admin
from app.database import get_db
from app.models import ReplayTesterSession, Sport, User
from app.schemas.admin_replay import (
    ReplayTesterSessionIn,
    ReplayTesterSessionOut,
)

router = APIRouter()


@router.post("/sessions", response_model=ReplayTesterSessionOut)
def create_session(
    payload: ReplayTesterSessionIn,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ReplayTesterSession:
    session = ReplayTesterSession(
        user_id=user.id,
        sport_id=payload.sport_id,
        season_year=payload.season_year,
        week_number=payload.week_number,
        task_text=payload.task_text,
        task_completed=payload.task_completed,
        time_to_complete_seconds=payload.time_to_complete_seconds,
        bug_found=payload.bug_found,
        bug_severity=payload.bug_severity,
        feature_gap_text=payload.feature_gap_text,
        screenshot_url=payload.screenshot_url,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ReplayTesterSessionOut])
def list_sessions(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[ReplayTesterSession]:
    return (
        db.query(ReplayTesterSession)
        .order_by(ReplayTesterSession.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


_CSV_COLUMNS = [
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


def _iter_csv(rows: list[tuple]) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_COLUMNS)
    yield buf.getvalue()
    buf.seek(0)
    buf.truncate(0)

    for row in rows:
        (
            session,
            user_email,
            sport_name,
        ) = row
        writer.writerow(
            [
                session.id,
                session.user_id,
                user_email or "",
                session.sport_id,
                sport_name or "",
                session.season_year,
                session.week_number,
                session.task_text or "",
                session.task_completed,
                session.time_to_complete_seconds
                if session.time_to_complete_seconds is not None
                else "",
                session.bug_found,
                session.bug_severity if session.bug_severity is not None else "",
                session.feature_gap_text or "",
                session.screenshot_url or "",
                session.created_at.isoformat() if session.created_at else "",
            ]
        )
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)


@router.get("/sessions.csv")
def export_sessions_csv(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    rows = (
        db.query(ReplayTesterSession, User.email, Sport.name)
        .outerjoin(User, User.id == ReplayTesterSession.user_id)
        .outerjoin(Sport, Sport.id == ReplayTesterSession.sport_id)
        .order_by(ReplayTesterSession.created_at.desc())
        .all()
    )

    return StreamingResponse(
        _iter_csv(rows),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="replay_tester_sessions.csv"'
        },
    )
