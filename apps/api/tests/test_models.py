from sqlalchemy import UniqueConstraint

from app.models import Sport, School, Team, Game, PowerRating


def test_sport_table_name():
    assert Sport.__tablename__ == "sports"


def test_school_table_name():
    assert School.__tablename__ == "schools"


def test_team_table_name():
    assert Team.__tablename__ == "teams"


def test_game_table_name():
    assert Game.__tablename__ == "games"


def test_power_rating_table_name():
    assert PowerRating.__tablename__ == "power_ratings"


def test_game_has_matchup_unique_constraint():
    """Game model declares uq_games_matchup on the canonical matchup columns.
    The scraper's upsert on_conflict target MUST stay in sync with this list."""
    uc = [c for c in Game.__table_args__ if isinstance(c, UniqueConstraint)]
    assert len(uc) == 1, "Game should declare exactly one UniqueConstraint"
    constraint = uc[0]
    assert constraint.name == "uq_games_matchup"
    assert [c.name for c in constraint.columns] == [
        "home_team_id", "away_team_id", "sport_id", "season_year", "game_date",
    ]
