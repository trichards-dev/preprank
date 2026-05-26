"""v2 logistic-regression prediction model.

Implements the formal model from ``docs/model_specification.md``:

    logit P(home wins) = β₀ + β₁·Δrating + β₂·HFA + β₃·Δf_margin
                       + β₄·Δf_offdef  + β₅·Δf_pyc

Per-sport β vectors are fitted by max-likelihood L2-regularized logistic
regression on the train fold (scipy.optimize.minimize / L-BFGS-B with
analytic gradient). The L2 strength λ is chosen via k-fold nested CV
inside the train fold — never hardcoded at run time. The fitted vectors
live in ``PredictionConfig.model_coefficients_by_sport``;
``predict_game_v3`` reads them at prediction time. By default it falls
back to the legacy ``win_probability_v2`` path when a sport has no
fitted vector (preserves the baseline regression guarantee); pass
``strict=True`` to raise ``MissingCoefficientsError`` instead — that's
what the validator runner and the Phase-7 marketing-claim generator
must do so a silent fall-through can't masquerade as a fitted result.

Phase 4 features land as new β slots inside the same equation. Phase 6
recalibration outputs live in ``PredictionConfig.recalibration_params_by_sport``
and are applied by this module after the raw fitted probability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np
from scipy.optimize import minimize

from engine.prediction.config import PredictionConfig
from engine.win_probability import win_probability_v2


class MissingCoefficientsError(RuntimeError):
    """Raised by ``predict_game_v3(strict=True)`` when no β are fitted.

    Distinct from the legacy ``win_probability_v2`` fallback path: the
    runner uses this signal to refuse to publish predictions that
    would silently masquerade as v2 fitted outputs.
    """


class FitConvergenceError(RuntimeError):
    """Raised when ``fit_sport`` fails to converge in a way that should
    NOT be silently absorbed (non-finite output, λ-CV grid all failed,
    or insufficient train data for the chosen CV split)."""


# Coefficient name ↔ feature-vector index. Order is load-bearing for the
# fit + predict paths. β₆ (recent-form) was added 2026-05-26 evening per
# Reese's Phase 4b sign-off — Phase 4b reorders the v2 plan to put
# recent-form ahead of log-margin / offdef / prior-year carryover.
COEF_NAMES: tuple[str, ...] = (
    "beta_0",  # intercept
    "beta_1",  # Δrating
    "beta_2",  # HFA indicator
    "beta_3",  # Δf_margin (log-compressed scoring margin)
    "beta_4",  # Δf_offdef (Massey-style offense/defense decomposition)
    "beta_5",  # Δf_pyc    (prior-year carryover, weeks 1-3 only)
    "beta_6",  # Δf_recent_form (recency-weighted capped-margin signal)
)

N_FEATURES = len(COEF_NAMES)

# Probabilities clipped to this range when evaluating the log-likelihood
# to prevent log(0) blowups. Raw predictions are NOT clipped — Phase 6
# recalibration wants the unclamped extremes.
_LOSS_EPS = 1e-6


@dataclass
class GameState:
    """Per-team pre-game state at the moment a prediction is made.

    All numeric fields are pre-game observable; no in-game or post-game
    quantities. See ``docs/model_specification.md`` "Feature definitions"
    for how each signal is computed by upstream Phase 4 modules.
    """

    rating: float
    margin_signal: float = 0.0
    off_signal: float = 0.0
    def_signal: float = 0.0
    prior_year_rating: float | None = None
    recent_form_signal: float = 0.0
    week_number: int = 1
    season_year: int = 0


@dataclass
class GameTrainingRow:
    """One game with both teams' states and the observed outcome.

    ``is_mercy`` carries the Phase-0 audit's mercy-rule flag. During
    Phase 4c, mercy games get down-weighted in the loss via
    ``w_mercy``; before Phase 4c, ``is_mercy`` is informational and all
    games carry equal weight.
    """

    home_state: GameState
    away_state: GameState
    is_neutral_site: bool
    is_mercy: bool
    home_won: bool


@dataclass
class FitResult:
    """Output of ``fit_sport``. Stored in
    ``PredictionConfig.model_coefficients_by_sport[sport]`` as a flat
    coefficient dict; the rest of the fields are reporting only.

    ``selected_lambda_per_game`` and ``lambda_cv_scores`` make the
    nested-CV λ choice auditable from the FitResult alone.
    """

    sport: str
    coefficients: dict[str, float]
    n_train_games: int
    converged: bool
    loss: float
    iterations: int
    message: str = ""
    selected_lambda_per_game: float = 0.0
    lambda_cv_scores: dict[float, float] = field(default_factory=dict)


def _decay(week_number: int) -> float:
    """Prior-year carryover decay schedule from the model spec.

    week 1 → 1.0, week 2 → 0.667, week 3 → 0.333, week ≥ 4 → 0.0.
    """
    if week_number < 1:
        return 1.0
    if week_number >= 4:
        return 0.0
    return max(0.0, 1.0 - (week_number - 1) / 3.0)


def _pyc(state: GameState) -> float:
    """Per-team prior-year carryover term for the model's β₅ feature."""
    if state.prior_year_rating is None:
        return 0.0
    return _decay(state.week_number) * state.prior_year_rating


