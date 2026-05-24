from sqlalchemy import (
    Column, Integer, String, Boolean, Date, Numeric,
    ForeignKey, DateTime, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Sport(Base):
    __tablename__ = "sports"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    season = Column(String(20), nullable=False)
    has_power_rating = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    teams = relationship("Team", back_populates="sport")


class School(Base):
    __tablename__ = "schools"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    city = Column(String(100))
    parish = Column(String(100))
    classification = Column(String(10))
    division = Column(String(10))
    select_status = Column(String(20))
    enrollment = Column(Integer)
    lhsaa_member_id = Column(String(50))
    mascot = Column(String(100))
    mascot_url = Column(String(500))
    color1 = Column(String(10))
    color2 = Column(String(10))
    maxpreps_uuid = Column(String(50), unique=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

    teams = relationship("Team", back_populates="school")


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"))
    sport_id = Column(Integer, ForeignKey("sports.id"))
    season_year = Column(Integer, nullable=False)
    head_coach = Column(String(200))
    division = Column(String(10))
    select_status = Column(String(20))
    created_at = Column(DateTime, server_default=func.now())

    school = relationship("School", back_populates="teams")
    sport = relationship("Sport", back_populates="teams")
    power_ratings = relationship("PowerRating", back_populates="team")
    home_games = relationship("Game", foreign_keys="Game.home_team_id", back_populates="home_team")
    away_games = relationship("Game", foreign_keys="Game.away_team_id", back_populates="away_team")

    __table_args__ = (UniqueConstraint("school_id", "sport_id", "season_year"),)


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True)
    home_team_id = Column(Integer, ForeignKey("teams.id"))
    away_team_id = Column(Integer, ForeignKey("teams.id"))
    sport_id = Column(Integer, ForeignKey("sports.id"))
    season_year = Column(Integer, nullable=False)
    game_date = Column(Date)
    week_number = Column(Integer)
    home_score = Column(Integer)
    away_score = Column(Integer)
    status = Column(String(20), default="scheduled")
    is_district = Column(Boolean, default=False)
    is_playoff = Column(Boolean, default=False)
    is_championship = Column(Boolean, default=False)
    is_out_of_state = Column(Boolean, default=False)
    source = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

    home_team = relationship("Team", foreign_keys=[home_team_id], back_populates="home_games")
    away_team = relationship("Team", foreign_keys=[away_team_id], back_populates="away_games")


class PowerRating(Base):
    __tablename__ = "power_ratings"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    week_number = Column(Integer, nullable=False)
    season_year = Column(Integer, nullable=False)
    power_rating = Column(Numeric(6, 2), nullable=False)
    strength_factor = Column(Numeric(6, 2))
    rank_in_division = Column(Integer)
    total_teams_in_division = Column(Integer)
    source = Column(String(32), nullable=False, default="engine")
    snapshot_date = Column(Date, nullable=True)
    calculated_at = Column(DateTime, server_default=func.now())

    team = relationship("Team", back_populates="power_ratings")


class Simulation(Base):
    __tablename__ = "simulations"

    id = Column(Integer, primary_key=True)
    sport_id = Column(Integer, ForeignKey("sports.id"))
    season_year = Column(Integer, nullable=False)
    week_number = Column(Integer, nullable=False)
    run_count = Column(Integer, default=10000)
    status = Column(String(20), default="pending")
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    sport = relationship("Sport")
    projected_ratings = relationship("ProjectedRating", back_populates="simulation", cascade="all, delete-orphan")
    game_predictions = relationship("GamePrediction", back_populates="simulation", cascade="all, delete-orphan")
    game_impacts = relationship("GameImpactAnalysis", back_populates="simulation", cascade="all, delete-orphan")


class ProjectedRating(Base):
    __tablename__ = "projected_ratings"

    id = Column(Integer, primary_key=True)
    simulation_id = Column(Integer, ForeignKey("simulations.id", ondelete="CASCADE"))
    team_id = Column(Integer, ForeignKey("teams.id"))
    projected_rating_mean = Column(Numeric(6, 2))
    projected_rating_median = Column(Numeric(6, 2))
    projected_rating_p10 = Column(Numeric(6, 2))
    projected_rating_p90 = Column(Numeric(6, 2))
    projected_rank_mean = Column(Numeric(6, 1))
    playoff_probability = Column(Numeric(5, 2))
    championship_probability = Column(Numeric(5, 2))
    projected_wins_mean = Column(Numeric(4, 1))
    projected_losses_mean = Column(Numeric(4, 1))
    created_at = Column(DateTime, server_default=func.now())

    simulation = relationship("Simulation", back_populates="projected_ratings")
    team = relationship("Team")


class GamePrediction(Base):
    __tablename__ = "game_predictions"

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"))
    simulation_id = Column(Integer, ForeignKey("simulations.id", ondelete="CASCADE"))
    home_win_probability = Column(Numeric(5, 2))
    predicted_home_score = Column(Numeric(5, 1))
    predicted_away_score = Column(Numeric(5, 1))
    predicted_spread = Column(Numeric(5, 1))
    created_at = Column(DateTime, server_default=func.now())

    simulation = relationship("Simulation", back_populates="game_predictions")
    game = relationship("Game")


class GameImpactAnalysis(Base):
    __tablename__ = "game_impact_analysis"

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"))
    simulation_id = Column(Integer, ForeignKey("simulations.id", ondelete="CASCADE"))
    affected_team_id = Column(Integer, ForeignKey("teams.id"))
    rating_if_home_wins = Column(Numeric(6, 2))
    rating_if_away_wins = Column(Numeric(6, 2))
    rank_if_home_wins = Column(Integer)
    rank_if_away_wins = Column(Integer)
    playoff_prob_if_home_wins = Column(Numeric(5, 2))
    playoff_prob_if_away_wins = Column(Numeric(5, 2))
    created_at = Column(DateTime, server_default=func.now())

    simulation = relationship("Simulation", back_populates="game_impacts")
    game = relationship("Game")
    affected_team = relationship("Team")


class HypeScore(Base):
    __tablename__ = "hype_scores"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    week_number = Column(Integer, nullable=False)
    season_year = Column(Integer, nullable=False)
    hype_score = Column(Numeric(5, 1), nullable=False)
    hype_label = Column(String(20), nullable=False)
    rating_velocity = Column(Numeric(6, 3))
    win_streak = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    team = relationship("Team")

    __table_args__ = (UniqueConstraint("team_id", "week_number", "season_year"),)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    subscription_tier = Column(String(20), default="free")
    subscription_expires = Column(DateTime)
    stripe_customer_id = Column(String(100))
    push_token = Column(String(500))
    is_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


class UserFavorite(Base):
    __tablename__ = "user_favorites"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    entity_type = Column(String(20), nullable=False)
    entity_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")

    __table_args__ = (UniqueConstraint("user_id", "entity_type", "entity_id"),)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    token = Column(String(500), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")


class PickemContest(Base):
    __tablename__ = "pickem_contests"

    id = Column(Integer, primary_key=True)
    sport_id = Column(Integer, ForeignKey("sports.id"))
    season_year = Column(Integer, nullable=False)
    week_number = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    status = Column(String(20), default="draft")
    opens_at = Column(DateTime)
    locks_at = Column(DateTime)
    scored_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    sport = relationship("Sport")
    entries = relationship("PickemEntry", back_populates="contest", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("sport_id", "season_year", "week_number"),)


class PickemEntry(Base):
    __tablename__ = "pickem_entries"

    id = Column(Integer, primary_key=True)
    contest_id = Column(Integer, ForeignKey("pickem_contests.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    game_id = Column(Integer, ForeignKey("games.id"))
    picked_team_id = Column(Integer, ForeignKey("teams.id"))
    is_correct = Column(Boolean)
    points_earned = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    contest = relationship("PickemContest", back_populates="entries")
    user = relationship("User")
    game = relationship("Game")
    picked_team = relationship("Team")

    __table_args__ = (UniqueConstraint("contest_id", "user_id", "game_id"),)


class PickemBadge(Base):
    __tablename__ = "pickem_badges"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    badge_type = Column(String(50), nullable=False)
    badge_name = Column(String(200), nullable=False)
    description = Column(String(500))
    earned_at = Column(DateTime, server_default=func.now())
    contest_id = Column(Integer, ForeignKey("pickem_contests.id"))
    metadata_json = Column(Text)

    user = relationship("User")
    contest = relationship("PickemContest")


class ReplayTesterSession(Base):
    __tablename__ = "replay_tester_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    sport_id = Column(Integer, ForeignKey("sports.id"))
    season_year = Column(Integer, nullable=False)
    week_number = Column(Integer, nullable=False)
    task_text = Column(Text, nullable=False)
    task_completed = Column(Boolean, nullable=False, default=False)
    time_to_complete_seconds = Column(Integer)
    bug_found = Column(Boolean, nullable=False, default=False)
    bug_severity = Column(Integer)
    feature_gap_text = Column(Text)
    screenshot_url = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    sport = relationship("Sport")
