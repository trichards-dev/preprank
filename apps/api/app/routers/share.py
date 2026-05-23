"""Share image endpoints — returns PNG images for social sharing and OG meta."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Team, School, PowerRating, Game, Sport,
    PickemContest, PickemEntry, PickemBadge, User, UserFavorite,
)
from app.services.share_images import (
    generate_team_card, generate_game_card,
    generate_pickem_results_card, generate_school_leaderboard_card,
    generate_badge_card,
)

router = APIRouter()


def _png_response(data: bytes) -> Response:
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/team/{team_id}/image")
def team_share_image(team_id: int, db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    school = db.query(School).filter(School.id == team.school_id).first()
    rating = (
        db.query(PowerRating)
        .filter(PowerRating.team_id == team_id, PowerRating.source == "engine")
        .order_by(PowerRating.week_number.desc())
        .first()
    )
    data = generate_team_card(
        school_name=school.name if school else "Unknown",
        rating=float(rating.power_rating) if rating else 0.0,
        rank=rating.rank_in_division or 0 if rating else 0,
        division=team.division or "",
        classification=school.classification or "" if school else "",
    )
    return _png_response(data)


@router.get("/game/{game_id}/image")
def game_share_image(game_id: int, db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    home_school = db.query(School).join(Team).filter(Team.id == game.home_team_id).first()
    away_school = db.query(School).join(Team).filter(Team.id == game.away_team_id).first()
    home_rating = db.query(PowerRating).filter(
        PowerRating.team_id == game.home_team_id, PowerRating.source == "engine"
    ).order_by(PowerRating.week_number.desc()).first()
    away_rating = db.query(PowerRating).filter(
        PowerRating.team_id == game.away_team_id, PowerRating.source == "engine"
    ).order_by(PowerRating.week_number.desc()).first()

    data = generate_game_card(
        home_team=home_school.name if home_school else "Home",
        away_team=away_school.name if away_school else "Away",
        home_rating=float(home_rating.power_rating) if home_rating else 0.0,
        away_rating=float(away_rating.power_rating) if away_rating else 0.0,
        game_date=str(game.game_date) if game.game_date else "",
    )
    return _png_response(data)


@router.get("/pickem/{contest_id}/user/{user_id}/image")
def pickem_share_image(contest_id: int, user_id: int, db: Session = Depends(get_db)):
    contest = db.query(PickemContest).filter(PickemContest.id == contest_id).first()
    if not contest:
        raise HTTPException(status_code=404, detail="Contest not found")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    entries = db.query(PickemEntry).filter(
        PickemEntry.contest_id == contest_id, PickemEntry.user_id == user_id,
    ).all()
    correct = sum(1 for e in entries if e.is_correct)
    total = sum(1 for e in entries if e.is_correct is not None)

    # Check for badges
    badge = db.query(PickemBadge).filter(
        PickemBadge.user_id == user_id, PickemBadge.contest_id == contest_id,
    ).first()

    # Get school from favorites
    fav = db.query(UserFavorite).filter(
        UserFavorite.user_id == user_id, UserFavorite.entity_type == "team",
    ).first()
    school_name = None
    if fav:
        team = db.query(Team).filter(Team.id == fav.entity_id).first()
        if team:
            school = db.query(School).filter(School.id == team.school_id).first()
            if school:
                school_name = school.name

    name = f"{user.first_name} {user.last_name[0]}." if user.first_name and user.last_name else "PrepRank User"
    data = generate_pickem_results_card(
        user_name=name, correct=correct, total=total,
        school_name=school_name,
        badge_name=badge.badge_name if badge else None,
        week=contest.week_number,
    )
    return _png_response(data)


@router.get("/leaderboard/{school_id}/image")
def leaderboard_share_image(school_id: int, db: Session = Depends(get_db)):
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    # Simple placeholder — in production, compute from actual leaderboard data
    data = generate_school_leaderboard_card(
        school_name=school.name, rank=1, correct=0, total=0, participants=0,
    )
    return _png_response(data)


@router.get("/badge/{badge_id}/image")
def badge_share_image(badge_id: int, db: Session = Depends(get_db)):
    badge = db.query(PickemBadge).filter(PickemBadge.id == badge_id).first()
    if not badge:
        raise HTTPException(status_code=404, detail="Badge not found")
    user = db.query(User).filter(User.id == badge.user_id).first()
    name = f"{user.first_name} {user.last_name[0]}." if user and user.first_name and user.last_name else "PrepRank User"

    data = generate_badge_card(
        user_name=name,
        badge_name=badge.badge_name,
        badge_description=badge.description or "",
    )
    return _png_response(data)
