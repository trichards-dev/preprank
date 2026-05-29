"""Phase 2 walk-forward runner — fits v2 logistic-regression β per sport
on the train fold, predicts holdout with ``predict_game_v3(strict=True)``,
and applies the HALT-rules from Reese's 2026-05-26 Phase 2 sign-off.

Also exposes ``run_phase4a_hfa_ablation`` — fits BOTH the baseline (β₂
fitted) and the HFA-ablation (β₂=0) per sport, then runs the per-sport
paired-bootstrap CI + Benjamini-Hochberg FDR across the 8 sports per
Reese's 2026-05-26 evening Phase 4a scope.

Distinct from the v1 ``runner.run_validation`` path:

* v1 path (``runner._predict_inputs``) uses the additive-signal
  ``validator.predictor.predict_game`` with feature-flag config — frozen
  for back-compat.
* This module (Phase 2 v2 path) uses the fitted v2 model
  (``prediction.model.fit_sport`` + ``predict_game_v3(strict=True)``).
  Baseline = only β₀/β₁/β₂ identifiable (no Phase-4 features yet); the
  remaining β slots fit to ~0.

Per Reese 2026-05-26 sign-off conditions, this runner:

* Computes 1000-resample bootstrap CIs for accuracy + Brier
* Computes train/holdout accuracy gap and applies the < 0.005 gate
* Computes per-sport calibration slope/intercept
* Records ``selected_lambda_per_game`` per sport for audit
* HALTs if overall holdout acc > 0.73 with no clear feature-side explanation
  (the "Phase 1 leakage" guard — Phase 2 adds no features, so any jump that
  large is suspicious)
* Auto-promotes to Phase 4a-ready when overall Brier < 0.20 AND
  train/holdout gap < 0.005
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from engine.prediction.config import PredictionConfig
from engine.prediction.config import PredictionConfig as _PredictionConfig  # noqa: F401
from engine.prediction.features.log_margin import precompute_team_week_log_margins
from engine.prediction.features.massey_od import precompute_team_week_massey_od
from engine.prediction.features.recent_form import precompute_team_week_form
from engine.prediction.model import (
    COEF_NAMES,
    FitResult,
    GameState,
    GameTrainingRow,
    MissingCoefficientsError,
    fit_sport,
    predict_game_v3,
)

from .data import (
    ALL_SPORTS,
    RunInputs,
    load_run_inputs,
    load_sports_map,
    load_teams_with_schools,
)
from .fdr import benjamini_hochberg
from .metrics import (
    bootstrap_ci,
    brier_score,
    game_winner_accuracy,
    reliability_bins,
)
from .predictor import PredictionRecord
from .runner import _resolve_pregame_rating


# ---------------------------------------------------------------------------
# HALT-rule thresholds (from Reese 2026-05-26 Phase 2 sign-off conditions)
# ---------------------------------------------------------------------------
HALT_ACCURACY_UPPER_BOUND = 0.73
"""If overall holdout acc exceeds this without a feature-side explanation,
HALT and audit for leakage. Baseline (no features) jumping above 0.73
would repeat the same Phase-1 contamination pattern."""

MAX_TRAIN_HOLDOUT_GAP = 0.005
"""Overall train-acc minus holdout-acc must stay within this band."""

AUTO_PROMOTE_BRIER_CEILING = 0.20
"""Overall holdout Brier below this AND gap < MAX_TRAIN_HOLDOUT_GAP
auto-promotes to Phase 4a without additional sign-off."""


@dataclass
class SportPhase2Result:
    """Per-sport result block for one Phase 2 run."""

    sport: str
    fit: FitResult
    n_train: int
    n_holdout: int
    train_accuracy: float
    train_brier: float
    holdout_accuracy: float
    holdout_brier: float
    holdout_accuracy_ci: tuple[float, float]
    holdout_brier_ci: tuple[float, float]
    calibration_slope: float
    calibration_intercept: float
    train_holdout_gap: float
    halt_triggers: list[str] = field(default_factory=list)


@dataclass
class Phase2Result:
    """Aggregated output of one walk-forward Phase 2 baseline run."""

    config_label: str
    run_id: str
    timestamp: datetime
    train_seasons: list[int]
    holdout_seasons: list[int]
    drop_seasons: list[int]
    sports: dict[str, SportPhase2Result] = field(default_factory=dict)
    overall_train_accuracy: float = 0.0
    overall_train_brier: float = 0.0
    overall_holdout_accuracy: float = 0.0
    overall_holdout_brier: float = 0.0
    overall_holdout_accuracy_ci: tuple[float, float] = (0.0, 0.0)
    overall_holdout_brier_ci: tuple[float, float] = (0.0, 0.0)
    overall_train_holdout_gap: float = 0.0
    n_train: int = 0
    n_holdout: int = 0
    halt_triggers: list[str] = field(default_factory=list)
    auto_promote_to_phase4a: bool = False
    fit_warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Build per-game training rows from RunInputs
# ---------------------------------------------------------------------------
def _build_training_rows(
    inputs: RunInputs,
    *,
    prior_year_finals_for_carryover: dict[int, float] | None = None,
    recent_form_signals: dict[tuple[int, int], float] | None = None,
    log_margin_signals: dict[tuple[int, int], float] | None = None,
    massey_od_signals: dict[tuple[int, int], tuple[float, float]] | None = None,
) -> list[GameTrainingRow]:
    """Turn one sport-season's RunInputs into GameTrainingRow list.

    Phase 2 baseline: only Δrating + HFA are signals; margin/off/def/pyc
    signals are 0 because Phase 4 hasn't landed. Prior-year carryover is
    populated when available for weeks 1-3 (so β₅ is identifiable on the
    fold, though it's expected to fit near 0 at baseline).

    Phase 4b: caller passes ``recent_form_signals`` mapping
    ``(team_id, week)`` to the recency-weighted capped-margin signal
    through that week. The runner looks up ``W-1`` for each game in
    week ``W`` to get the pre-game signal.

    Phase 4c: caller passes ``log_margin_signals`` mapping
    ``(team_id, week)`` to the cumulative log-compressed margin signal
    through that week. Looked up at ``W-1`` for each predicted game.
    Populates ``GameState.margin_signal`` which feeds β₃ in the model.
    """
    rows: list[GameTrainingRow] = []
    prior = prior_year_finals_for_carryover or inputs.prior_finals
    form = recent_form_signals or {}
    log_marg = log_margin_signals or {}
    massey = massey_od_signals or {}
    for g in inputs.games:
        w = int(g["_engine_week"])
        h_team = g["home_team_id"]
        a_team = g["away_team_id"]
        h_div = inputs.teams.get(h_team, {}).get("division")
        a_div = inputs.teams.get(a_team, {}).get("division")

        h_rating, _ = _resolve_pregame_rating(
            h_team, w, h_div, inputs.engine_ratings,
            inputs.prior_finals, inputs.division_prior_medians,
        )
        a_rating, _ = _resolve_pregame_rating(
            a_team, w, a_div, inputs.engine_ratings,
            inputs.prior_finals, inputs.division_prior_medians,
        )

        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue  # incomplete games can't train

        is_neutral = bool(g.get("neutral_site", False))

        h_massey = massey.get((h_team, w - 1), (0.0, 0.0))
        a_massey = massey.get((a_team, w - 1), (0.0, 0.0))
        home_state = GameState(
            rating=h_rating,
            margin_signal=float(log_marg.get((h_team, w - 1), 0.0)),
            off_signal=float(h_massey[0]),
            def_signal=float(h_massey[1]),
            prior_year_rating=prior.get(h_team),
            recent_form_signal=float(form.get((h_team, w - 1), 0.0)),
            week_number=w,
            season_year=inputs.season_year,
        )
        away_state = GameState(
            rating=a_rating,
            margin_signal=float(log_marg.get((a_team, w - 1), 0.0)),
            off_signal=float(a_massey[0]),
            def_signal=float(a_massey[1]),
            prior_year_rating=prior.get(a_team),
            recent_form_signal=float(form.get((a_team, w - 1), 0.0)),
            week_number=w,
            season_year=inputs.season_year,
        )
        rows.append(
            GameTrainingRow(
                home_state=home_state,
                away_state=away_state,
                is_neutral_site=is_neutral,
                is_mercy=False,  # Phase 4c will populate this; Phase 2 baseline doesn't use it
                home_won=bool(hs > as_),
            )
        )
    return rows


def _predict_rows(
    rows: list[GameTrainingRow],
    sport: str,
    config: PredictionConfig,
) -> list[PredictionRecord]:
    """Wrap fitted-model predictions in PredictionRecord for metric reuse."""
    preds: list[PredictionRecord] = []
    for row in rows:
        p_home = predict_game_v3(
            row.home_state, row.away_state,
            sport, config,
            is_neutral_site=row.is_neutral_site,
            strict=True,
        )
        preds.append(
            PredictionRecord(
                game_id=0,
                home_team_id=0,
                away_team_id=0,
                home_win_probability=float(p_home),
                predicted_home_score=None,
                predicted_away_score=None,
                predicted_spread=None,
                home_rating_pregame=row.home_state.rating,
                away_rating_pregame=row.away_state.rating,
                home_cold_start=row.home_state.prior_year_rating is None,
                away_cold_start=row.away_state.prior_year_rating is None,
                actual_home_won=row.home_won,
                sport=sport,
                season_year=row.home_state.season_year,
                week_number=row.home_state.week_number,
            )
        )
    return preds


def _calibration_slope_intercept(preds: list[PredictionRecord]) -> tuple[float, float]:
    """OLS slope/intercept of (predicted, observed) — quick calibration health check."""
    import numpy as np

    if not preds:
        return (1.0, 0.0)
    x = np.array([p.home_win_probability for p in preds], dtype=np.float64)
    y = np.array([1.0 if p.actual_home_won else 0.0 for p in preds], dtype=np.float64)
    # Avoid degenerate case
    if float(np.std(x)) < 1e-9:
        return (0.0, float(np.mean(y)))
    cov = float(np.mean((x - x.mean()) * (y - y.mean())))
    slope = cov / float(np.var(x))
    intercept = float(y.mean() - slope * x.mean())
    return (slope, intercept)


# ---------------------------------------------------------------------------
# HALT-rule evaluation
# ---------------------------------------------------------------------------
def _apply_halt_rules(result: Phase2Result) -> None:
    """Mutate ``result`` with halt_triggers + auto_promote_to_phase4a per
    Reese 2026-05-26 Phase 2 sign-off conditions.

    The train/holdout gap is read **bidirectionally** (`abs(gap) > 0.005`):
    overfitting (positive gap) and "easy holdout" (negative gap) are both
    flags. A symmetric bound catches both Phase-1-style contamination
    AND distribution shifts where the holdout happens to be easier than
    the train fold.
    """
    abs_gap = abs(result.overall_train_holdout_gap)

    if result.overall_holdout_accuracy > HALT_ACCURACY_UPPER_BOUND:
        result.halt_triggers.append(
            f"overall holdout accuracy {result.overall_holdout_accuracy:.4f} > "
            f"{HALT_ACCURACY_UPPER_BOUND:.2f} without feature-side explanation. "
            "HALT and audit for leakage before Phase 4a starts (mirrors Phase 1 contamination pattern)."
        )

    if abs_gap > MAX_TRAIN_HOLDOUT_GAP:
        result.halt_triggers.append(
            f"overall |train - holdout| gap {result.overall_train_holdout_gap:+.4f} "
            f"(|·|={abs_gap:.4f}) exceeds {MAX_TRAIN_HOLDOUT_GAP:.4f}. "
            "HALT and audit: positive gap = overfit; negative gap = holdout easier than train."
        )

    # Auto-promote only when there are no triggers AND both conditions are met
    if (
        not result.halt_triggers
        and result.overall_holdout_brier < AUTO_PROMOTE_BRIER_CEILING
        and abs_gap < MAX_TRAIN_HOLDOUT_GAP
    ):
        result.auto_promote_to_phase4a = True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run_phase2_baseline(
    *,
    train_seasons: list[int],
    holdout_seasons: list[int],
    drop_seasons: list[int] | None = None,
    sports: list[str] | None = None,
    config_label: str = "wf-baseline-v2-fitted",
    n_bootstrap: int = 1000,
    seed: int = 42,
    supabase_client: Any | None = None,
    supabase_client_factory: Callable[[], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    run_id: str | None = None,
) -> Phase2Result:
    """Fit + evaluate Phase 2 baseline. See module docstring."""
    drop_seasons = list(drop_seasons or [])
    sports = list(sports) if sports else list(ALL_SPORTS)
    now = (now_fn or datetime.utcnow)()
    rid = run_id or str(uuid.uuid4())

    if supabase_client is None:
        if supabase_client_factory is None:
            from .runner import _default_supabase_client_factory

            supabase_client_factory = _default_supabase_client_factory
        supabase_client = supabase_client_factory()
    sb = supabase_client

    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): sid for sid, n in sports_map.items()}
    teams = load_teams_with_schools(sb)

    # Load + bucket inputs by sport. Drop seasons removed entirely; train
    # and holdout kept and tagged.
    inputs_by_sport: dict[str, list[RunInputs]] = {}
    for sport_name in sports:
        sid = name_to_id.get(sport_name.lower())
        if sid is None:
            continue
        inputs_by_sport[sport_name] = []
        for season in train_seasons + holdout_seasons:
            if season in drop_seasons:
                continue
            inputs_by_sport[sport_name].append(
                load_run_inputs(sb, sid, sport_name, season, teams=teams)
            )

    result = Phase2Result(
        config_label=config_label,
        run_id=rid,
        timestamp=now,
        train_seasons=list(train_seasons),
        holdout_seasons=list(holdout_seasons),
        drop_seasons=list(drop_seasons),
    )

    config = PredictionConfig()
    all_train_preds: list[PredictionRecord] = []
    all_hold_preds: list[PredictionRecord] = []

    for sport_name, inputs_list in inputs_by_sport.items():
        train_rows: list[GameTrainingRow] = []
        hold_rows: list[GameTrainingRow] = []
        for inputs in inputs_list:
            rows = _build_training_rows(inputs)
            if inputs.season_year in holdout_seasons:
                hold_rows.extend(rows)
            else:
                train_rows.extend(rows)

        if not train_rows:
            result.fit_warnings.append(f"{sport_name}: no train rows — skipped")
            continue

        try:
            fit = fit_sport(sport_name, train_rows, cv_seed=seed)
        except Exception as e:
            result.fit_warnings.append(f"{sport_name}: fit_sport raised {type(e).__name__}: {e}")
            continue

        if not fit.converged:
            result.fit_warnings.append(
                f"{sport_name}: fit did not converge cleanly (iters={fit.iterations}, "
                f"message={fit.message!r})"
            )

        config.model_coefficients_by_sport[sport_name] = fit.coefficients

        train_preds = _predict_rows(train_rows, sport_name, config)
        hold_preds = _predict_rows(hold_rows, sport_name, config)

        train_acc = game_winner_accuracy(train_preds)
        train_bri = brier_score(train_preds)
        hold_acc = game_winner_accuracy(hold_preds) if hold_preds else 0.0
        hold_bri = brier_score(hold_preds) if hold_preds else 0.0

        acc_ci = (
            bootstrap_ci(game_winner_accuracy, hold_preds,
                         n_resamples=n_bootstrap, ci=0.95, seed=seed)
            if hold_preds else (0.0, 0.0)
        )
        bri_ci = (
            bootstrap_ci(brier_score, hold_preds,
                         n_resamples=n_bootstrap, ci=0.95, seed=seed + 1)
            if hold_preds else (0.0, 0.0)
        )
        slope, intercept = _calibration_slope_intercept(hold_preds)

        sport_result = SportPhase2Result(
            sport=sport_name,
            fit=fit,
            n_train=len(train_rows),
            n_holdout=len(hold_rows),
            train_accuracy=train_acc,
            train_brier=train_bri,
            holdout_accuracy=hold_acc,
            holdout_brier=hold_bri,
            holdout_accuracy_ci=acc_ci,
            holdout_brier_ci=bri_ci,
            calibration_slope=slope,
            calibration_intercept=intercept,
            train_holdout_gap=train_acc - hold_acc,
        )
        result.sports[sport_name] = sport_result
        all_train_preds.extend(train_preds)
        all_hold_preds.extend(hold_preds)

    # Overall metrics
    if all_train_preds:
        result.overall_train_accuracy = game_winner_accuracy(all_train_preds)
        result.overall_train_brier = brier_score(all_train_preds)
        result.n_train = len(all_train_preds)
    if all_hold_preds:
        result.overall_holdout_accuracy = game_winner_accuracy(all_hold_preds)
        result.overall_holdout_brier = brier_score(all_hold_preds)
        result.overall_holdout_accuracy_ci = bootstrap_ci(
            game_winner_accuracy, all_hold_preds,
            n_resamples=n_bootstrap, ci=0.95, seed=seed,
        )
        result.overall_holdout_brier_ci = bootstrap_ci(
            brier_score, all_hold_preds,
            n_resamples=n_bootstrap, ci=0.95, seed=seed + 1,
        )
        result.n_holdout = len(all_hold_preds)

    result.overall_train_holdout_gap = (
        result.overall_train_accuracy - result.overall_holdout_accuracy
    )

    _apply_halt_rules(result)
    return result


# ---------------------------------------------------------------------------
# Phase 4a — per-sport HFA ablation
# ---------------------------------------------------------------------------
@dataclass
class SportPhase4aResult:
    """Per-sport result block for Phase 4a HFA ablation.

    Lift metrics compute as (baseline - ablation): positive lift means
    the baseline (with per-sport β₂) outperforms the ablation (β₂=0).
    """

    sport: str
    fit_baseline: FitResult
    fit_ablation: FitResult
    n_holdout: int
    baseline_accuracy: float
    ablation_accuracy: float
    accuracy_lift: float
    accuracy_lift_ci: tuple[float, float]
    baseline_brier: float
    ablation_brier: float
    brier_lift: float                       # ablation - baseline (positive = baseline better)
    brier_lift_ci: tuple[float, float]
    p_value_one_sided: float                # P(lift <= 0) from bootstrap; one-sided
    significant_after_fdr: bool = False


@dataclass
class Phase4aResult:
    """Aggregated output of one Phase 4a HFA-ablation run."""

    config_label: str
    run_id: str
    timestamp: datetime
    train_seasons: list[int]
    holdout_seasons: list[int]
    drop_seasons: list[int]
    sports: dict[str, SportPhase4aResult] = field(default_factory=dict)
    n_significant_after_fdr: int = 0
    fit_warnings: list[str] = field(default_factory=list)


def _paired_bootstrap_lift(
    baseline_preds: list[PredictionRecord],
    ablation_preds: list[PredictionRecord],
    *,
    n_resamples: int,
    seed: int,
    ci: float = 0.95,
) -> tuple[float, tuple[float, float], float, tuple[float, float], float]:
    """Paired-bootstrap CI on per-game (acc, brier) lift + one-sided p-value
    for the accuracy lift.

    Returns (acc_lift, acc_ci, brier_lift, brier_ci, p_one_sided).

    p_one_sided = fraction of bootstrap replicates where acc_lift <= 0.
    Tests null hypothesis "baseline is no better than ablation in accuracy".
    """
    import numpy as np

    assert len(baseline_preds) == len(ablation_preds)
    n = len(baseline_preds)
    if n == 0:
        return (0.0, (0.0, 0.0), 0.0, (0.0, 0.0), 1.0)

    # Per-game correctness flags
    b_correct = np.array([
        1.0 if (p.home_win_probability > 0.5) == bool(p.actual_home_won) else 0.0
        for p in baseline_preds
    ], dtype=np.float64)
    a_correct = np.array([
        1.0 if (p.home_win_probability > 0.5) == bool(p.actual_home_won) else 0.0
        for p in ablation_preds
    ], dtype=np.float64)
    y = np.array([1.0 if p.actual_home_won else 0.0 for p in baseline_preds], dtype=np.float64)
    b_p = np.array([p.home_win_probability for p in baseline_preds], dtype=np.float64)
    a_p = np.array([p.home_win_probability for p in ablation_preds], dtype=np.float64)
    b_brier_g = (b_p - y) ** 2
    a_brier_g = (a_p - y) ** 2

    acc_lift = float(b_correct.mean() - a_correct.mean())
    brier_lift = float(a_brier_g.mean() - b_brier_g.mean())  # positive = baseline better

    rng = np.random.default_rng(seed)
    acc_replicates = np.empty(n_resamples, dtype=np.float64)
    brier_replicates = np.empty(n_resamples, dtype=np.float64)
    for r in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        acc_replicates[r] = float(b_correct[idx].mean() - a_correct[idx].mean())
        brier_replicates[r] = float(a_brier_g[idx].mean() - b_brier_g[idx].mean())

    lo_q = (1 - ci) / 2
    hi_q = 1 - lo_q
    acc_ci = (float(np.quantile(acc_replicates, lo_q)),
              float(np.quantile(acc_replicates, hi_q)))
    brier_ci = (float(np.quantile(brier_replicates, lo_q)),
                float(np.quantile(brier_replicates, hi_q)))
    p_one_sided = float((acc_replicates <= 0).mean())

    return (acc_lift, acc_ci, brier_lift, brier_ci, p_one_sided)


def run_phase4a_hfa_ablation(
    *,
    train_seasons: list[int],
    holdout_seasons: list[int],
    drop_seasons: list[int] | None = None,
    sports: list[str] | None = None,
    config_label: str = "wf-phase4a-hfa-ablation",
    n_bootstrap: int = 1000,
    seed: int = 42,
    fdr_alpha: float = 0.05,
    supabase_client: Any | None = None,
    supabase_client_factory: Callable[[], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    run_id: str | None = None,
) -> Phase4aResult:
    """Phase 4a: per-sport β₂ ablation vs baseline, paired-bootstrap + FDR.

    For each sport:
      1. Fit baseline (all 6 β free) on train fold
      2. Fit ablation (β₂=0 constrained) on train fold
      3. Predict holdout with both
      4. Paired-bootstrap CI on (accuracy_baseline - accuracy_ablation)
         and (brier_ablation - brier_baseline)
      5. One-sided p-value: P(acc_lift <= 0)

    After all sports: Benjamini-Hochberg FDR at α=``fdr_alpha`` over the
    8 per-sport p-values. A sport is "significantly lifted by per-sport
    HFA" iff both the p-value survives FDR AND the accuracy-lift CI
    lower bound is positive.

    Halts at the Phase 4a boundary regardless of outcome — caller MUST
    do its own sign-off cycle before promoting to Phase 4b.
    """
    drop_seasons = list(drop_seasons or [])
    sports = list(sports) if sports else list(ALL_SPORTS)
    now = (now_fn or datetime.utcnow)()
    rid = run_id or str(uuid.uuid4())

    if supabase_client is None:
        if supabase_client_factory is None:
            from .runner import _default_supabase_client_factory

            supabase_client_factory = _default_supabase_client_factory
        supabase_client = supabase_client_factory()
    sb = supabase_client

    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): sid for sid, n in sports_map.items()}
    teams = load_teams_with_schools(sb)

    result = Phase4aResult(
        config_label=config_label,
        run_id=rid,
        timestamp=now,
        train_seasons=list(train_seasons),
        holdout_seasons=list(holdout_seasons),
        drop_seasons=list(drop_seasons),
    )

    per_sport_p_values: list[tuple[str, float]] = []

    for sport_name in sports:
        sid = name_to_id.get(sport_name.lower())
        if sid is None:
            continue

        # Load per-season inputs
        inputs_list: list[RunInputs] = []
        for season in train_seasons + holdout_seasons:
            if season in drop_seasons:
                continue
            inputs_list.append(load_run_inputs(sb, sid, sport_name, season, teams=teams))

        train_rows: list[GameTrainingRow] = []
        hold_rows: list[GameTrainingRow] = []
        for inp in inputs_list:
            rows = _build_training_rows(inp)
            if inp.season_year in holdout_seasons:
                hold_rows.extend(rows)
            else:
                train_rows.extend(rows)

        if not train_rows or not hold_rows:
            result.fit_warnings.append(f"{sport_name}: insufficient rows — skipped")
            continue

        try:
            fit_b = fit_sport(sport_name, train_rows, cv_seed=seed)
            fit_a = fit_sport(sport_name, train_rows, cv_seed=seed, fixed_indices=[2])
        except Exception as e:
            result.fit_warnings.append(
                f"{sport_name}: fit raised {type(e).__name__}: {e}"
            )
            continue

        if not fit_b.converged:
            result.fit_warnings.append(f"{sport_name}: baseline did not converge cleanly")
        if not fit_a.converged:
            result.fit_warnings.append(f"{sport_name}: ablation did not converge cleanly")

        config_b = PredictionConfig(
            model_coefficients_by_sport={sport_name: fit_b.coefficients}
        )
        config_a = PredictionConfig(
            model_coefficients_by_sport={sport_name: fit_a.coefficients}
        )
        preds_b = _predict_rows(hold_rows, sport_name, config_b)
        preds_a = _predict_rows(hold_rows, sport_name, config_a)

        b_acc = game_winner_accuracy(preds_b)
        a_acc = game_winner_accuracy(preds_a)
        b_bri = brier_score(preds_b)
        a_bri = brier_score(preds_a)

        acc_lift, acc_ci, brier_lift, brier_ci, p_one = _paired_bootstrap_lift(
            preds_b, preds_a,
            n_resamples=n_bootstrap, seed=seed,
        )

        sport_result = SportPhase4aResult(
            sport=sport_name,
            fit_baseline=fit_b,
            fit_ablation=fit_a,
            n_holdout=len(hold_rows),
            baseline_accuracy=b_acc,
            ablation_accuracy=a_acc,
            accuracy_lift=acc_lift,
            accuracy_lift_ci=acc_ci,
            baseline_brier=b_bri,
            ablation_brier=a_bri,
            brier_lift=brier_lift,
            brier_lift_ci=brier_ci,
            p_value_one_sided=p_one,
        )
        result.sports[sport_name] = sport_result
        per_sport_p_values.append((sport_name, p_one))

    # Benjamini-Hochberg FDR across the 8 per-sport p-values
    if per_sport_p_values:
        sport_names = [s for s, _ in per_sport_p_values]
        p_list = [p for _, p in per_sport_p_values]
        flags = benjamini_hochberg(p_list, alpha=fdr_alpha)
        for sport_name, sig in zip(sport_names, flags):
            sr = result.sports[sport_name]
            # Spec requires BOTH FDR-significance AND CI-lower-bound > 0
            sr.significant_after_fdr = bool(sig and sr.accuracy_lift_ci[0] > 0.0)
            if sr.significant_after_fdr:
                result.n_significant_after_fdr += 1

    return result


# ---------------------------------------------------------------------------
# Phase 4b — recent-form weighting (Reese 2026-05-26 evening reordering)
# ---------------------------------------------------------------------------
@dataclass
class SportPhase4bResult:
    """Per-sport result block for Phase 4b recent-form ablation.

    Mirrors SportPhase4aResult but on the β₆ slot. Lift positive means
    the recent-form-enabled model beats the recent-form-ablated model.
    """

    sport: str
    fit_baseline: FitResult            # WITH recent-form (β₆ free)
    fit_ablation: FitResult            # WITHOUT recent-form (β₆ = 0)
    n_holdout: int
    baseline_accuracy: float
    ablation_accuracy: float
    accuracy_lift: float
    accuracy_lift_ci: tuple[float, float]
    baseline_brier: float
    ablation_brier: float
    brier_lift: float
    brier_lift_ci: tuple[float, float]
    p_value_one_sided: float
    significant_after_fdr: bool = False


@dataclass
class Phase4bResult:
    config_label: str
    run_id: str
    timestamp: datetime
    train_seasons: list[int]
    holdout_seasons: list[int]
    drop_seasons: list[int]
    sports: dict[str, SportPhase4bResult] = field(default_factory=dict)
    n_significant_after_fdr: int = 0
    fit_warnings: list[str] = field(default_factory=list)


def run_phase4b_recent_form_ablation(
    *,
    train_seasons: list[int],
    holdout_seasons: list[int],
    drop_seasons: list[int] | None = None,
    sports: list[str] | None = None,
    config_label: str = "wf-phase4b-recent-form-ablation",
    n_bootstrap: int = 1000,
    seed: int = 42,
    fdr_alpha: float = 0.05,
    recent_form_config: Any | None = None,
    supabase_client: Any | None = None,
    supabase_client_factory: Callable[[], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    run_id: str | None = None,
) -> Phase4bResult:
    """Phase 4b: per-sport β₆ ablation. Recent-form-enabled vs β₆=0.

    Mirrors ``run_phase4a_hfa_ablation``: fits ref + ablation per sport,
    computes paired-bootstrap CI on (acc, brier) deltas, applies
    Benjamini-Hochberg FDR across the 8 per-sport tests. Halts at the
    phase boundary regardless of outcome per the v2 spec.
    """
    drop_seasons = list(drop_seasons or [])
    sports = list(sports) if sports else list(ALL_SPORTS)
    now = (now_fn or datetime.utcnow)()
    rid = run_id or str(uuid.uuid4())

    if supabase_client is None:
        if supabase_client_factory is None:
            from .runner import _default_supabase_client_factory

            supabase_client_factory = _default_supabase_client_factory
        supabase_client = supabase_client_factory()
    sb = supabase_client

    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): sid for sid, n in sports_map.items()}
    teams = load_teams_with_schools(sb)

    # Use a default PredictionConfig for the recent-form precompute (the
    # caller can override via ``recent_form_config`` if they want
    # different margin caps for the form computation).
    rf_config = recent_form_config or _PredictionConfig()

    result = Phase4bResult(
        config_label=config_label,
        run_id=rid,
        timestamp=now,
        train_seasons=list(train_seasons),
        holdout_seasons=list(holdout_seasons),
        drop_seasons=list(drop_seasons),
    )

    per_sport_p_values: list[tuple[str, float]] = []

    for sport_name in sports:
        sid = name_to_id.get(sport_name.lower())
        if sid is None:
            continue

        inputs_list: list[RunInputs] = []
        for season in train_seasons + holdout_seasons:
            if season in drop_seasons:
                continue
            inputs_list.append(load_run_inputs(sb, sid, sport_name, season, teams=teams))

        train_rows: list[GameTrainingRow] = []
        hold_rows: list[GameTrainingRow] = []
        for inp in inputs_list:
            form_table = precompute_team_week_form(inp.games, sport_name, rf_config)
            rows = _build_training_rows(inp, recent_form_signals=form_table)
            if inp.season_year in holdout_seasons:
                hold_rows.extend(rows)
            else:
                train_rows.extend(rows)

        if not train_rows or not hold_rows:
            result.fit_warnings.append(f"{sport_name}: insufficient rows — skipped")
            continue

        try:
            fit_b = fit_sport(sport_name, train_rows, cv_seed=seed)
            fit_a = fit_sport(sport_name, train_rows, cv_seed=seed, fixed_indices=[6])
        except Exception as e:
            result.fit_warnings.append(
                f"{sport_name}: fit raised {type(e).__name__}: {e}"
            )
            continue

        if not fit_b.converged:
            result.fit_warnings.append(f"{sport_name}: ref did not converge cleanly")
        if not fit_a.converged:
            result.fit_warnings.append(f"{sport_name}: ablation did not converge cleanly")

        config_b = PredictionConfig(
            model_coefficients_by_sport={sport_name: fit_b.coefficients}
        )
        config_a = PredictionConfig(
            model_coefficients_by_sport={sport_name: fit_a.coefficients}
        )
        preds_b = _predict_rows(hold_rows, sport_name, config_b)
        preds_a = _predict_rows(hold_rows, sport_name, config_a)

        b_acc = game_winner_accuracy(preds_b)
        a_acc = game_winner_accuracy(preds_a)
        b_bri = brier_score(preds_b)
        a_bri = brier_score(preds_a)

        acc_lift, acc_ci, brier_lift, brier_ci, p_one = _paired_bootstrap_lift(
            preds_b, preds_a, n_resamples=n_bootstrap, seed=seed,
        )

        sport_result = SportPhase4bResult(
            sport=sport_name,
            fit_baseline=fit_b,
            fit_ablation=fit_a,
            n_holdout=len(hold_rows),
            baseline_accuracy=b_acc,
            ablation_accuracy=a_acc,
            accuracy_lift=acc_lift,
            accuracy_lift_ci=acc_ci,
            baseline_brier=b_bri,
            ablation_brier=a_bri,
            brier_lift=brier_lift,
            brier_lift_ci=brier_ci,
            p_value_one_sided=p_one,
        )
        result.sports[sport_name] = sport_result
        per_sport_p_values.append((sport_name, p_one))

    if per_sport_p_values:
        sport_names = [s for s, _ in per_sport_p_values]
        p_list = [p for _, p in per_sport_p_values]
        flags = benjamini_hochberg(p_list, alpha=fdr_alpha)
        for sport_name, sig in zip(sport_names, flags):
            sr = result.sports[sport_name]
            sr.significant_after_fdr = bool(sig and sr.accuracy_lift_ci[0] > 0.0)
            if sr.significant_after_fdr:
                result.n_significant_after_fdr += 1

    return result


# ---------------------------------------------------------------------------
# Phase 4c — log-margin ablation (β₃ slot)
# ---------------------------------------------------------------------------
@dataclass
class SportPhase4cResult:
    """Per-sport result block for Phase 4c log-margin ablation.

    Reference fit = β₃ free (log-margin signal active).
    Ablation fit = β₃ constrained to 0 (signal still computed, but
    the coefficient slot is masked).

    Lift positive means the log-margin-enabled model beats the ablation.
    """

    sport: str
    fit_baseline: FitResult            # WITH log-margin (β₃ free)
    fit_ablation: FitResult            # WITHOUT log-margin (β₃ = 0)
    n_holdout: int
    baseline_accuracy: float
    ablation_accuracy: float
    accuracy_lift: float
    accuracy_lift_ci: tuple[float, float]
    baseline_brier: float
    ablation_brier: float
    brier_lift: float
    brier_lift_ci: tuple[float, float]
    p_value_one_sided: float
    significant_after_fdr: bool = False


@dataclass
class Phase4cResult:
    config_label: str
    run_id: str
    timestamp: datetime
    train_seasons: list[int]
    holdout_seasons: list[int]
    drop_seasons: list[int]
    sports: dict[str, SportPhase4cResult] = field(default_factory=dict)
    n_significant_after_fdr: int = 0
    fit_warnings: list[str] = field(default_factory=list)


def run_phase4c_log_margin_ablation(
    *,
    train_seasons: list[int],
    holdout_seasons: list[int],
    drop_seasons: list[int] | None = None,
    sports: list[str] | None = None,
    config_label: str = "wf-phase4c-log-margin-ablation",
    n_bootstrap: int = 1000,
    seed: int = 42,
    fdr_alpha: float = 0.05,
    supabase_client: Any | None = None,
    supabase_client_factory: Callable[[], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    run_id: str | None = None,
) -> Phase4cResult:
    """Phase 4c: per-sport β₃ ablation. Log-margin-enabled vs β₃=0.

    Both reference and ablation include the Phase 4b recent-form signal
    (β₆ free) — Phase 4c builds on top of Phase 4b, it does not
    replace it. The ablation cleanly isolates the marginal contribution
    of the log-margin feature given that recent-form is already in.

    Mirrors ``run_phase4b_recent_form_ablation`` structurally: fits ref
    + ablation per sport, computes paired-bootstrap CI on (acc, brier)
    deltas, applies BH-FDR across the 8 per-sport tests. Halts at the
    phase boundary regardless of outcome.
    """
    drop_seasons = list(drop_seasons or [])
    sports = list(sports) if sports else list(ALL_SPORTS)
    now = (now_fn or datetime.utcnow)()
    rid = run_id or str(uuid.uuid4())

    if supabase_client is None:
        if supabase_client_factory is None:
            from .runner import _default_supabase_client_factory

            supabase_client_factory = _default_supabase_client_factory
        supabase_client = supabase_client_factory()
    sb = supabase_client

    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): sid for sid, n in sports_map.items()}
    teams = load_teams_with_schools(sb)

    rf_config = _PredictionConfig()

    result = Phase4cResult(
        config_label=config_label,
        run_id=rid,
        timestamp=now,
        train_seasons=list(train_seasons),
        holdout_seasons=list(holdout_seasons),
        drop_seasons=list(drop_seasons),
    )

    per_sport_p_values: list[tuple[str, float]] = []

    for sport_name in sports:
        sid = name_to_id.get(sport_name.lower())
        if sid is None:
            continue

        inputs_list: list[RunInputs] = []
        for season in train_seasons + holdout_seasons:
            if season in drop_seasons:
                continue
            inputs_list.append(load_run_inputs(sb, sid, sport_name, season, teams=teams))

        train_rows: list[GameTrainingRow] = []
        hold_rows: list[GameTrainingRow] = []
        for inp in inputs_list:
            # Both features are pre-game by construction; precompute both for
            # the season and feed into _build_training_rows.
            form_table = precompute_team_week_form(inp.games, sport_name, rf_config)
            log_margin_table = precompute_team_week_log_margins(inp.games)
            rows = _build_training_rows(
                inp,
                recent_form_signals=form_table,
                log_margin_signals=log_margin_table,
            )
            if inp.season_year in holdout_seasons:
                hold_rows.extend(rows)
            else:
                train_rows.extend(rows)

        if not train_rows or not hold_rows:
            result.fit_warnings.append(f"{sport_name}: insufficient rows — skipped")
            continue

        try:
            # Reference fit: β₃ free (along with all other identifiable slots)
            fit_b = fit_sport(sport_name, train_rows, cv_seed=seed)
            # Ablation fit: β₃ constrained to 0
            fit_a = fit_sport(sport_name, train_rows, cv_seed=seed, fixed_indices=[3])
        except Exception as e:
            result.fit_warnings.append(
                f"{sport_name}: fit raised {type(e).__name__}: {e}"
            )
            continue

        if not fit_b.converged:
            result.fit_warnings.append(f"{sport_name}: ref did not converge cleanly")
        if not fit_a.converged:
            result.fit_warnings.append(f"{sport_name}: ablation did not converge cleanly")

        config_b = PredictionConfig(
            model_coefficients_by_sport={sport_name: fit_b.coefficients}
        )
        config_a = PredictionConfig(
            model_coefficients_by_sport={sport_name: fit_a.coefficients}
        )
        preds_b = _predict_rows(hold_rows, sport_name, config_b)
        preds_a = _predict_rows(hold_rows, sport_name, config_a)

        b_acc = game_winner_accuracy(preds_b)
        a_acc = game_winner_accuracy(preds_a)
        b_bri = brier_score(preds_b)
        a_bri = brier_score(preds_a)

        acc_lift, acc_ci, brier_lift, brier_ci, p_one = _paired_bootstrap_lift(
            preds_b, preds_a, n_resamples=n_bootstrap, seed=seed,
        )

        sport_result = SportPhase4cResult(
            sport=sport_name,
            fit_baseline=fit_b,
            fit_ablation=fit_a,
            n_holdout=len(hold_rows),
            baseline_accuracy=b_acc,
            ablation_accuracy=a_acc,
            accuracy_lift=acc_lift,
            accuracy_lift_ci=acc_ci,
            baseline_brier=b_bri,
            ablation_brier=a_bri,
            brier_lift=brier_lift,
            brier_lift_ci=brier_ci,
            p_value_one_sided=p_one,
        )
        result.sports[sport_name] = sport_result
        per_sport_p_values.append((sport_name, p_one))

    if per_sport_p_values:
        sport_names = [s for s, _ in per_sport_p_values]
        p_list = [p for _, p in per_sport_p_values]
        flags = benjamini_hochberg(p_list, alpha=fdr_alpha)
        for sport_name, sig in zip(sport_names, flags):
            sr = result.sports[sport_name]
            sr.significant_after_fdr = bool(sig and sr.accuracy_lift_ci[0] > 0.0)
            if sr.significant_after_fdr:
                result.n_significant_after_fdr += 1

    return result


# ---------------------------------------------------------------------------
# Phase 4d — Massey off/def ablation (β₄ slot)
# ---------------------------------------------------------------------------
# β₃ is pinned to 0 from Phase 4c onward per decisions.md 2026-05-27 entry
# "Phase 4c log-margin (β₃) null + mechanism retraction." This pin is enforced
# by passing fixed_indices including 3 on every Phase 4d+ fit. The pin
# preserves the slot in the model spec (functional form unchanged); the
# disposition is "no marginal predictive power above β₁+β₆," not "feature
# removed."
PHASE4_PINNED_INDICES = (3,)


@dataclass
class SportPhase4dResult:
    """Per-sport result block for Phase 4d Massey off/def ablation.

    Reference fit: β₃ pinned to 0, β₄ free (Massey signal active).
    Ablation fit: β₃ AND β₄ pinned to 0 (Massey signal still computed
    but the coefficient slot is masked).

    Lift positive means the Massey-enabled model beats the ablation.
    """

    sport: str
    fit_baseline: FitResult            # β₃=0, β₄ free
    fit_ablation: FitResult            # β₃=0, β₄=0
    n_holdout: int
    baseline_accuracy: float
    ablation_accuracy: float
    accuracy_lift: float
    accuracy_lift_ci: tuple[float, float]
    baseline_brier: float
    ablation_brier: float
    brier_lift: float
    brier_lift_ci: tuple[float, float]
    p_value_one_sided: float
    significant_after_fdr: bool = False


@dataclass
class Phase4dResult:
    config_label: str
    run_id: str
    timestamp: datetime
    train_seasons: list[int]
    holdout_seasons: list[int]
    drop_seasons: list[int]
    sports: dict[str, SportPhase4dResult] = field(default_factory=dict)
    n_significant_after_fdr: int = 0
    fit_warnings: list[str] = field(default_factory=list)


def run_phase4d_offdef_ablation(
    *,
    train_seasons: list[int],
    holdout_seasons: list[int],
    drop_seasons: list[int] | None = None,
    sports: list[str] | None = None,
    config_label: str = "wf-phase4d-massey-offdef-ablation",
    n_bootstrap: int = 1000,
    seed: int = 42,
    fdr_alpha: float = 0.05,
    supabase_client: Any | None = None,
    supabase_client_factory: Callable[[], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    run_id: str | None = None,
) -> Phase4dResult:
    """Phase 4d: per-sport β₄ ablation. Massey-enabled vs β₄=0.

    Both reference and ablation:
      - Include Phase 4b recent-form (β₆ free)
      - Include Phase 4c log-margin signal (computed) with β₃ PINNED to 0
        per decisions.md 2026-05-27 disposition
      - Reference: β₄ free (Massey off/def signal active)
      - Ablation: β₄ pinned to 0 (Massey signal still computed but
        coefficient masked)

    This isolates the marginal contribution of the Massey LS off/def
    decomposition given that recent-form is already in and log-margin
    is pinned-out.

    Mirrors run_phase4c_log_margin_ablation structurally. Halts at
    phase boundary regardless of outcome. >2pp lift on any sport
    triggers the standardized replay audit downstream (the CLI flags
    the trigger; the audit is run as a separate step).
    """
    drop_seasons = list(drop_seasons or [])
    sports = list(sports) if sports else list(ALL_SPORTS)
    now = (now_fn or datetime.utcnow)()
    rid = run_id or str(uuid.uuid4())

    if supabase_client is None:
        if supabase_client_factory is None:
            from .runner import _default_supabase_client_factory

            supabase_client_factory = _default_supabase_client_factory
        supabase_client = supabase_client_factory()
    sb = supabase_client

    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): sid for sid, n in sports_map.items()}
    teams = load_teams_with_schools(sb)

    rf_config = _PredictionConfig()

    result = Phase4dResult(
        config_label=config_label,
        run_id=rid,
        timestamp=now,
        train_seasons=list(train_seasons),
        holdout_seasons=list(holdout_seasons),
        drop_seasons=list(drop_seasons),
    )

    per_sport_p_values: list[tuple[str, float]] = []

    for sport_name in sports:
        sid = name_to_id.get(sport_name.lower())
        if sid is None:
            continue

        inputs_list: list[RunInputs] = []
        for season in train_seasons + holdout_seasons:
            if season in drop_seasons:
                continue
            inputs_list.append(load_run_inputs(sb, sid, sport_name, season, teams=teams))

        train_rows: list[GameTrainingRow] = []
        hold_rows: list[GameTrainingRow] = []
        for inp in inputs_list:
            form_table = precompute_team_week_form(inp.games, sport_name, rf_config)
            log_margin_table = precompute_team_week_log_margins(inp.games)
            massey_table = precompute_team_week_massey_od(inp.games)
            rows = _build_training_rows(
                inp,
                recent_form_signals=form_table,
                log_margin_signals=log_margin_table,
                massey_od_signals=massey_table,
            )
            if inp.season_year in holdout_seasons:
                hold_rows.extend(rows)
            else:
                train_rows.extend(rows)

        if not train_rows or not hold_rows:
            result.fit_warnings.append(f"{sport_name}: insufficient rows — skipped")
            continue

        try:
            # Reference: beta_3 pinned to 0, beta_4 free.
            fit_b = fit_sport(
                sport_name, train_rows, cv_seed=seed,
                fixed_indices=list(PHASE4_PINNED_INDICES),
            )
            # Ablation: beta_3 AND beta_4 pinned to 0.
            fit_a = fit_sport(
                sport_name, train_rows, cv_seed=seed,
                fixed_indices=list(PHASE4_PINNED_INDICES) + [4],
            )
        except Exception as e:
            result.fit_warnings.append(
                f"{sport_name}: fit raised {type(e).__name__}: {e}"
            )
            continue

        if not fit_b.converged:
            result.fit_warnings.append(f"{sport_name}: ref did not converge cleanly")
        if not fit_a.converged:
            result.fit_warnings.append(f"{sport_name}: ablation did not converge cleanly")

        config_b = PredictionConfig(
            model_coefficients_by_sport={sport_name: fit_b.coefficients}
        )
        config_a = PredictionConfig(
            model_coefficients_by_sport={sport_name: fit_a.coefficients}
        )
        preds_b = _predict_rows(hold_rows, sport_name, config_b)
        preds_a = _predict_rows(hold_rows, sport_name, config_a)

        b_acc = game_winner_accuracy(preds_b)
        a_acc = game_winner_accuracy(preds_a)
        b_bri = brier_score(preds_b)
        a_bri = brier_score(preds_a)

        acc_lift, acc_ci, brier_lift, brier_ci, p_one = _paired_bootstrap_lift(
            preds_b, preds_a, n_resamples=n_bootstrap, seed=seed,
        )

        sport_result = SportPhase4dResult(
            sport=sport_name,
            fit_baseline=fit_b,
            fit_ablation=fit_a,
            n_holdout=len(hold_rows),
            baseline_accuracy=b_acc,
            ablation_accuracy=a_acc,
            accuracy_lift=acc_lift,
            accuracy_lift_ci=acc_ci,
            baseline_brier=b_bri,
            ablation_brier=a_bri,
            brier_lift=brier_lift,
            brier_lift_ci=brier_ci,
            p_value_one_sided=p_one,
        )
        result.sports[sport_name] = sport_result
        per_sport_p_values.append((sport_name, p_one))

    if per_sport_p_values:
        sport_names = [s for s, _ in per_sport_p_values]
        p_list = [p for _, p in per_sport_p_values]
        flags = benjamini_hochberg(p_list, alpha=fdr_alpha)
        for sport_name, sig in zip(sport_names, flags):
            sr = result.sports[sport_name]
            sr.significant_after_fdr = bool(sig and sr.accuracy_lift_ci[0] > 0.0)
            if sr.significant_after_fdr:
                result.n_significant_after_fdr += 1

    return result


# ---------------------------------------------------------------------------
# Phase 4e — prior-year carryover ablation (β₅ slot)
# ---------------------------------------------------------------------------
# Reese 2026-05-29 design decisions:
#  - Ablation control: PIN β₃ + β₄ + β₅ (stricter null). β₄ pinned in BOTH
#    fits so it cannot absorb β₅'s signal when β₅ is pinned in the ablation.
#  - Cold-start handling: report TWO measurements — weeks-1-3 (PRIMARY;
#    where β₅ structurally fires via _decay) and full-season (SECONDARY,
#    Phase 4d parity). Headline is the primary.
#  - Missing prior-year handling: KEEP cold-start games (they're precisely
#    what β₅ targets). Diagnostic counts _pyc=0 share in the primary
#    holdout window.
PHASE4E_REF_PINNED_INDICES = (3, 4)         # β₃ + β₄ pinned, β₅ free
PHASE4E_ABL_PINNED_INDICES = (3, 4, 5)      # β₃ + β₄ + β₅ all pinned


@dataclass
class Phase4eMeasurement:
    """One acc/Brier-lift measurement on a sport's holdout subset.

    Phase 4e reports two measurements per sport: weeks_1_3 (primary) and
    full_season (secondary, Phase 4d parity).
    """

    label: str                              # "weeks_1_3" | "full_season"
    n_holdout: int
    baseline_accuracy: float
    ablation_accuracy: float
    accuracy_lift: float
    accuracy_lift_ci: tuple[float, float]
    baseline_brier: float
    ablation_brier: float
    brier_lift: float
    brier_lift_ci: tuple[float, float]
    p_value_one_sided: float
    significant_after_fdr: bool = False


@dataclass
class SportPhase4eResult:
    """Per-sport result block for Phase 4e prior-year-carryover ablation.

    Reference fit: β₃ + β₄ pinned, β₅ free (Phase 4d parity except β₄
    held constant so it cannot absorb β₅'s signal).
    Ablation fit: β₃ + β₄ + β₅ all pinned. β₆ free in both.
    """

    sport: str
    fit_baseline: FitResult                 # PHASE4E_REF_PINNED_INDICES
    fit_ablation: FitResult                 # PHASE4E_ABL_PINNED_INDICES
    weeks_1_3: "Phase4eMeasurement"
    full_season: "Phase4eMeasurement"
    n_pyc_zero_holdout: int = 0
    n_pyc_zero_genuine_coldstart: int = 0
    n_pyc_zero_data_gap: int = 0


@dataclass
class Phase4eResult:
    config_label: str
    run_id: str
    timestamp: datetime
    train_seasons: list[int]
    holdout_seasons: list[int]
    drop_seasons: list[int]
    sports: dict[str, SportPhase4eResult] = field(default_factory=dict)
    n_significant_after_fdr_primary: int = 0
    n_significant_after_fdr_secondary: int = 0
    fit_warnings: list[str] = field(default_factory=list)


def _filter_rows_weeks_1_3(rows: list[GameTrainingRow]) -> list[GameTrainingRow]:
    """Filter to games where home week_number ∈ {1, 2, 3} (where β₅ fires)."""
    return [r for r in rows if 1 <= r.home_state.week_number <= 3]


def _measure_phase4e_lift(
    label: str,
    hold_rows: list[GameTrainingRow],
    sport_name: str,
    config_b: PredictionConfig,
    config_a: PredictionConfig,
    *,
    n_bootstrap: int,
    seed: int,
) -> Phase4eMeasurement:
    """Compute paired-bootstrap lift on a holdout subset."""
    preds_b = _predict_rows(hold_rows, sport_name, config_b)
    preds_a = _predict_rows(hold_rows, sport_name, config_a)
    if preds_b and preds_a:
        b_acc = game_winner_accuracy(preds_b)
        a_acc = game_winner_accuracy(preds_a)
        b_bri = brier_score(preds_b)
        a_bri = brier_score(preds_a)
        acc_lift, acc_ci, brier_lift, brier_ci, p_one = _paired_bootstrap_lift(
            preds_b, preds_a, n_resamples=n_bootstrap, seed=seed,
        )
    else:
        b_acc = a_acc = b_bri = a_bri = 0.0
        acc_lift = brier_lift = 0.0
        acc_ci = brier_ci = (0.0, 0.0)
        p_one = 1.0
    return Phase4eMeasurement(
        label=label,
        n_holdout=len(hold_rows),
        baseline_accuracy=b_acc,
        ablation_accuracy=a_acc,
        accuracy_lift=acc_lift,
        accuracy_lift_ci=acc_ci,
        baseline_brier=b_bri,
        ablation_brier=a_bri,
        brier_lift=brier_lift,
        brier_lift_ci=brier_ci,
        p_value_one_sided=p_one,
    )


def run_phase4e_prior_year_ablation(
    *,
    train_seasons: list[int],
    holdout_seasons: list[int],
    drop_seasons: list[int] | None = None,
    sports: list[str] | None = None,
    config_label: str = "wf-phase4e-prior-year-carryover-ablation",
    n_bootstrap: int = 1000,
    seed: int = 42,
    fdr_alpha: float = 0.05,
    supabase_client: Any | None = None,
    supabase_client_factory: Callable[[], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    run_id: str | None = None,
) -> Phase4eResult:
    """Phase 4e: per-sport β₅ ablation. Prior-year carryover enabled vs β₅=0.

    Both reference and ablation:
      - β₃ pinned to 0 (Phase 4c disposition)
      - β₄ PINNED to 0 in BOTH fits (Reese 2026-05-29 design call: β₄
        cannot absorb β₅'s signal when β₅ is masked in the ablation)
      - β₆ free in both
    Reference: β₅ free.
    Ablation: β₅ pinned to 0.

    Reports two holdout measurements per sport:
      - weeks_1_3 (PRIMARY): rows where home week_number ∈ {1,2,3}.
        This is where _decay() makes β₅ non-zero structurally.
      - full_season (SECONDARY): matches Phase 4d holdout scope.

    Halts at phase boundary regardless of outcome.
    """
    drop_seasons = list(drop_seasons or [])
    sports = list(sports) if sports else list(ALL_SPORTS)
    now = (now_fn or datetime.utcnow)()
    rid = run_id or str(uuid.uuid4())

    if supabase_client is None:
        if supabase_client_factory is None:
            from .runner import _default_supabase_client_factory

            supabase_client_factory = _default_supabase_client_factory
        supabase_client = supabase_client_factory()
    sb = supabase_client

    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): sid for sid, n in sports_map.items()}
    teams = load_teams_with_schools(sb)

    rf_config = _PredictionConfig()

    result = Phase4eResult(
        config_label=config_label,
        run_id=rid,
        timestamp=now,
        train_seasons=list(train_seasons),
        holdout_seasons=list(holdout_seasons),
        drop_seasons=list(drop_seasons),
    )

    p_values_primary: list[tuple[str, float]] = []
    p_values_secondary: list[tuple[str, float]] = []

    for sport_name in sports:
        sid = name_to_id.get(sport_name.lower())
        if sid is None:
            continue

        inputs_list: list[RunInputs] = []
        for season in train_seasons + holdout_seasons:
            if season in drop_seasons:
                continue
            inputs_list.append(load_run_inputs(sb, sid, sport_name, season, teams=teams))

        train_rows: list[GameTrainingRow] = []
        hold_rows: list[GameTrainingRow] = []
        for inp in inputs_list:
            form_table = precompute_team_week_form(inp.games, sport_name, rf_config)
            log_margin_table = precompute_team_week_log_margins(inp.games)
            massey_table = precompute_team_week_massey_od(inp.games)
            rows = _build_training_rows(
                inp,
                recent_form_signals=form_table,
                log_margin_signals=log_margin_table,
                massey_od_signals=massey_table,
            )
            if inp.season_year in holdout_seasons:
                hold_rows.extend(rows)
            else:
                train_rows.extend(rows)

        if not train_rows or not hold_rows:
            result.fit_warnings.append(f"{sport_name}: insufficient rows — skipped")
            continue

        try:
            fit_b = fit_sport(
                sport_name, train_rows, cv_seed=seed,
                fixed_indices=list(PHASE4E_REF_PINNED_INDICES),
            )
            fit_a = fit_sport(
                sport_name, train_rows, cv_seed=seed,
                fixed_indices=list(PHASE4E_ABL_PINNED_INDICES),
            )
        except Exception as e:
            result.fit_warnings.append(
                f"{sport_name}: fit raised {type(e).__name__}: {e}"
            )
            continue

        if not fit_b.converged:
            result.fit_warnings.append(f"{sport_name}: ref did not converge cleanly")
        if not fit_a.converged:
            result.fit_warnings.append(f"{sport_name}: ablation did not converge cleanly")

        config_b = PredictionConfig(
            model_coefficients_by_sport={sport_name: fit_b.coefficients}
        )
        config_a = PredictionConfig(
            model_coefficients_by_sport={sport_name: fit_a.coefficients}
        )

        rows_w1_3 = _filter_rows_weeks_1_3(hold_rows)
        m_primary = _measure_phase4e_lift(
            "weeks_1_3", rows_w1_3, sport_name, config_b, config_a,
            n_bootstrap=n_bootstrap, seed=seed,
        )
        m_secondary = _measure_phase4e_lift(
            "full_season", hold_rows, sport_name, config_b, config_a,
            n_bootstrap=n_bootstrap, seed=seed,
        )

        n_zero = 0
        for r in rows_w1_3:
            if r.home_state.prior_year_rating is None:
                n_zero += 1
            if r.away_state.prior_year_rating is None:
                n_zero += 1

        sport_result = SportPhase4eResult(
            sport=sport_name,
            fit_baseline=fit_b,
            fit_ablation=fit_a,
            weeks_1_3=m_primary,
            full_season=m_secondary,
            n_pyc_zero_holdout=n_zero,
            n_pyc_zero_genuine_coldstart=n_zero,
            n_pyc_zero_data_gap=0,
        )
        result.sports[sport_name] = sport_result
        p_values_primary.append((sport_name, m_primary.p_value_one_sided))
        p_values_secondary.append((sport_name, m_secondary.p_value_one_sided))

    if p_values_primary:
        sport_names = [s for s, _ in p_values_primary]
        p_list = [p for _, p in p_values_primary]
        flags = benjamini_hochberg(p_list, alpha=fdr_alpha)
        for sport_name, sig in zip(sport_names, flags):
            sr = result.sports[sport_name]
            sr.weeks_1_3.significant_after_fdr = bool(
                sig and sr.weeks_1_3.accuracy_lift_ci[0] > 0.0
            )
            if sr.weeks_1_3.significant_after_fdr:
                result.n_significant_after_fdr_primary += 1
    if p_values_secondary:
        sport_names = [s for s, _ in p_values_secondary]
        p_list = [p for _, p in p_values_secondary]
        flags = benjamini_hochberg(p_list, alpha=fdr_alpha)
        for sport_name, sig in zip(sport_names, flags):
            sr = result.sports[sport_name]
            sr.full_season.significant_after_fdr = bool(
                sig and sr.full_season.accuracy_lift_ci[0] > 0.0
            )
            if sr.full_season.significant_after_fdr:
                result.n_significant_after_fdr_secondary += 1

    return result


# ---------------------------------------------------------------------------
# Phase 5 — Q1-Q4 competitive stratification
# ---------------------------------------------------------------------------
# Per the v2 plan §5: report per-sport accuracy + Brier per quartile of
# abs(rating_diff). Q1 = closest games (the hardest; toss-ups). Q4 =
# biggest blowouts (the easiest to predict). Phase 7 marketing claims
# require Q1 lower-CI > pro benchmark, NOT overall accuracy > pro
# benchmark.
#
# The fit configuration matches the engine's current candidate-final
# state: β₃ pinned to 0 (Phase 4c disposition), β₄/β₅/β₆ free
# (post-Phase-4d-Step-4 + Phase-4e disposition). For sports where β₄ or
# β₅ ended up in noise band on their respective phases, the fit still
# allows them — the regression just lands them near 0.
PHASE5_PINNED_INDICES = (3,)


@dataclass
class SportPhase5Result:
    """Per-sport stratification result.

    sport       : sport name
    fit         : the model fit used for predictions on holdout
    n_holdout   : holdout games for this sport
    overall_acc : accuracy across all 4 quartiles (sanity check)
    overall_brier: brier across all quartiles
    quartiles   : list of QuartileResult Q1-Q4
    """

    sport: str
    fit: FitResult
    n_holdout: int
    overall_accuracy: float
    overall_brier: float
    quartiles: list[Any] = field(default_factory=list)


@dataclass
class Phase5Result:
    config_label: str
    run_id: str
    timestamp: datetime
    train_seasons: list[int]
    holdout_seasons: list[int]
    drop_seasons: list[int]
    sports: dict[str, SportPhase5Result] = field(default_factory=dict)
    fit_warnings: list[str] = field(default_factory=list)


def run_phase5_stratification(
    *,
    train_seasons: list[int],
    holdout_seasons: list[int],
    drop_seasons: list[int] | None = None,
    sports: list[str] | None = None,
    config_label: str = "wf-phase5-stratification",
    n_bootstrap: int = 1000,
    seed: int = 42,
    supabase_client: Any | None = None,
    supabase_client_factory: Callable[[], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    run_id: str | None = None,
) -> Phase5Result:
    """Phase 5: per-sport Q1-Q4 competitive stratification.

    Fits the engine's current candidate-final model per sport (β₃ pinned;
    β₄/β₅/β₆ free), predicts holdout, and splits the predictions into
    quartiles by abs(home_rating - away_rating). Reports per-quartile
    accuracy + Brier with bootstrap CIs.

    This is descriptive — no ablation, no FDR. Output feeds Phase 7
    marketing-claims rigor framing.
    """
    from .stratify import stratify  # local import: avoid circular at module load

    drop_seasons = list(drop_seasons or [])
    sports = list(sports) if sports else list(ALL_SPORTS)
    now = (now_fn or datetime.utcnow)()
    rid = run_id or str(uuid.uuid4())

    if supabase_client is None:
        if supabase_client_factory is None:
            from .runner import _default_supabase_client_factory

            supabase_client_factory = _default_supabase_client_factory
        supabase_client = supabase_client_factory()
    sb = supabase_client

    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): sid for sid, n in sports_map.items()}
    teams = load_teams_with_schools(sb)

    rf_config = _PredictionConfig()

    result = Phase5Result(
        config_label=config_label,
        run_id=rid,
        timestamp=now,
        train_seasons=list(train_seasons),
        holdout_seasons=list(holdout_seasons),
        drop_seasons=list(drop_seasons),
    )

    for sport_name in sports:
        sid = name_to_id.get(sport_name.lower())
        if sid is None:
            continue

        inputs_list: list[RunInputs] = []
        for season in train_seasons + holdout_seasons:
            if season in drop_seasons:
                continue
            inputs_list.append(load_run_inputs(sb, sid, sport_name, season, teams=teams))

        train_rows: list[GameTrainingRow] = []
        hold_rows: list[GameTrainingRow] = []
        for inp in inputs_list:
            form_table = precompute_team_week_form(inp.games, sport_name, rf_config)
            log_margin_table = precompute_team_week_log_margins(inp.games)
            massey_table = precompute_team_week_massey_od(inp.games)
            rows = _build_training_rows(
                inp,
                recent_form_signals=form_table,
                log_margin_signals=log_margin_table,
                massey_od_signals=massey_table,
            )
            if inp.season_year in holdout_seasons:
                hold_rows.extend(rows)
            else:
                train_rows.extend(rows)

        if not train_rows or not hold_rows:
            result.fit_warnings.append(f"{sport_name}: insufficient rows — skipped")
            continue

        try:
            fit = fit_sport(
                sport_name, train_rows, cv_seed=seed,
                fixed_indices=list(PHASE5_PINNED_INDICES),
            )
        except Exception as e:
            result.fit_warnings.append(
                f"{sport_name}: fit raised {type(e).__name__}: {e}"
            )
            continue

        if not fit.converged:
            result.fit_warnings.append(f"{sport_name}: fit did not converge cleanly")

        config = PredictionConfig(
            model_coefficients_by_sport={sport_name: fit.coefficients}
        )
        preds = _predict_rows(hold_rows, sport_name, config)
        if not preds:
            continue

        overall_acc = game_winner_accuracy(preds)
        overall_bri = brier_score(preds)
        quartiles = stratify(preds, n_bootstrap=n_bootstrap, seed=seed)

        result.sports[sport_name] = SportPhase5Result(
            sport=sport_name,
            fit=fit,
            n_holdout=len(preds),
            overall_accuracy=overall_acc,
            overall_brier=overall_bri,
            quartiles=quartiles,
        )

    return result


