"""Unit tests for the engine.validator package.

Coverage targets:
    - metrics: brier perfect / coin-flip / accuracy / reliability / bootstrap
    - predictor: predict_game routes to win_probability_v2
    - runner: end-to-end smoke with a fake Supabase client
    - cli: arg parsing helpers
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from engine.prediction.config import PredictionConfig
from engine.validator.cli import _parse_seasons, _parse_sports
from engine.validator.metrics import (
    bootstrap_ci,
    brier_score,
    game_winner_accuracy,
    playoff_field_accuracy,
    rating_projection_delta,
    reliability_bins,
)
from engine.validator.predictor import PredictionRecord, predict_game
from engine.validator.runner import run_validation
from engine.win_probability import win_probability_v2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_pred(p_home: float, home_won: bool, *, game_id: int = 1, sport: str = "Football",
               season: int = 2024, week: int = 5, cold: bool = False) -> PredictionRecord:
    return PredictionRecord(
        game_id=game_id,
        home_team_id=10 + game_id,
        away_team_id=100 + game_id,
        home_win_probability=p_home,
        predicted_home_score=None,
        predicted_away_score=None,
        predicted_spread=None,
        home_rating_pregame=0.0,
        away_rating_pregame=0.0,
        home_cold_start=cold,
        away_cold_start=False,
        actual_home_won=home_won,
        sport=sport,
        season_year=season,
        week_number=week,
    )


# ---------------------------------------------------------------------------
# metrics: brier + accuracy
# ---------------------------------------------------------------------------
def test_brier_score_perfect_predictions():
    preds = [_make_pred(1.0, True, game_id=1), _make_pred(0.0, False, game_id=2)]
    assert brier_score(preds) == 0.0


def test_brier_score_coin_flip():
    preds = [_make_pred(0.5, True, game_id=i) for i in range(5)] + \
            [_make_pred(0.5, False, game_id=10 + i) for i in range(5)]
    assert brier_score(preds) == pytest.approx(0.25)


def test_brier_empty_returns_zero():
    assert brier_score([]) == 0.0


def test_game_winner_accuracy_perfect_and_inverted():
    perfect = [_make_pred(0.9, True, game_id=1), _make_pred(0.1, False, game_id=2)]
    assert game_winner_accuracy(perfect) == 1.0

    inverted = [_make_pred(0.9, False, game_id=1), _make_pred(0.1, True, game_id=2)]
    assert game_winner_accuracy(inverted) == 0.0


def test_game_winner_accuracy_handles_unscored():
    # Predictions with actual_home_won=None are dropped before scoring
    preds = [_make_pred(0.9, True, game_id=1), _make_pred(0.7, None, game_id=2)]
    # Effective sample = 1, perfect
    assert game_winner_accuracy(preds) == 1.0


def test_game_winner_accuracy_half_is_miss():
    # Probability of exactly 0.5 is graded as 'no opinion' = miss
    preds = [_make_pred(0.5, True, game_id=1)]
    assert game_winner_accuracy(preds) == 0.0


# ---------------------------------------------------------------------------
# metrics: reliability
# ---------------------------------------------------------------------------
def test_reliability_bins_uniform():
    # 10 predictions, each in a distinct decile, half-true half-false alternating
    preds: list[PredictionRecord] = []
    for i in range(10):
        p = 0.05 + 0.1 * i  # 0.05, 0.15, ..., 0.95
        preds.append(_make_pred(p, i % 2 == 0, game_id=i + 1))
    bins = reliability_bins(preds, n_bins=10)
    assert len(bins) == 10
    for b in bins:
        assert b["n_games"] in (0, 1, 2)
    # The 0.95 prediction falls in the [0.9, 1.0] (final, inclusive) bin
    assert any(b["n_games"] >= 1 and 0.9 <= b["bin_lower"] <= 1.0 for b in bins)
    # Total game count across bins matches input
    assert sum(b["n_games"] for b in bins) == 10


def test_reliability_bins_handles_empty():
    bins = reliability_bins([], n_bins=10)
    assert len(bins) == 10
    assert all(b["n_games"] == 0 for b in bins)


def test_reliability_bins_invalid_n_bins():
    with pytest.raises(ValueError):
        reliability_bins([], n_bins=0)


# ---------------------------------------------------------------------------
# metrics: bootstrap CI
# ---------------------------------------------------------------------------
def test_bootstrap_ci_known_distribution():
    # All-correct predictions => any bootstrap resample is also all-correct => CI [1.0, 1.0]
    preds = [_make_pred(0.9, True, game_id=i) for i in range(50)]
    lo, hi = bootstrap_ci(game_winner_accuracy, preds, n_resamples=200, seed=0)
    assert lo == pytest.approx(1.0)
    assert hi == pytest.approx(1.0)


def test_bootstrap_ci_mixed_distribution():
    # 50% accuracy on a noisy sample: CI should contain ~0.5 with reasonable width
    preds = []
    for i in range(100):
        preds.append(_make_pred(0.7, i % 2 == 0, game_id=i + 1))
    lo, hi = bootstrap_ci(game_winner_accuracy, preds, n_resamples=500, seed=7)
    assert 0.3 < lo < 0.5
    assert 0.5 < hi < 0.7


def test_bootstrap_ci_empty_and_singleton():
    assert bootstrap_ci(game_winner_accuracy, [], n_resamples=10) == (0.0, 0.0)
    one = [_make_pred(0.6, True)]
    lo, hi = bootstrap_ci(game_winner_accuracy, one, n_resamples=10)
    assert lo == hi == 1.0


def test_bootstrap_ci_invalid_args():
    with pytest.raises(ValueError):
        bootstrap_ci(game_winner_accuracy, [], n_resamples=0)
    with pytest.raises(ValueError):
        bootstrap_ci(game_winner_accuracy, [], ci=0.0)
    with pytest.raises(ValueError):
        bootstrap_ci(game_winner_accuracy, [], ci=1.0)


# ---------------------------------------------------------------------------
# metrics: rating-projection delta + playoff field accuracy
# ---------------------------------------------------------------------------
def test_rating_projection_delta_basic():
    proj = {1: 100.0, 2: 90.0, 3: 80.0}
    actual = {1: 99.0, 2: 92.0, 3: 80.0, 99: 50.0}  # 99 ignored (not in proj)
    out = rating_projection_delta(proj, actual)
    assert out["n"] == 3
    assert out["mean_abs_delta"] == pytest.approx((1.0 + 2.0 + 0.0) / 3)
    assert out["median_abs_delta"] == pytest.approx(1.0)


def test_rating_projection_delta_no_overlap():
    out = rating_projection_delta({1: 1.0}, {2: 2.0})
    assert out == {"mean_abs_delta": 0.0, "median_abs_delta": 0.0, "n": 0}


def test_playoff_field_accuracy_placeholder():
    # Stub returns hit-rate when both sides are non-empty
    assert playoff_field_accuracy(set(), {1, 2}) == 0.0
    assert playoff_field_accuracy({1, 2}, set()) == 0.0
    assert playoff_field_accuracy({1, 2, 3}, {1, 2, 99}) == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# predictor
# ---------------------------------------------------------------------------
def test_predict_game_uses_v2():
    config = PredictionConfig()
    direct = win_probability_v2(10.0, 5.0, config, sport="Football")
    via = predict_game(10.0, 5.0, "Football", config)
    assert direct == pytest.approx(via)


def test_predict_game_sport_specific_hfa():
    cfg = PredictionConfig(home_advantage_by_sport={"Football": 2.0})
    # Same matchup, but Football HFA overrides; Volleyball uses the default
    p_football = predict_game(0.0, 0.0, "Football", cfg)
    p_volleyball = predict_game(0.0, 0.0, "Volleyball", cfg)
    assert p_football > p_volleyball


# ---------------------------------------------------------------------------
# runner smoke (with fake Supabase client)
# ---------------------------------------------------------------------------
class _FakeQuery:
    """Minimal chainable supabase-py builder for tests.

    Mirrors the subset of methods the validator uses: .select, .eq, .in_,
    .range, .order, .limit, .delete, .insert, .execute.
    """

    def __init__(self, fake_db: dict, table: str):
        self._fake_db = fake_db
        self._table = table
        self._filters: list[tuple[str, str, object]] = []
        self._range: tuple[int, int] | None = None
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None
        self._insert_payload: list[dict] | None = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, k, v):
        self._filters.append(("eq", k, v))
        return self

    def in_(self, k, v):
        self._filters.append(("in_", k, list(v)))
        return self

    def ilike(self, k, v):
        self._filters.append(("ilike", k, v))
        return self

    def range(self, lo, hi):
        self._range = (lo, hi)
        return self

    def order(self, key, desc=False):
        self._order = (key, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, payload):
        self._insert_payload = list(payload)
        return self

    def delete(self):
        self._filters.append(("__delete__", "", None))
        return self

    def execute(self):
        if self._insert_payload is not None:
            self._fake_db.setdefault(self._table, []).extend(self._insert_payload)
            data = list(self._insert_payload)
            self._insert_payload = None
            return type("Res", (), {"data": data})()
        rows = list(self._fake_db.get(self._table, []))
        is_delete = any(f[0] == "__delete__" for f in self._filters)
        for op, key, value in self._filters:
            if op == "__delete__":
                continue
            if op == "eq":
                rows = [r for r in rows if r.get(key) == value]
            elif op == "in_":
                rows = [r for r in rows if r.get(key) in value]
            elif op == "ilike":
                # crude case-insensitive equality
                rows = [r for r in rows if str(r.get(key, "")).lower() == str(value).lower()]
        if self._order:
            key, desc = self._order
            rows = sorted(rows, key=lambda r: (r.get(key) is None, r.get(key)), reverse=desc)
        if self._range:
            lo, hi = self._range
            rows = rows[lo : hi + 1]
        if self._limit:
            rows = rows[: self._limit]
        if is_delete:
            # Remove these rows from the fake db
            remaining = []
            removed_ids = {id(r) for r in rows}
            for r in self._fake_db.get(self._table, []):
                if id(r) not in removed_ids:
                    remaining.append(r)
            self._fake_db[self._table] = remaining
        return type("Res", (), {"data": rows})()


class _FakeSupabase:
    def __init__(self, db: dict):
        self._db = db

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self._db, name)


def _build_fake_db() -> dict:
    """Two sports (Football + Volleyball), one season (2025), 10 games each."""
    db: dict = {
        "sports": [{"id": 1, "name": "Football"}],
        "schools": [],
        "teams": [],
        "games": [],
        "power_ratings": [],
        "game_predictions": [],
    }
    # 4 schools / 4 teams in Football 2025
    for i in range(1, 5):
        db["schools"].append({"id": i, "name": f"School{i}", "classification": "5A"})
        db["teams"].append({
            "id": i, "school_id": i, "division": "I", "select_status": "non-select",
            "season_year": 2025, "sport_id": 1,
        })
    # Engine ratings for weeks 1..5
    for tid in range(1, 5):
        for w in range(1, 6):
            db["power_ratings"].append({
                "team_id": tid, "week_number": w, "season_year": 2025,
                "power_rating": 100.0 - 5.0 * (tid - 1) + 0.5 * w, "source": "engine",
            })
    # Prior-season finals (week 12 in 2024 for the same school_ids/sport)
    for tid_prior in range(101, 105):
        # Prior-season teams - use distinct ids; school_id maps to current-season same school
        db["teams"].append({
            "id": tid_prior, "school_id": tid_prior - 100, "division": "I",
            "select_status": "non-select", "season_year": 2024, "sport_id": 1,
        })
        db["power_ratings"].append({
            "team_id": tid_prior, "week_number": 12, "season_year": 2024,
            "power_rating": 95.0, "source": "engine",
        })
    # 4 games: 1 in week 1 (cold-start), 3 in week 2+
    db["games"] = [
        {
            "id": 1001, "home_team_id": 1, "away_team_id": 2,
            "home_score": 28, "away_score": 14, "week_number": 1, "status": "final",
            "is_out_of_state": False, "game_date": "2025-08-29", "sport_id": 1,
            "season_year": 2025,
        },
        {
            "id": 1002, "home_team_id": 3, "away_team_id": 4,
            "home_score": 21, "away_score": 35, "week_number": 2, "status": "final",
            "is_out_of_state": False, "game_date": "2025-09-05", "sport_id": 1,
            "season_year": 2025,
        },
        {
            "id": 1003, "home_team_id": 1, "away_team_id": 3,
            "home_score": 7, "away_score": 24, "week_number": 3, "status": "final",
            "is_out_of_state": False, "game_date": "2025-09-12", "sport_id": 1,
            "season_year": 2025,
        },
        {
            "id": 1004, "home_team_id": 2, "away_team_id": 4,
            "home_score": 17, "away_score": 17, "week_number": 4, "status": "final",
            "is_out_of_state": False, "game_date": "2025-09-19", "sport_id": 1,
            "season_year": 2025,
        },
    ]
    return db


def test_runner_smoke(tmp_path: Path):
    db = _build_fake_db()
    sb = _FakeSupabase(db)
    config = PredictionConfig.baseline()

    result = run_validation(
        config=config,
        config_label="baseline-test",
        sports=["Football"],
        seasons=[2025],
        holdout_seasons=[2025],
        write_to_db=True,
        output_dir=tmp_path,
        n_bootstrap=10,
        supabase_client=sb,
        now_fn=lambda: datetime(2026, 1, 1, 12, 0, 0),
    )

    # Shape checks
    assert result.config_label == "baseline-test"
    assert result.n_predictions == 4
    assert "Football" in result.sports
    football = result.sports["Football"]
    assert football["n_holdout"] == 4
    assert "game_winner_acc" in football["holdout"]
    assert "brier" in football["holdout"]
    assert "reliability_bins" in football["holdout"]
    assert len(football["holdout"]["reliability_bins"]) == 10

    # Predictions written to DB
    assert len(db["game_predictions"]) == 4
    for row in db["game_predictions"]:
        assert row["config_label"] == "baseline-test"
        assert row["run_id"] == result.run_id
        assert row["simulation_id"] is None
        assert 0.0 <= row["home_win_probability"] <= 1.0

    # Artifacts written
    assert result.output_dir is not None
    summary_path = result.output_dir / "summary.json"
    csv_path = result.output_dir / "per_game_log.csv"
    md_path = result.output_dir / "report.md"
    assert summary_path.exists()
    assert csv_path.exists()
    assert md_path.exists()
    payload = json.loads(summary_path.read_text())
    assert payload["config"] == "baseline-test"
    assert payload["n_predictions"] == 4

    # CSV column shape
    with csv_path.open() as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    assert "game_id" in header
    assert "actual_winner" in header
    assert len(rows) == 4


def test_runner_no_write(tmp_path: Path):
    db = _build_fake_db()
    sb = _FakeSupabase(db)
    config = PredictionConfig.baseline()
    result = run_validation(
        config=config,
        config_label="baseline-test",
        sports=["Football"],
        seasons=[2025],
        holdout_seasons=[2025],
        write_to_db=False,
        output_dir=tmp_path,
        n_bootstrap=10,
        supabase_client=sb,
        now_fn=lambda: datetime(2026, 1, 1, 12, 0, 0),
    )
    assert result.n_predictions == 4
    assert db["game_predictions"] == []


def test_runner_handles_cold_start(tmp_path: Path):
    db = _build_fake_db()
    sb = _FakeSupabase(db)
    config = PredictionConfig.baseline()
    result = run_validation(
        config=config,
        config_label="baseline-test",
        sports=["Football"],
        seasons=[2025],
        holdout_seasons=[2025],
        write_to_db=False,
        output_dir=tmp_path,
        n_bootstrap=10,
        supabase_client=sb,
        now_fn=lambda: datetime(2026, 1, 1, 12, 0, 0),
    )
    # Week 1 game (id=1001) should produce two cold-start sides
    assert result.n_cold_start >= 1


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------
def test_parse_sports_all_and_single():
    assert "Football" in _parse_sports("all")
    assert _parse_sports("football") == ["Football"]
    assert _parse_sports("football,volleyball") == ["Football", "Volleyball"]


def test_parse_sports_unknown_raises():
    with pytest.raises(SystemExit):
        _parse_sports("badminton")


def test_parse_seasons_range_and_csv():
    assert _parse_seasons("2021-2025") == [2021, 2022, 2023, 2024, 2025]
    assert _parse_seasons("2025") == [2025]
    assert _parse_seasons("2021,2024") == [2021, 2024]
