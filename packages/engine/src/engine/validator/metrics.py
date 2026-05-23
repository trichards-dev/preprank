"""Prediction-accuracy metrics for the validator.

All metrics operate on plain Python lists of :class:`PredictionRecord` (or
numeric arrays) — no DB access here. Pure NumPy + stdlib.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

import numpy as np

from .predictor import PredictionRecord

T = TypeVar("T")


def _ungraded(predictions: Sequence[PredictionRecord]) -> list[PredictionRecord]:
    """Drop predictions whose ``actual_home_won`` is None (no scored outcome)."""
    return [p for p in predictions if p.actual_home_won is not None]


def game_winner_accuracy(predictions: Sequence[PredictionRecord]) -> float:
    """Share of games where the higher-probability side matched the actual winner.

    Predictions of exactly 0.5 are graded as a *miss* (no opinion). Returns
    0.0 if there are no gradable predictions.
    """
    graded = _ungraded(predictions)
    if not graded:
        return 0.0
    correct = 0
    for p in graded:
        pick_home = p.home_win_probability > 0.5
        actual_home = bool(p.actual_home_won)
        if pick_home == actual_home and p.home_win_probability != 0.5:
            correct += 1
    return correct / len(graded)


def brier_score(predictions: Sequence[PredictionRecord]) -> float:
    """Mean squared error between predicted home-win probability and the actual binary outcome.

    Returns 0.0 if there are no gradable predictions.
    """
    graded = _ungraded(predictions)
    if not graded:
        return 0.0
    p = np.array([x.home_win_probability for x in graded], dtype=float)
    y = np.array([1.0 if x.actual_home_won else 0.0 for x in graded], dtype=float)
    return float(np.mean((p - y) ** 2))


def reliability_bins(
    predictions: Sequence[PredictionRecord], n_bins: int = 10
) -> list[dict]:
    """Bucket predictions by predicted probability and report the observed rate per bucket.

    Returns ``n_bins`` dicts ordered low->high with keys:
    ``bin_lower``, ``bin_upper``, ``mean_predicted``, ``mean_observed``, ``n_games``.
    Empty buckets report ``mean_predicted=NaN``, ``mean_observed=NaN``,
    ``n_games=0``.
    """
    if n_bins <= 0:
        raise ValueError("n_bins must be positive")
    graded = _ungraded(predictions)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out: list[dict] = []
    if not graded:
        for i in range(n_bins):
            out.append({
                "bin_lower": float(edges[i]),
                "bin_upper": float(edges[i + 1]),
                "mean_predicted": float("nan"),
                "mean_observed": float("nan"),
                "n_games": 0,
            })
        return out

    probs = np.array([p.home_win_probability for p in graded], dtype=float)
    obs = np.array([1.0 if p.actual_home_won else 0.0 for p in graded], dtype=float)

    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        # Right edge inclusive only on the final bucket so 1.0 isn't dropped.
        if i == n_bins - 1:
            mask = (probs >= lo) & (probs <= hi)
        else:
            mask = (probs >= lo) & (probs < hi)
        n = int(mask.sum())
        if n == 0:
            out.append({
                "bin_lower": float(lo),
                "bin_upper": float(hi),
                "mean_predicted": float("nan"),
                "mean_observed": float("nan"),
                "n_games": 0,
            })
        else:
            out.append({
                "bin_lower": float(lo),
                "bin_upper": float(hi),
                "mean_predicted": float(probs[mask].mean()),
                "mean_observed": float(obs[mask].mean()),
                "n_games": n,
            })
    return out


def playoff_field_accuracy(
    projected_field: set[int], actual_field: set[int]
) -> float:
    """Share of ``projected_field`` teams that actually qualified.

    Placeholder — the real metric requires Monte Carlo projections that this
    package doesn't run yet (deferred to TASK 4). Implemented now so the JSON
    schema is forward-compatible.

    TODO(task-4): wire this up once Monte Carlo projections are surfaced.
    """
    if not projected_field:
        return 0.0
    if not actual_field:
        return 0.0
    hit = projected_field & actual_field
    return len(hit) / len(projected_field)


def rating_projection_delta(
    projected: dict[int, float], actual: dict[int, float]
) -> dict:
    """Mean/median absolute difference between two team_id -> rating maps.

    Only teams that appear in both maps count. Returns ``{"mean_abs_delta",
    "median_abs_delta", "n"}``.
    """
    common = set(projected.keys()) & set(actual.keys())
    if not common:
        return {"mean_abs_delta": 0.0, "median_abs_delta": 0.0, "n": 0}
    deltas = np.array([abs(projected[t] - actual[t]) for t in common], dtype=float)
    return {
        "mean_abs_delta": float(deltas.mean()),
        "median_abs_delta": float(np.median(deltas)),
        "n": int(deltas.size),
    }


def bootstrap_ci(
    metric_fn: Callable[[Sequence[T]], float],
    samples: Sequence[T],
    n_resamples: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """Paired bootstrap CI around ``metric_fn(samples)``.

    Resamples ``samples`` with replacement ``n_resamples`` times, computes
    ``metric_fn`` on each resample, and returns the (lo, hi) quantiles.

    Returns ``(metric_fn(samples), metric_fn(samples))`` when ``samples`` is
    empty or has length 1 (no variability).
    """
    if not 0.0 < ci < 1.0:
        raise ValueError("ci must be in (0, 1)")
    if n_resamples < 1:
        raise ValueError("n_resamples must be >= 1")
    n = len(samples)
    if n == 0:
        return (0.0, 0.0)
    if n == 1:
        point = float(metric_fn(samples))
        return (point, point)

    rng = np.random.default_rng(seed)
    samples_list = list(samples)
    stats = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        resample = [samples_list[j] for j in idx]
        stats[i] = metric_fn(resample)
    alpha = (1.0 - ci) / 2.0
    lo = float(np.quantile(stats, alpha))
    hi = float(np.quantile(stats, 1.0 - alpha))
    return (lo, hi)
