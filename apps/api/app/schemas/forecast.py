"""Forecast endpoint Pydantic schemas.

Per `forecast_api_design_2026-05-29.md` (memory):
  - Single endpoint GET /api/v1/games/{game_id}/forecast
  - Auth-conditional premium_detail block (null for anon/non-premium)
  - Source-data caveat field (populated for Baseball, null otherwise)
  - forecast_unavailable_reason enum when forecast is null (Spec 7)
  - calibration_run_id field for transparency
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------
# forecast_unavailable_reason enum (Spec 7)
# --------------------------------------------------------------------
ForecastUnavailableReason = Literal[
    "INSUFFICIENT_PRIOR_DATA",
    "RECENTLY_SCHEDULED",
    "SPORT_CALIBRATION_PENDING",
    "COLD_START_TEAM",
    "OTHER",
]


# --------------------------------------------------------------------
# Confidence tier enum (Spec 2)
# --------------------------------------------------------------------
ConfidenceTier = Literal["confident_pick", "lean", "toss_up", "long_shot"]


# --------------------------------------------------------------------
# Sub-blocks
# --------------------------------------------------------------------
class TeamRef(BaseModel):
    id: int
    name: str


class ForecastBlock(BaseModel):
    """The probability + CI + tier label block. Returned when forecast available."""
    home_win_probability: int                                # 0..100
    home_win_probability_ci_low: int                         # 0..100
    home_win_probability_ci_high: int                        # 0..100
    confidence_tier: ConfidenceTier
    confidence_tier_label: str


class SourceDataCaveat(BaseModel):
    """Sport-specific source-data caveat (Spec 1a). Currently Baseball-only."""
    code: str
    prose: str


class PredictedDecileReliability(BaseModel):
    """Per-decile reliability stat surfaced in premium drawer."""
    n_games: int
    gap: float
    mean_predicted: float | None
    mean_observed: float | None


class PremiumDetail(BaseModel):
    """Premium-auth-conditional fields per Spec 5."""
    model_coefficients: dict[str, float]
    home_typical_decile: int | None
    away_typical_decile: int | None
    predicted_decile: int
    predicted_decile_reliability: PredictedDecileReliability | None
    methodology_deep_link: str


# --------------------------------------------------------------------
# Top-level response
# --------------------------------------------------------------------
class GameForecastResponse(BaseModel):
    """GET /api/v1/games/{game_id}/forecast response shape."""
    game_id: int
    sport: str
    season_year: int
    week_number: int | None
    status: str
    home_team: TeamRef
    away_team: TeamRef

    # forecast can be None when unavailable; if None, reason MUST be set
    forecast: ForecastBlock | None
    forecast_unavailable_reason: ForecastUnavailableReason | None = None

    # Sport-specific source-data caveat (currently Baseball-only)
    source_data_caveat: SourceDataCaveat | None = None

    # Premium-conditional; null for anonymous + non-premium users
    premium_detail: PremiumDetail | None = None

    # Calibration run identifier — public per Spec 5 Q5 decision
    calibration_run_id: str

    # ISO 8601 UTC timestamp of when this forecast was computed
    computed_at: str
