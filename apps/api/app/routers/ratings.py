import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Game, PowerRating, Team, School, Sport
from app.schemas.ratings import LatestWeekOut, PowerRatingOut, RankedTeamOut
from engine.types import TeamRecord, GameResult, GameStatus as EngineGameStatus
from engine.power_rating import calculate_all_ratings

router = APIRouter()


# Lazy in-memory cache for latest-week lookups.
# Key: (sport_lower, season_year, source). Value: (payload_dict, expiry_epoch).
# Rankings change at most weekly; a 5-minute TTL lets new weeks surface
# shortly after publication while absorbing the obvious re-load bursts.
_LATEST_WEEK_CACHE: dict[tuple[str, int, str], tuple[dict, float]] = {}
_LATEST_WEEK_TTL_SEC = 5 * 60


@router.get("/rankings", response_model=list[RankedTeamOut])
def list_rankings(
    sport: str = Query(..., description="Sport name (e.g. Football)"),
    season_year: int = Query(..., description="Season year"),
    week_number: int = Query(..., description="Week number"),
    division: str | None = Query(None, description="Filter by division"),
    source: str = Query("engine", description="Rating source: 'engine' or 'lhsaa_official'"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = (
        db.query(PowerRating, Team, School)
        .join(Team, PowerRating.team_id == Team.id)
        .join(School, Team.school_id == School.id)
        .join(Sport, Team.sport_id == Sport.id)
        .filter(
            Sport.name.ilike(sport),
            PowerRating.season_year == season_year,
            PowerRating.week_number == week_number,
            PowerRating.source == source,
        )
    )
    if division:
        query = query.filter(Team.division == division)
    # Always sort by power_rating descending and compute rank from position
    query = query.order_by(PowerRating.power_rating.desc())
    results = query.offset(offset).limit(limit).all()

    ranked_results = []
    for i, (pr, team, school) in enumerate(results, start=offset + 1):
        ranked_results.append(RankedTeamOut(
            rank=i,
            school_name=school.name,
            division=team.division,
            classification=school.classification,
            select_status=school.select_status or "",
            power_rating=float(pr.power_rating),
            strength_factor=float(pr.strength_factor) if pr.strength_factor else None,
            team_id=team.id,
            school_id=school.id,
        ))
    return ranked_results


@router.get("/latest-week", response_model=LatestWeekOut)
def get_latest_week(
    sport: str = Query(..., description="Sport name (e.g. Football)"),
    season_year: int = Query(..., description="Season year"),
    source: str = Query(
        "engine",
        description="Rating source — 'engine' for PrepRank canonical rankings",
    ),
    db: Session = Depends(get_db),
):
    """Return the latest published week for a sport/season + ranked-team count.

    Used by the web rankings page to find the most recent week before
    issuing a /rankings call. Returns latest_week=null + total_rankings=0
    when a valid sport has no rankings yet for the requested season.
    Returns 404 only when the sport name does not resolve to any Sport row.
    """
    cache_key = (sport.lower(), season_year, source)
    entry = _LATEST_WEEK_CACHE.get(cache_key)
    if entry is not None:
        payload, expiry = entry
        if time.time() < expiry:
            return LatestWeekOut.model_validate(payload)
        _LATEST_WEEK_CACHE.pop(cache_key, None)

    sport_row = (
        db.query(Sport)
        .filter(func.lower(Sport.name) == sport.lower())
        .first()
    )
    if sport_row is None:
        raise HTTPException(status_code=404, detail="Sport not found")

    latest = (
        db.query(func.max(PowerRating.week_number))
        .join(Team, PowerRating.team_id == Team.id)
        .filter(
            Team.sport_id == sport_row.id,
            PowerRating.season_year == season_year,
            PowerRating.source == source,
        )
        .scalar()
    )

    total = 0
    if latest is not None:
        total = (
            db.query(func.count(PowerRating.id))
            .join(Team, PowerRating.team_id == Team.id)
            .filter(
                Team.sport_id == sport_row.id,
                PowerRating.season_year == season_year,
                PowerRating.source == source,
                PowerRating.week_number == latest,
            )
            .scalar()
        ) or 0

    out = LatestWeekOut(
        sport=sport_row.name,
        season_year=season_year,
        latest_week=int(latest) if latest is not None else None,
        total_rankings=int(total),
    )
    _LATEST_WEEK_CACHE[cache_key] = (out.model_dump(), time.time() + _LATEST_WEEK_TTL_SEC)
    return out


@router.get("/{team_id}", response_model=list[PowerRatingOut])
def get_team_ratings(
    team_id: int,
    season_year: int = Query(..., description="Season year"),
    source: str = Query("engine", description="Rating source: 'engine' or 'lhsaa_official'"),
    db: Session = Depends(get_db),
):
    ratings = (
        db.query(PowerRating)
        .filter(
            PowerRating.team_id == team_id,
            PowerRating.season_year == season_year,
            PowerRating.source == source,
        )
        .order_by(PowerRating.week_number.asc())
        .all()
    )
    return ratings


DIVISION_TO_CLASSIFICATION = {"I": "5A", "II": "4A", "III": "3A", "IV": "2A", "V": "1A"}


@router.post("/recalculate")
def recalculate_ratings(
    sport: str = Query(..., description="Sport name"),
    season_year: int = Query(..., description="Season year"),
    week_number: int = Query(..., description="Week to calculate through"),
    db: Session = Depends(get_db),
):
    """Recalculate power ratings for all teams in a sport/season."""
    sport_obj = db.query(Sport).filter(Sport.name == sport).first()
    if not sport_obj:
        raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")

    # Load teams
    team_rows = (
        db.query(Team, School)
        .join(School, Team.school_id == School.id)
        .filter(Team.sport_id == sport_obj.id, Team.season_year == season_year)
        .all()
    )
    teams = {}
    for team, school in team_rows:
        cls = school.classification or DIVISION_TO_CLASSIFICATION.get(team.division, "5A")
        teams[team.id] = TeamRecord(
            team_id=team.id, school_name=school.name,
            division=team.division, classification=cls,
        )

    # Load games
    game_rows = (
        db.query(Game)
        .filter(
            Game.sport_id == sport_obj.id,
            Game.season_year == season_year,
            Game.status.in_(["final", "forfeit"]),
            Game.week_number <= week_number,
        )
        .all()
    )
    games = [
        GameResult(
            game_id=g.id, home_team_id=g.home_team_id, away_team_id=g.away_team_id,
            home_score=g.home_score, away_score=g.away_score,
            status=EngineGameStatus(g.status),
            is_forfeit=(g.status == "forfeit"),
            week_number=g.week_number,
        )
        for g in game_rows
    ]

    # Calculate ratings
    result = calculate_all_ratings(teams, games)

    # Rank within division
    by_div: dict[str, list[tuple[int, float]]] = {}
    for tid, t in result.items():
        by_div.setdefault(t.division, []).append((tid, t.power_rating))

    ranks = {}
    div_counts = {}
    for div, div_teams in by_div.items():
        sorted_teams = sorted(div_teams, key=lambda x: -x[1])
        div_counts[div] = len(sorted_teams)
        for rank, (tid, _) in enumerate(sorted_teams, 1):
            ranks[tid] = rank

    # Upsert power ratings (engine-source only; LHSAA-official rows live in their own partial index)
    updated = 0
    for tid, t in result.items():
        existing = db.query(PowerRating).filter(
            PowerRating.team_id == tid,
            PowerRating.week_number == week_number,
            PowerRating.season_year == season_year,
            PowerRating.source == "engine",
        ).first()
        if existing:
            existing.power_rating = t.power_rating
            existing.strength_factor = t.strength_factor
            existing.rank_in_division = ranks.get(tid)
            existing.total_teams_in_division = div_counts.get(t.division)
        else:
            db.add(PowerRating(
                team_id=tid, week_number=week_number, season_year=season_year,
                power_rating=t.power_rating, strength_factor=t.strength_factor,
                rank_in_division=ranks.get(tid),
                total_teams_in_division=div_counts.get(t.division),
                source="engine",
            ))
        updated += 1
    db.commit()

    return {"status": "ok", "teams_updated": updated, "games_processed": len(games)}

