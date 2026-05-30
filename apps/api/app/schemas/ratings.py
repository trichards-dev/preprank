from pydantic import BaseModel


class LatestWeekOut(BaseModel):
    sport: str
    season_year: int
    latest_week: int | None
    total_rankings: int


class PowerRatingOut(BaseModel):
    id: int
    team_id: int
    week_number: int
    season_year: int
    power_rating: float
    strength_factor: float | None = None
    rank_in_division: int | None = None
    total_teams_in_division: int | None = None

    model_config = {"from_attributes": True}


class RankedTeamOut(BaseModel):
    rank: int
    school_name: str
    division: str
    classification: str
    select_status: str
    power_rating: float
    strength_factor: float | None = None
    team_id: int
    school_id: int

    model_config = {"from_attributes": True}
