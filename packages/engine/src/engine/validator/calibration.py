"""Calibration analysis: reliability bins + slope/intercept + optional isotonic.

Per the v2 plan §6: reliability plots per fold per sport per quartile,
calibration slope (β₁ in observed = β₀ + β₁ × predicted), and
optional isotonic recalibration when slope < 0.85 or > 1.15.

The reliability-bin computation is already in `metrics.reliability_bins`;
this module adds the slope/intercept fit and the recalibration helpers.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CalibrationFit:
    slope: float
    intercept: float
    n_games: int
    rms_error: float  # sqrt(mean((observed - (intercept + slope*predicted))^2))


def calibration_slope_intercept(
    predicted_probs: list[float],
    actuals: list[int],
) -> CalibrationFit:
    """Fit observed = β₀ + β₁ × predicted via OLS.

    Pure-Python (no numpy/scipy dep at this layer to keep the module
    portable). The validator's tests already pull in numpy via pandas,
    so we could swap to np.polyfit later if precision matters.

    Returns CalibrationFit. n_games = len(predicted_probs).
    """
    n = len(predicted_probs)
    if n < 2 or n != len(actuals):
        return CalibrationFit(slope=1.0, intercept=0.0, n_games=n, rms_error=0.0)

    mean_x = sum(predicted_probs) / n
    mean_y = sum(actuals) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(predicted_probs, actuals))
    den = sum((x - mean_x) ** 2 for x in predicted_probs)
    if den == 0:
        return CalibrationFit(slope=0.0, intercept=mean_y, n_games=n, rms_error=0.0)
    slope = num / den
    intercept = mean_y - slope * mean_x
    rss = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(predicted_probs, actuals))
    rms = (rss / n) ** 0.5
    return CalibrationFit(slope=slope, intercept=intercept, n_games=n, rms_error=rms)


def needs_recalibration(fit: CalibrationFit, slope_band: tuple[float, float] = (0.85, 1.15)) -> bool:
    """Heuristic from v2 plan §6.4: recalibrate when slope outside [0.85, 1.15]."""
    lo, hi = slope_band
    return not (lo <= fit.slope <= hi)


@dataclass
class IsotonicRegressor:
    """Pool-adjacent-violators isotonic regression.

    Fit on (train_predicted, train_actual) pairs; transform new predictions
    via piecewise-constant lookup. Pure-Python; no scikit-learn dep.

    This is the minimum-viable isotonic for v2 plan §6.4. If accuracy
    matters at the edges, swap to scipy.interpolate.IsotonicRegression
    or scikit-learn's variant.
    """
    breakpoints: list[float]
    values: list[float]

    @classmethod
    def fit(cls, predicted: list[float], actual: list[int]) -> "IsotonicRegressor":
        if not predicted or len(predicted) != len(actual):
            return cls(breakpoints=[], values=[])
        # Sort pairs by prediction
        pairs = sorted(zip(predicted, actual))
        # PAV: walk through and merge violating pairs
        groups: list[list[tuple[float, float]]] = [[(p, float(a))] for p, a in pairs]
        i = 1
        while i < len(groups):
            prev_mean = sum(a for _, a in groups[i - 1]) / len(groups[i - 1])
            curr_mean = sum(a for _, a in groups[i]) / len(groups[i])
            if prev_mean > curr_mean:
                groups[i - 1].extend(groups[i])
                groups.pop(i)
                if i > 1:
                    i -= 1
            else:
                i += 1
        breakpoints = [grp[-1][0] for grp in groups]
        values = [sum(a for _, a in grp) / len(grp) for grp in groups]
        return cls(breakpoints=breakpoints, values=values)

    def transform(self, predicted: list[float]) -> list[float]:
        if not self.breakpoints:
            return list(predicted)
        out: list[float] = []
        for p in predicted:
            # Find first group whose breakpoint >= p
            placed = False
            for bp, v in zip(self.breakpoints, self.values):
                if p <= bp:
                    out.append(v)
                    placed = True
                    break
            if not placed:
                out.append(self.values[-1])
        return out
