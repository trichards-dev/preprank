"""Benjamini-Hochberg FDR correction for the 40 sport×phase tests.

Per the v2 plan §2.3 decision triggers: "FDR-corrected at α=0.05
family-wise across 40 tests." Each phase comparison produces a paired
bootstrap p-value (probability that the candidate is no better than the
baseline); we correct that family of p-values before deciding accept/
reject.
"""
from __future__ import annotations


def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> list[bool]:
    """Returns a list of accept/reject flags (True = reject H0, i.e. result
    is significant after FDR correction).

    Implementation: sort p-values, find the largest k such that
    p_(k) <= (k/m) * alpha; reject all p_(1)..p_(k).

    Pure-Python; no scipy.stats dep. O(m log m).

    >>> benjamini_hochberg([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205], alpha=0.05)
    [True, True, True, True, True, False, False, False]
    """
    if not p_values:
        return []
    m = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda kv: kv[1])
    significance = [False] * m
    threshold_idx = -1
    for k, (orig_i, p) in enumerate(indexed, start=1):
        if p <= (k / m) * alpha:
            threshold_idx = k - 1   # 0-based last significant
    # All p-values up to threshold_idx in sorted order are rejected
    for j in range(threshold_idx + 1):
        orig_i = indexed[j][0]
        significance[orig_i] = True
    return significance


def family_decision(
    accept_flags: list[bool],
    require_all: bool = False,
) -> str:
    """Convenience helper: 'all-accept', 'some-accept', or 'none-accept'.

    Phase 4 spec says a feature is accepted only if BOTH (a) FDR-corrected
    significance holds and (b) 95% CI lower bound on accuracy lift > 0 and
    (c) Brier delta <= +0.005 and (d) consistent direction across folds.
    This helper handles only (a).
    """
    n_accept = sum(accept_flags)
    if n_accept == 0:
        return "none-accept"
    if require_all and n_accept == len(accept_flags):
        return "all-accept"
    if n_accept == len(accept_flags):
        return "all-accept"
    return "some-accept"