def _feature_vector(
    home: GameState,
    away: GameState,
    *,
    is_neutral_site: bool,
) -> np.ndarray:
    """Build the feature vector for one game.

    Returns a length-``N_FEATURES`` array with indices mapped to
    ``COEF_NAMES``. Unfilled upstream signals evaluate to 0 and their β
    stays at 0 in baseline fits.
    """
    hfa_indicator = 0.0 if is_neutral_site else 1.0

    # Massey-style matchup contrast per spec: matchup(X_off, Y_def) = X_off + Y_def.
    # Δf_offdef = matchup(h_off, a_def) - matchup(a_off, h_def).
    f_offdef = (home.off_signal + away.def_signal) - (away.off_signal + home.def_signal)

    return np.array(
        [
            1.0,                                                        # β₀ intercept
            home.rating - away.rating,                                  # β₁ Δrating
            hfa_indicator,                                              # β₂ HFA
            home.margin_signal - away.margin_signal,                    # β₃ Δf_margin
            f_offdef,                                                   # β₄ Δf_offdef
            _pyc(home) - _pyc(away),                                    # β₅ Δf_pyc
            home.recent_form_signal - away.recent_form_signal,          # β₆ Δf_recent_form
        ],
        dtype=np.float64,
    )


def _logit(z: np.ndarray) -> np.ndarray:
    """Numerically-stable σ(z)."""
    # Split into z >= 0 and z < 0 to avoid overflow in exp(±z)
    out = np.empty_like(z)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


def _nll_and_grad(
    beta: np.ndarray,
    X: np.ndarray,
    y: np.ndarray,
    sample_weight: np.ndarray,
    l2_lambda: float,
) -> tuple[float, np.ndarray]:
    """Weighted negative-log-likelihood + L2 penalty, with analytic gradient.

    BFGS converges materially faster when handed a gradient. The analytic
    form is cheap (one matmul each for the loss and its gradient) so we
    always provide it.
    """
    z = X @ beta
    p = _logit(z)
    p_clipped = np.clip(p, _LOSS_EPS, 1.0 - _LOSS_EPS)
    nll = -np.sum(sample_weight * (y * np.log(p_clipped) + (1.0 - y) * np.log(1.0 - p_clipped)))
    reg = l2_lambda * float(beta @ beta)
    loss = float(nll + reg)

    grad = X.T @ (sample_weight * (p - y))
    grad += 2.0 * l2_lambda * beta
    return loss, grad


def _fit_with_lambda(
    X: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    l2_lambda: float,
    beta0: np.ndarray,
    max_iter: int,
    gtol: float,
) -> tuple[np.ndarray, float, int, bool, str]:
    """Inner fit at a fixed λ. Returns (β̂, loss, iters, converged, message).

    Separated so the λ-selection nested CV can call it many times
    without re-implementing the optimizer plumbing.
    """
    result = minimize(
        _nll_and_grad,
        beta0,
        args=(X, y, w, l2_lambda),
        method="L-BFGS-B",
        jac=True,
        options={"gtol": gtol, "maxiter": max_iter},
    )
    final_grad = result.jac if getattr(result, "jac", None) is not None else np.zeros_like(result.x)
    grad_norm = float(np.linalg.norm(final_grad))
    converged = bool(result.success) or grad_norm < 1e-3
    return (
        np.array(result.x, dtype=np.float64),
        float(result.fun),
        int(result.nit),
        converged,
        str(result.message),
    )


