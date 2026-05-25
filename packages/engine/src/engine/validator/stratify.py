"""Competitive-game stratification (Q1-Q4) by absolute rating differential.

Per the v2 plan §5: "Q1 = closest games (rating_diff smallest 25%) ... Q4 =
biggest blowouts (rating_diff largest 25%)". Used to surface where the
model's accuracy holds — predicting an obvious blowout is easy; predicting
a toss-up is the actual skill.

Phase 7 marketing claims about "beats benchmark" require Q1 lower-CI
> benchmark (NFL 68.6%, MLB 57.1%, NBA tourney 72%, club soccer 61.6%).

This module is pure computation — no DB, no model. Plugs into the
walk-forward runner.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .metrics import bootstrap_ci, brier_score, game_winner_accuracy

if TYPE_CHECKING:
    from .predictor import PredictionRecord


@dataclass
class QuartileResult:
    quartile: int            # 1..4
    n_games: int
    accuracy: float
    accuracy_ci_low: float
    accuracy_ci_high: float
    brier: float
    brier_ci_low: float
    brier_ci_high: float
    rating_diff_min: float
    rating_diff_max: float


def _abs_rating_diff(p: "PredictionRecord") -> float:
    return abs(p.home_rating_pregame - p.away_rating_pregame)


def quartile_split(abs_diffs: list[float]) -> list[float]:
    """Return the three breakpoints (q1, q2, q3) for splitting into 4 quartiles."""
    if not abs_diffs:
        return [0.0, 0.0, 0.0]
    sorted_diffs = sorted(abs_diffs)
    n = len(sorted_diffs)
    return [
        sorted_diffs[n // 4],
        sorted_diffs[n // 2],
        sorted_diffs[3 * n // 4],
    ]


def stratify(
    predictions: Sequence["PredictionRecord"],
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> list[QuartileResult]:
    """Split PredictionRecords into Q1-Q4 by abs(home_rating - away_rating).

    Reuses the validator's existing metric functions for accuracy + Brier
    so the CI methodology matches the per-(sport, season) report.

    Q1 = closest games (toss-ups; the hardest predictions).
    """
    if not predictions:
        return []

    abs_diffs = [_abs_rating_diff(p) for p in predictions]
    breaks = quartile_split(abs_diffs)
    q_buckets: list[list["PredictionRecord"]] = [[], [], [], []]
    for p, d in zip(predictions, abs_diffs):
        if d <= breaks[0]:
            q_buckets[0].append(p)
        elif d <= breaks[1]:
            q_buckets[1].append(p)
        elif d <= breaks[2]:
            q_buckets[2].append(p)
        else:
            q_buckets[3].append(p)

    results: list[QuartileResult] = []
    for i, bucket in enumerate(q_buckets, start=1):
        if not bucket:
            results.append(QuartileResult(
                quartile=i, n_games=0,
                accuracy=0.0, accuracy_ci_low=0.0, accuracy_ci_high=0.0,
                brier=0.0, brier_ci_low=0.0, brier_ci_high=0.0,
                rating_diff_min=0.0, rating_diff_max=0.0,
            ))
            continue
        bucket_abs_diffs = [_abs_rating_diff(p) for p in bucket]
        acc = game_winner_accuracy(bucket)
        brier = brier_score(bucket)
        acc_lo, acc_hi = bootstrap_ci(game_winner_accuracy, bucket,
                                       n_resamples=n_bootstrap, seed=seed)
        brier_lo, brier_hi = bootstrap_ci(brier_score, bucket,
                                           n_resamples=n_bootstrap, seed=seed)
        results.append(QuartileResult(
            quartile=i, n_games=len(bucket),
            accuracy=acc, accuracy_ci_low=acc_lo, accuracy_ci_high=acc_hi,
            brier=brier, brier_ci_low=brier_lo, brier_ci_high=brier_hi,
            rating_diff_min=min(bucket_abs_diffs), rating_diff_max=max(bucket_abs_diffs),
        ))
    return results
