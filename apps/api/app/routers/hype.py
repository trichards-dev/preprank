"""Hype Score endpoints — trending teams, risers, fallers."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models import HypeScore, Team, School, PowerRating
from pydantic import BaseModel

router = APIRouter()


class HypeScoreOut(BaseModel):
    team_id: int
    school_name: str
    division: str
    hype_score: float
    hype_label: str
    rating_velocity: float | None
    win_streak: int
    power_rating: float | None = None

    model_config = {"from_attributes": True}


def _build_hype_response(db, hype, team, school) -> HypeScoreOut:
    # Get latest power rating
    pr = db.query(PowerRating).filter(
        PowerRating.team_id == team.id, PowerRating.source == "engine"
    ).order_by(PowerRating.week_number.desc()).first()

    return HypeScoreOut(
        team_id=team.id,
        school_name=school.name,
        division=team.division or "",
        hype_score=float(hype.hype_score),
        hype_label=hype.hype_label,
        rating_velocity=float(hype.rating_velocity) if hype.rating_velocity else None,
        win_streak=hype.win_streak or 0,
        power_rating=float(pr.power_rating) if pr else None,
    )


@router.get("/team/{team_id}", response_model=HypeScoreOut)
def get_team_hype(team_id: int, db: Session = Depends(get_db)):
    hype = db.query(HypeScore).filter(
        HypeScore.team_id == team_id
    ).order_by(HypeScore.week_number.desc()).first()
    if not hype:
        raise HTTPException(status_code=404, detail="No hype score for this team")
    team = db.query(Team).filter(Team.id == team_id).first()
    school = db.query(School).filter(School.id == team.school_id).first()
    return _build_hype_response(db, hype, team, school)


@router.get("/trending", response_model=list[HypeScoreOut])
def trending_teams(
    season_year: int = Query(2025),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Top teams by hype score."""
    # Get latest week with hype data
    latest = db.query(HypeScore.week_number).filter(
        HypeScore.season_year == season_year
    ).order_by(HypeScore.week_number.desc()).first()
    if not latest:
        return []

    rows = (
        db.query(HypeScore, Team, School)
        .join(Team, HypeScore.team_id == Team.id)
        .join(School, Team.school_id == School.id)
        .filter(HypeScore.season_year == season_year, HypeScore.week_number == latest[0])
        .order_by(desc(HypeScore.hype_score))
        .limit(limit)
        .all()
    )
    return [_build_hype_response(db, h, t, s) for h, t, s in rows]


@router.get("/risers", response_model=list[HypeScoreOut])
def hype_risers(
    season_year: int = Query(2025),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Teams with biggest hype score increases."""
    rows = (
        db.query(HypeScore, Team, School)
        .join(Team, HypeScore.team_id == Team.id)
        .join(School, Team.school_id == School.id)
        .filter(HypeScore.season_year == season_year)
        .order_by(desc(HypeScore.rating_velocity))
        .limit(limit)
        .all()
    )
    return [_build_hype_response(db, h, t, s) for h, t, s in rows]


@router.get("/fallers", response_model=list[HypeScoreOut])
def hype_fallers(
    season_year: int = Query(2025),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Teams with biggest hype score drops."""
    rows = (
        db.query(HypeScore, Team, School)
        .join(Team, HypeScore.team_id == Team.id)
        .join(School, Team.school_id == School.id)
        .filter(HypeScore.season_year == season_year)
        .order_by(HypeScore.rating_velocity.asc())
        .limit(limit)
        .all()
    )
    return [_build_hype_response(db, h, t, s) for h, t, s in rows]