def _negative_log_likelihood_unregularized(
    beta: np.ndarray, X: np.ndarray, y: np.ndarray, w: np.ndarray
) -> float:
    """Pure NLL without the L2 penalty — used to score λ-grid candidates
    on held-out folds (regularization is part of training, not the
    validation criterion)."""
    z = X @ beta
    p = _logit(z)
    p_clipped = np.clip(p, _LOSS_EPS, 1.0 - _LOSS_EPS)
    return float(-np.sum(w * (y * np.log(p_clipped) + (1.0 - y) * np.log(1.0 - p_clipped))))


# Default λ-grid for nested CV. Spans 4 orders of magnitude — wide
# enough to bracket the optimum for typical HS-volume per-sport fits
# (Football's 5-season train fold is ~5K games; Volleyball is ~10K;
# Soccer per-gender is ~3K). Spec doc says λ is sensitivity-tested at
# {0.001, 0.01, 0.1} × n_train_games — this grid extends both ends.
_LAMBDA_GRID_DEFAULT: tuple[float, ...] = (1e-4, 1e-3, 1e-2, 1e-1, 1.0)


def _choose_lambda_nested_cv(
    X: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    *,
    lambdas: Sequence[float],
    n_folds: int,
    seed: int,
    beta0: np.ndarray,
    max_iter: int,
    gtol: float,
) -> tuple[float, dict[float, float]]:
    """K-fold nested CV inside the train fold.

    For each λ in the grid: fit on (k-1)/k of the train data, score raw
    NLL on the held-out 1/k, average across folds. Return the λ with the
    best mean held-out NLL. ``per_lambda_nll`` is the per-λ score map
    for surfacing in FitResult so the choice is auditable.
    """
    n = X.shape[0]
    if n < n_folds:
        raise FitConvergenceError(
            f"nested CV requires at least n_folds={n_folds} games; got n={n}"
        )

    rng = np.random.default_rng(seed)
    perm = rng.permutation(n)
    fold_assignments = np.array_split(perm, n_folds)

    per_lambda_nll: dict[float, float] = {}
    for lam_per_game in lambdas:
        fold_nlls: list[float] = []
        for fold_idx, val_idx in enumerate(fold_assignments):
            train_idx = np.concatenate(
                [fold_assignments[j] for j in range(n_folds) if j != fold_idx]
            )
            X_tr, y_tr, w_tr = X[train_idx], y[train_idx], w[train_idx]
            X_va, y_va, w_va = X[val_idx], y[val_idx], w[val_idx]
            l2_lambda = lam_per_game * X_tr.shape[0]
            beta_hat, *_ = _fit_with_lambda(
                X_tr, y_tr, w_tr, l2_lambda, beta0.copy(), max_iter, gtol
            )
            if not np.all(np.isfinite(beta_hat)):
                fold_nlls.append(np.inf)
                continue
            fold_nlls.append(
                _negative_log_likelihood_unregularized(beta_hat, X_va, y_va, w_va)
            )
        per_lambda_nll[float(lam_per_game)] = float(np.mean(fold_nlls))

    finite = {lam: nll for lam, nll in per_lambda_nll.items() if np.isfinite(nll)}
    if not finite:
        raise FitConvergenceError(
            "nested CV: all λ candidates failed (non-finite NLL across every fold)"
        )
    best_lambda = min(finite, key=finite.__getitem__)
    return best_lambda, per_lambda_nll


