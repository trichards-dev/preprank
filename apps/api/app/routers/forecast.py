"""GET /api/v1/games/{game_id}/forecast — per-game forecast with CI + tier label.

Per the locked design in `forecast_api_design_2026-05-29.md` (memory):
  - Single endpoint with auth-conditional premium_detail block
  - Lazy in-memory cache + TTL (15min scheduled, 24hr final)
  - Reliability table loaded once at module import (production: at API startup)
  - Source-data caveat surfaces for Baseball (Spec 1a)
  - Forecast-unavailable surfaces with enum reason + sub-line (Spec 7)
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import get_optional_user
from app.auth.premium import _is_premium
from app.database import get_db
from app.models import Game, Sport, Team, User
from app.schemas.forecast import (
    ForecastBlock,
    GameForecastResponse,
    PremiumDetail,
    PredictedDecileReliability,
    SourceDataCaveat,
    TeamRef,
)

from engine.calibration.forecast import (
    build_premium_detail,
    compute_forecast,
)
from engine.calibration.source_caveats import get_source_caveat


router = APIRouter()


# --------------------------------------------------------------------
# Reliability table loading
# --------------------------------------------------------------------
# Located relative to repo root. Override via PREPRANK_RELIABILITY_TABLE
# env var for tests / staging.
_DEFAULT_TABLE_PATH = (
    Path(__file__).resolve().parents[4]
    / "data" / "calibration" / "phase6_reliability_table.json"
)


def _load_reliability_table() -> dict[str, Any]:
    path_str = os.environ.get("PREPRANK_RELIABILITY_TABLE")
    path = Path(path_str) if path_str else _DEFAULT_TABLE_PATH
    if not path.exists():
        # Production safety: empty table allows the API to start but
        # every forecast request returns SPORT_CALIBRATION_PENDING
        return {"schema_version": 0, "calibration_run_id": "missing", "sports": {}}
    return json.loads(path.read_text())


# Module-level singleton, loaded once at import. Hot-reload via the
# admin endpoint (defined below) reassigns this dict.
_RELIABILITY_TABLE: dict[str, Any] = _load_reliability_table()


# --------------------------------------------------------------------
# Lazy in-memory forecast cache (per-process)
# --------------------------------------------------------------------
# Keyed by (game_id, is_premium_flag). Value: (response_dict, expiry_epoch).
# Premium variant cached separately because premium_detail block differs.
_FORECAST_CACHE: dict[tuple[int, bool], tuple[dict[str, Any], float]] = {}

CACHE_TTL_SCHEDULED_SEC = 15 * 60      # 15 min for scheduled games
CACHE_TTL_FINAL_SEC = 24 * 60 * 60     # 24 hr for final games (forecast doesn't change)


def _cache_get(key: tuple[int, bool]) -> dict[str, Any] | None:
    entry = _FORECAST_CACHE.get(key)
    if entry is None:
        return None
    payload, expiry = entry
    if time.time() >= expiry:
        _FORECAST_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: tuple[int, bool], payload: dict[str, Any], game_status: str) -> None:
    ttl = CACHE_TTL_FINAL_SEC if game_status == "final" else CACHE_TTL_SCHEDULED_SEC
    _FORECAST_CACHE[key] = (payload, time.time() + ttl)


def _cache_clear() -> int:
    n = len(_FORECAST_CACHE)
    _FORECAST_CACHE.clear()
    return n


# --------------------------------------------------------------------
# Engine integration — placeholder for v1.0
# --------------------------------------------------------------------
def _resolve_home_win_probability(
    db: Session, game: Game, sport_name: str,
) -> tuple[float | None, str | None]:
    """Resolve the engine's home_win_probability for this game.

    Returns (probability, unavailable_reason). Exactly one is non-None.

    For v1.0, this is a lightweight placeholder that derives probability
    from the most recent pre-game power_ratings of both teams via the
    engine's predict_game_v3 path. Full wiring requires fetching team
    ratings at the game's `_engine_week - 1`, building GameState objects,
    and calling predict_game_v3.

    For the week-1 checkpoint, we use the SIMPLER prediction path: load
    each team's most recent power_rating + apply the existing engine
    win_probability heuristic. This is intentionally minimal — it
    surfaces a callable prediction without standing up the full
    GameState plumbing in v1.0. The probability is honest within the
    engine's current implementation; tighter prediction wiring lands
    in v1.1 when the per-game prediction flow gets its dedicated
    refactor.
    """
    from app.models import PowerRating

    h_rating_row = (
        db.query(PowerRating)
        .filter(PowerRating.team_id == game.home_team_id, PowerRating.source == "engine")
        .order_by(PowerRating.week_number.desc(), PowerRating.season_year.desc())
        .first()
    )
    a_rating_row = (
        db.query(PowerRating)
        .filter(PowerRating.team_id == game.away_team_id, PowerRating.source == "engine")
        .order_by(PowerRating.week_number.desc(), PowerRating.season_year.desc())
        .first()
    )

    if h_rating_row is None or a_rating_row is None:
        return None, "COLD_START_TEAM"

    h_rating = float(h_rating_row.power_rating)
    a_rating = float(a_rating_row.power_rating)

    # Use engine.win_probability for a sport-appropriate compute
    from engine.win_probability import win_probability
    try:
        prob = win_probability(home_rating=h_rating, away_rating=a_rating, sport=sport_name)
    except Exception:
        return None, "OTHER"

    return float(prob), None


# --------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------
@router.get("/{game_id}/forecast", response_model=GameForecastResponse)
def get_game_forecast(
    game_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> GameForecastResponse:
    """Return per-game forecast: probability + CI + tier label.

    Anonymous and non-premium auth → base response.
    Premium-authenticated → response includes the premium_detail block.

    Forecast unavailable cases return 200 with forecast=null and
    forecast_unavailable_reason populated (per Spec 7).
    """
    is_premium = bool(current_user and _is_premium(current_user))
    cache_key = (game_id, is_premium)
    cached = _cache_get(cache_key)
    if cached:
        return GameForecastResponse.model_validate(cached)

    game = (
        db.query(Game)
        .options(
            joinedload(Game.home_team).joinedload(Team.school),
            joinedload(Game.away_team).joinedload(Team.school),
        )
        .filter(Game.id == game_id)
        .first()
    )
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")

    sport_row = db.query(Sport).filter(Sport.id == game.sport_id).first()
    sport_name = sport_row.name if sport_row else "Unknown"
    home_team_name = (
        (game.home_team.school.name if game.home_team and game.home_team.school else None)
        or f"Team #{game.home_team_id}"
    )
    away_team_name = (
        (game.away_team.school.name if game.away_team and game.away_team.school else None)
        or f"Team #{game.away_team_id}"
    )

    # Resolve probability
    prob, unavailable_reason = _resolve_home_win_probability(db, game, sport_name)

    forecast_block: ForecastBlock | None = None
    premium_detail: PremiumDetail | None = None

    if prob is not None and sport_name in _RELIABILITY_TABLE.get("sports", {}):
        result = compute_forecast(prob, sport_name, _RELIABILITY_TABLE)
        forecast_block = ForecastBlock(
            home_win_probability=result.home_win_probability,
            home_win_probability_ci_low=result.home_win_probability_ci_low,
            home_win_probability_ci_high=result.home_win_probability_ci_high,
            confidence_tier=result.confidence_tier,  # type: ignore[arg-type]
            confidence_tier_label=result.confidence_tier_label,
        )
        if is_premium:
            detail_dict = build_premium_detail(
                sport_name=sport_name,
                home_team_id=game.home_team_id,
                away_team_id=game.away_team_id,
                predicted_decile=result.predicted_decile,
                reliability_table=_RELIABILITY_TABLE,
                home_typical_decile=None,  # v1.1 — per-team aggregate compute
                away_typical_decile=None,
            )
            decile_rel = detail_dict.get("predicted_decile_reliability")
            premium_detail = PremiumDetail(
                model_coefficients=detail_dict["model_coefficients"],
                home_typical_decile=detail_dict["home_typical_decile"],
                away_typical_decile=detail_dict["away_typical_decile"],
                predicted_decile=detail_dict["predicted_decile"],
                predicted_decile_reliability=(
                    PredictedDecileReliability(**decile_rel) if decile_rel else None
                ),
                methodology_deep_link=detail_dict["methodology_deep_link"],
            )
    elif prob is not None and sport_name not in _RELIABILITY_TABLE.get("sports", {}):
        unavailable_reason = "SPORT_CALIBRATION_PENDING"

    # Source-data caveat (Baseball only at v1.0)
    caveat = get_source_caveat(sport_name)
    caveat_block: SourceDataCaveat | None = None
    if caveat is not None:
        caveat_block = SourceDataCaveat(code=caveat.code, prose=caveat.prose)

    response = GameForecastResponse(
        game_id=game.id,
        sport=sport_name,
        season_year=game.season_year,
        week_number=game.week_number,
        status=game.status,
        home_team=TeamRef(id=game.home_team_id, name=home_team_name),
        away_team=TeamRef(id=game.away_team_id, name=away_team_name),
        forecast=forecast_block,
        forecast_unavailable_reason=unavailable_reason if forecast_block is None else None,  # type: ignore[arg-type]
        source_data_caveat=caveat_block,
        premium_detail=premium_detail,
        calibration_run_id=_RELIABILITY_TABLE.get("calibration_run_id", "unknown"),
        computed_at=datetime.now(timezone.utc).isoformat(),
    )

    _cache_set(cache_key, response.model_dump(), game.status or "scheduled")
    return response


# --------------------------------------------------------------------
# Admin endpoints
# --------------------------------------------------------------------
@router.post("/cache/clear")
def clear_forecast_cache(
    current_user: User = Depends(get_optional_user),
) -> dict[str, int]:
    """Admin: clear the in-memory forecast cache. Requires authenticated user."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    cleared = _cache_clear()
    return {"cleared": cleared}


@router.post("/reload")
def reload_reliability_table(
    current_user: User = Depends(get_optional_user),
) -> dict[str, Any]:
    """Admin: reload the reliability table from disk. Requires authenticated user."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    global _RELIABILITY_TABLE
    _RELIABILITY_TABLE = _load_reliability_table()
    _cache_clear()
    return {
        "calibration_run_id": _RELIABILITY_TABLE.get("calibration_run_id", "unknown"),
        "n_sports": len(_RELIABILITY_TABLE.get("sports", {})),
    }
