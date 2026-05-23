"""Top-level orchestration for validator runs.

``run_validation`` is the entry point. It:

1. For each (sport, season): loads inputs, derives pre-game ratings, calls
   :func:`predict_game` for every game, and packs the result into
   :class:`PredictionRecord` instances.
2. Computes per-(sport, train/holdout) metrics with bootstrap CIs.
3. Optionally writes the predictions to ``game_predictions`` (one row per
   game per run, tagged with ``config_label`` + ``run_id``).
4. Writes ``summary.json`` + ``per_game_log.csv`` + ``reliability_plot.png``
   + ``report.md`` to ``output_dir/<config_label>/<YYYY-MM-DD-HHMM>/``.

Network/DB I/O is isolated behind a tiny "supabase_client_factory" so the
unit tests can swap in an in-memory fake without going through the network.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.prediction.config import PredictionConfig

from .data import (
    ALL_SPORTS,
    RunInputs,
    load_run_inputs,
    load_sports_map,
    load_teams_with_schools,
)
from .metrics import (
    bootstrap_ci,
    brier_score,
    game_winner_accuracy,
    rating_projection_delta,
    reliability_bins,
)
from .predictor import PredictionRecord, predict_game

DEFAULT_SEASONS: list[int] = [2021, 2022, 2023, 2024, 2025]
DEFAULT_HOLDOUT: list[int] = [2025]


@dataclass
class RunResult:
    """Aggregated output of one :func:`run_validation` call."""

    config_label: str
    run_id: str
    timestamp: datetime
    sports: dict[str, dict] = field(default_factory=dict)
    overall: dict = field(default_factory=dict)
    output_dir: Path | None = None
    n_predictions: int = 0
    n_cold_start: int = 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run_validation(
    config: PredictionConfig,
    config_label: str = "baseline",
    sports: list[str] | None = None,
    seasons: list[int] | None = None,
    holdout_seasons: list[int] | None = None,
    write_to_db: bool = True,
    output_dir: Path | str = "reports",
    n_bootstrap: int = 1000,
    seed: int = 42,
    supabase_client: Any | None = None,
    supabase_client_factory: Callable[[], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    run_id: str | None = None,
) -> RunResult:
    """Run validator across ``sports x seasons`` for one ``PredictionConfig``.

    ``sports=None`` -> all 8. ``seasons=None`` -> 2021-2025.
    ``holdout_seasons=None`` -> [2025]. Holdout seasons are aggregated
    separately from train seasons in the per-sport result blocks.

    Pass ``supabase_client`` to inject an already-built client (used by
    tests). Otherwise ``supabase_client_factory`` is invoked; if not given,
    a real Supabase REST client is built from env vars.
    """
    sports = list(sports) if sports else list(ALL_SPORTS)
    seasons = list(seasons) if seasons else list(DEFAULT_SEASONS)
    holdout_seasons = list(holdout_seasons) if holdout_seasons else list(DEFAULT_HOLDOUT)
    now = (now_fn or datetime.utcnow)()
    # Standard 36-char UUID form (with dashes) — supabase-py/postgres-uuid behavior
    # on undashed hex is environment-dependent; use the canonical string form.
    rid = run_id or str(uuid.uuid4())

    if supabase_client is None:
        if supabase_client_factory is None:
            supabase_client_factory = _default_supabase_client_factory
        supabase_client = supabase_client_factory()

    sb = supabase_client

    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): sid for sid, n in sports_map.items()}
    teams = load_teams_with_schools(sb)

    all_predictions: list[PredictionRecord] = []
    per_sport_predictions: dict[str, list[PredictionRecord]] = {s: [] for s in sports}
    n_cold_start = 0

    for sport_name in sports:
        sid = name_to_id.get(sport_name.lower())
        if sid is None:
            continue
        for season in seasons:
            inputs = load_run_inputs(sb, sid, sport_name, season, teams=teams)
            preds = _predict_inputs(inputs, config)
            per_sport_predictions[sport_name].extend(preds)
            all_predictions.extend(preds)
            n_cold_start += sum(1 for p in preds if p.home_cold_start or p.away_cold_start)

    # --- per-sport metric blocks ---
    sports_block: dict[str, dict] = {}
    for sport_name, preds in per_sport_predictions.items():
        train = [p for p in preds if p.season_year not in holdout_seasons]
        hold = [p for p in preds if p.season_year in holdout_seasons]
        sports_block[sport_name] = {
            "train": _metric_block(train),
            "holdout": _metric_block(hold),
            "ci_95": _bootstrap_block(train, n_resamples=n_bootstrap, seed=seed),
            "n_train": len(train),
            "n_holdout": len(hold),
        }

    train_all = [p for p in all_predictions if p.season_year not in holdout_seasons]
    hold_all = [p for p in all_predictions if p.season_year in holdout_seasons]
    overall = {
        "train": _metric_block(train_all),
        "holdout": _metric_block(hold_all),
        "ci_95": _bootstrap_block(train_all, n_resamples=n_bootstrap, seed=seed),
        "n_train": len(train_all),
        "n_holdout": len(hold_all),
    }

    result = RunResult(
        config_label=config_label,
        run_id=rid,
        timestamp=now,
        sports=sports_block,
        overall=overall,
        n_predictions=len(all_predictions),
        n_cold_start=n_cold_start,
    )

    # --- DB write ---
    if write_to_db and all_predictions:
        _write_predictions_to_db(sb, all_predictions, config_label, rid)

    # --- on-disk artifacts ---
    out_root = Path(output_dir)
    run_dir = out_root / config_label / now.strftime("%Y-%m-%d-%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)
    result.output_dir = run_dir

    # Lazy imports — these touch matplotlib which is dev-optional.
    from . import report as _report

    _report.write_summary_json(run_dir / "summary.json", result)
    _report.write_per_game_log_csv(run_dir / "per_game_log.csv", all_predictions, rid)
    try:
        _report.write_reliability_plot(run_dir / "reliability_plot.png", all_predictions)
    except ImportError:
        # matplotlib not installed — fine for smoke tests; skip the PNG
        pass
    _report.write_markdown_report(run_dir / "report.md", result)

    return result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _default_supabase_client_factory():  # pragma: no cover - thin wrapper
    """Build a real Supabase client from env. Lazy import to keep tests light."""
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "https://ywlaekkxkwfznwuupggi.supabase.co")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not key:
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY env var is required to run validator against live DB"
        )
    return create_client(url, key)


def _resolve_pregame_rating(
    team_id: int,
    week_number: int,
    division: str | None,
    engine_ratings: dict[tuple[int, int], float],
    prior_finals: dict[int, float],
    division_medians: dict[str, float],
) -> tuple[float, bool]:
    """Return (rating, is_cold_start) for ``team_id`` going into ``week_number``.

    Lookup order:
      1. Engine rating for the prior week (W-1).
      2. Prior season's end-of-season engine rating (cold start).
      3. Median of division's prior-season ratings (cold start).
      4. Global default 0.0 (cold start) — only hit if the season has zero
         prior-season data, which would indicate a corrupt input.
    """
    if week_number > 1:
        r = engine_ratings.get((team_id, week_number - 1))
        if r is not None:
            return float(r), False
    # cold-start path
    r = prior_finals.get(team_id)
    if r is not None:
        return float(r), True
    if division and division in division_medians:
        return float(division_medians[division]), True
    return 0.0, True


def _predict_inputs(inputs: RunInputs, config: PredictionConfig) -> list[PredictionRecord]:
    preds: list[PredictionRecord] = []
    for g in inputs.games:
        w = int(g["_engine_week"])
        h_team = g["home_team_id"]
        a_team = g["away_team_id"]
        h_div = inputs.teams.get(h_team, {}).get("division")
        a_div = inputs.teams.get(a_team, {}).get("division")

        h_rating, h_cold = _resolve_pregame_rating(
            h_team, w, h_div, inputs.engine_ratings, inputs.prior_finals,
            inputs.division_prior_medians,
        )
        a_rating, a_cold = _resolve_pregame_rating(
            a_team, w, a_div, inputs.engine_ratings, inputs.prior_finals,
            inputs.division_prior_medians,
        )
        p_home = predict_game(h_rating, a_rating, inputs.sport_name, config)

        hs = g.get("home_score")
        as_ = g.get("away_score")
        actual_home_won: bool | None
        if hs is None or as_ is None:
            actual_home_won = None
        else:
            actual_home_won = bool(hs > as_)

        preds.append(PredictionRecord(
            game_id=int(g["id"]),
            home_team_id=int(h_team),
            away_team_id=int(a_team),
            home_win_probability=float(p_home),
            predicted_home_score=None,
            predicted_away_score=None,
            predicted_spread=None,
            home_rating_pregame=float(h_rating),
            away_rating_pregame=float(a_rating),
            home_cold_start=bool(h_cold),
            away_cold_start=bool(a_cold),
            actual_home_won=actual_home_won,
            sport=inputs.sport_name,
            season_year=int(inputs.season_year),
            week_number=w,
        ))
    return preds


def _metric_block(preds: list[PredictionRecord]) -> dict:
    return {
        "game_winner_acc": game_winner_accuracy(preds),
        "brier": brier_score(preds),
        "reliability_bins": reliability_bins(preds, n_bins=10),
        "n_games": len(preds),
    }


def _bootstrap_block(
    preds: list[PredictionRecord], n_resamples: int, seed: int
) -> dict:
    if not preds:
        return {
            "game_winner_acc": [0.0, 0.0],
            "brier": [0.0, 0.0],
        }
    acc_lo, acc_hi = bootstrap_ci(
        game_winner_accuracy, preds, n_resamples=n_resamples, ci=0.95, seed=seed,
    )
    bri_lo, bri_hi = bootstrap_ci(
        brier_score, preds, n_resamples=n_resamples, ci=0.95, seed=seed + 1,
    )
    return {
        "game_winner_acc": [acc_lo, acc_hi],
        "brier": [bri_lo, bri_hi],
    }


def _write_predictions_to_db(
    sb,
    predictions: list[PredictionRecord],
    config_label: str,
    run_id: str,
) -> int:
    """INSERT one row per prediction into ``game_predictions``.

    ``simulation_id`` is left NULL (validator runs don't simulate);
    ``config_label`` + ``run_id`` (the new columns from the
    ``add_validator_columns_to_game_predictions`` migration) disambiguate
    rows across runs.
    """
    rows: list[dict] = []
    for p in predictions:
        rows.append({
            "game_id": p.game_id,
            "simulation_id": None,
            "config_label": config_label,
            "run_id": run_id,
            "home_win_probability": round(float(p.home_win_probability), 4),
            "predicted_home_score": (
                round(float(p.predicted_home_score), 2) if p.predicted_home_score is not None else None
            ),
            "predicted_away_score": (
                round(float(p.predicted_away_score), 2) if p.predicted_away_score is not None else None
            ),
            "predicted_spread": (
                round(float(p.predicted_spread), 2) if p.predicted_spread is not None else None
            ),
        })
    written = 0
    # Chunk inserts to stay well under REST payload limits
    for i in range(0, len(rows), 500):
        batch = rows[i : i + 500]
        sb.table("game_predictions").insert(batch).execute()
        written += len(batch)
    return written


# Used by report.py for the rating-projection-delta block. Exposed here so
# the runner controls the source-of-truth dict structures.
def aggregate_rating_projection_deltas(
    inputs_by_sport_season: dict[tuple[str, int], RunInputs],
) -> dict[str, dict]:
    """For each sport, compare end-of-season engine ratings with the
    "projected" rating (currently = pre-final-week engine rating).

    Stub for the spec's rating-projection metric; the validator returns the
    structure but doesn't surface a meaningful projection without the Phase-2
    simulation layer. Mean/median deltas computed here are still informative
    as a calibration baseline.
    """
    by_sport: dict[str, dict] = {}
    for (sport_name, _season), inputs in inputs_by_sport_season.items():
        projected: dict[int, float] = {}
        actual: dict[int, float] = inputs.end_of_season_engine_ratings
        # "projected" baseline: take rating at second-to-last week per team
        by_team_weeks: dict[int, list[tuple[int, float]]] = {}
        for (tid, w), r in inputs.engine_ratings.items():
            by_team_weeks.setdefault(tid, []).append((w, r))
        for tid, lst in by_team_weeks.items():
            if len(lst) < 2:
                continue
            lst.sort()
            projected[tid] = lst[-2][1]
        delta = rating_projection_delta(projected, actual)
        existing = by_sport.get(sport_name)
        if existing is None:
            by_sport[sport_name] = delta
        else:
            # Merge by weighting; for simplicity sum n's and take a weighted mean.
            total_n = existing["n"] + delta["n"]
            if total_n == 0:
                continue
            by_sport[sport_name] = {
                "mean_abs_delta": (
                    existing["mean_abs_delta"] * existing["n"]
                    + delta["mean_abs_delta"] * delta["n"]
                ) / total_n,
                "median_abs_delta": (existing["median_abs_delta"] + delta["median_abs_delta"]) / 2,
                "n": total_n,
            }
    return by_sport