def fit_sport(
    sport: str,
    train_games: Iterable[GameTrainingRow],
    *,
    l2_lambda_per_game: float | None = None,
    lambda_grid: Sequence[float] | None = None,
    cv_n_folds: int = 5,
    cv_seed: int = 0,
    mercy_weight: float = 1.0,
    max_iter: int = 200,
    gtol: float = 1e-6,
    initial_coefficients: Sequence[float] | None = None,
    fixed_indices: Sequence[int] | None = None,
) -> FitResult:
    """Fit per-sport β vector by L2-regularized max-likelihood logistic regression.

    L2 strength λ is chosen by k-fold nested CV inside the train fold,
    unless ``l2_lambda_per_game`` is passed explicitly (tests + sanity
    runs use this to bypass CV). The nested-CV path is the production
    default; per Reese 2026-05-26 review, λ must not be hardcoded at
    run time.

    Parameters
    ----------
    sport : str
        Sport label (e.g. ``"Football"``). Used only to tag the FitResult.
    train_games : iterable of GameTrainingRow
        The train-fold games for this sport. Caller is responsible for
        filtering to the right fold + sport.
    l2_lambda_per_game : float, optional
        If supplied, skip nested CV and fit directly at this λ. Should
        only be set by tests, single-sport sanity runs, or callers who
        already ran the CV themselves and are re-fitting.
    lambda_grid : sequence of float, optional
        Candidate λ values (per-game) for the nested-CV sweep. Defaults
        to ``(1e-4, 1e-3, 1e-2, 1e-1, 1.0)``.
    cv_n_folds : int, default 5
        K for nested CV.
    cv_seed : int, default 0
        RNG seed for the fold permutation. Determinism guarantee: same
        seed + same data ⇒ same λ selected.
    mercy_weight : float, default 1.0
        Per-game loss weight for ``is_mercy=True`` rows. 1.0 = no
        down-weighting (pre-Phase-4c default). Phase 4c fits this jointly
        with the β vector via a separate call structure documented in
        ``prediction/features/mercy_weighting.py``.
    max_iter : int, default 200
        L-BFGS-B iteration cap.
    gtol : float, default 1e-6
        Gradient-norm convergence tolerance.
    initial_coefficients : optional sequence of float
        Warm start for L-BFGS-B. Defaults to a zero vector (uninformed prior).
    fixed_indices : optional sequence of int
        Coefficient indices that must remain 0.0 in the fitted result.
        Implementation: those columns are dropped from the design matrix
        before optimization; the reduced β is then padded with zeros at
        the fixed indices when written to the FitResult. Used by Phase
        4a's HFA ablation (``fixed_indices=[2]`` pins β₂=0).

    Returns
    -------
    FitResult with coefficients keyed by ``COEF_NAMES``. The
    ``selected_lambda_per_game`` field records the CV-chosen λ, and
    ``lambda_cv_scores`` records the per-λ mean held-out NLL. When
    ``fixed_indices`` is supplied, the constrained coefficients are
    exactly 0.0 in the result (and ``COEF_NAMES`` ordering is preserved).

    Raises
    ------
    ValueError
        If ``train_games`` is empty after iteration, or if
        ``initial_coefficients`` length is wrong.
    FitConvergenceError
        If the optimizer produces non-finite output, or if all λ
        candidates failed during nested CV.
    """
    rows = list(train_games)
    n = len(rows)
    if n == 0:
        raise ValueError(f"fit_sport({sport!r}) received empty train_games")

    X = np.empty((n, N_FEATURES), dtype=np.float64)
    y = np.empty(n, dtype=np.float64)
    w = np.empty(n, dtype=np.float64)
    for i, row in enumerate(rows):
        X[i] = _feature_vector(
            row.home_state, row.away_state, is_neutral_site=row.is_neutral_site
        )
        y[i] = 1.0 if row.home_won else 0.0
        w[i] = mercy_weight if row.is_mercy else 1.0

    beta0_full = (
        np.array(list(initial_coefficients), dtype=np.float64)
        if initial_coefficients is not None
        else np.zeros(N_FEATURES, dtype=np.float64)
    )
    if beta0_full.shape != (N_FEATURES,):
        raise ValueError(
            f"initial_coefficients length {beta0_full.shape[0]} != N_FEATURES {N_FEATURES}"
        )

    # Constrained-fit support: drop the fixed columns from X, fit on the
    # reduced parameter vector, then pad zeros back at the fixed indices.
    if fixed_indices:
        fixed_set = set(int(i) for i in fixed_indices)
        for i in fixed_set:
            if not 0 <= i < N_FEATURES:
                raise ValueError(
                    f"fixed_indices contains {i} outside [0, {N_FEATURES})"
                )
        free_mask = np.array([i not in fixed_set for i in range(N_FEATURES)])
        X_fit = X[:, free_mask]
        beta0_fit = beta0_full[free_mask]
    else:
        free_mask = np.ones(N_FEATURES, dtype=bool)
        X_fit = X
        beta0_fit = beta0_full

    if l2_lambda_per_game is None:
        grid = lambda_grid if lambda_grid is not None else _LAMBDA_GRID_DEFAULT
        chosen_lambda, cv_scores = _choose_lambda_nested_cv(
            X_fit, y, w,
            lambdas=grid,
            n_folds=cv_n_folds,
            seed=cv_seed,
            beta0=beta0_fit,
            max_iter=max_iter,
            gtol=gtol,
        )
    else:
        chosen_lambda = float(l2_lambda_per_game)
        cv_scores = {}

    l2_lambda = chosen_lambda * n
    beta_fit_hat, loss, iters, converged, message = _fit_with_lambda(
        X_fit, y, w, l2_lambda, beta0_fit.copy(), max_iter, gtol
    )

    if not np.all(np.isfinite(beta_fit_hat)):
        raise FitConvergenceError(
            f"fit_sport({sport!r}) produced non-finite coefficients: "
            f"{beta_fit_hat.tolist()} after {iters} iterations"
        )

    # Pad the reduced fit back to full β-vector with 0s at fixed indices
    beta_hat = np.zeros(N_FEATURES, dtype=np.float64)
    beta_hat[free_mask] = beta_fit_hat
    coefficients = {name: float(beta_hat[i]) for i, name in enumerate(COEF_NAMES)}
    return FitResult(
        sport=sport,
        coefficients=coefficients,
        n_train_games=n,
        converged=converged,
        loss=loss,
        iterations=iters,
        message=message,
        selected_lambda_per_game=chosen_lambda,
        lambda_cv_scores=cv_scores,
    )


def _apply_recalibration(p_raw: float, params: dict) -> float:
    """Apply Phase-6 recalibration if params are present and well-formed.

    Supports the two methods documented in the model spec:
    isotonic (piecewise-linear interpolation) and platt (sigmoid). Falls
    back to the raw probability if the params dict is empty or
    malformed; this keeps Phase 1 callable in isolation from Phase 6.
    """
    if not params:
        return p_raw
    method = params.get("method")
    if method == "isotonic":
        bp = params.get("breakpoints")
        vals = params.get("values")
        if bp is None or vals is None or len(bp) != len(vals) or len(bp) < 2:
            return p_raw
        return float(np.interp(p_raw, bp, vals))
    if method == "platt":
        a = float(params.get("slope", 1.0))
        b = float(params.get("intercept", 0.0))
        logit_raw = np.log(max(p_raw, _LOSS_EPS) / max(1.0 - p_raw, _LOSS_EPS))
        return float(1.0 / (1.0 + np.exp(-(a * logit_raw + b))))
    return p_raw


def predict_game_v3(
    home_state: GameState,
    away_state: GameState,
    sport: str,
    config: PredictionConfig,
    *,
    is_neutral_site: bool = False,
    strict: bool = False,
) -> float:
    """Return P(home_state's team wins) under the v2 model.

    Parameters
    ----------
    strict : bool, default False
        When ``True`` and no coefficients are fitted for ``sport``,
        raises :class:`MissingCoefficientsError`. Callers that must
        never silently emit a legacy-fallback prediction (the
        walk-forward runner once a fit completes; the Phase-7
        marketing-claim generator) set ``strict=True`` so a missing
        fit surfaces immediately. When ``False`` (default), falls
        back to :func:`engine.win_probability.win_probability_v2` —
        preserves the baseline regression guarantee for callers
        that pre-date v2 (existing engine consumers, tests, the
        scenarios router).
    """
    coefs = config.model_coefficients_by_sport.get(sport, {})
    if not coefs:
        if strict:
            raise MissingCoefficientsError(
                f"predict_game_v3(sport={sport!r}, strict=True): "
                f"no fitted coefficients in config.model_coefficients_by_sport. "
                "Either run fit_sport for this sport first or call with strict=False."
            )
        return win_probability_v2(home_state.rating, away_state.rating, config, sport=sport)

    x = _feature_vector(home_state, away_state, is_neutral_site=is_neutral_site)
    beta = np.array([coefs.get(name, 0.0) for name in COEF_NAMES], dtype=np.float64)
    logit_val = float(x @ beta)
    p_raw = float(_logit(np.array([logit_val]))[0])

    recal_params = config.recalibration_params_by_sport.get(sport, {})
    return _apply_recalibration(p_raw, recal_params)
