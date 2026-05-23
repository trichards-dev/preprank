"""Phase-2b recent-form feature.

The LHSAA power-rating formula is fixed and ignorant of recency. This
module computes a *prediction-layer* signal that augments the rating
the validator's predictor feeds into ``win_probability_v2``: for each
(team, week) we accumulate a recency-weighted average of the team's
prior signed (and per-sport capped) game margins.

The recency curve is a piecewise-linear taper:

    games_back  ∈ [0, window-1]      → weight = peak       (e.g. 1.5)
    games_back  ∈ [window, floor_at) → linear decay from peak to 1.0
    games_back  ∈ [floor_at, ∞)      → weight = 1.0

Per the spec: "Weight last 3 games at 1.5× in form-adjusted rating;
decay older games linearly to 1.0× by game 8."

All functions here are pure. They reuse :func:`capped_margin` from the
Phase-2a margin module so blowouts don't dominate the recent-form
signal either.
"""
from __future__ import annotations

from collections import defaultdict

from engine.prediction.config import PredictionConfig

from .margin import capped_margin


def game_recency_weight(
    games_back: int,
    window: int = 3,
    peak: float = 1.5,
    floor_at: int = 8,
) -> float:
    """Weight for a game that's ``games_back`` games ago (0 = most recent).

    Games 0..window-1 get full ``peak`` weight (default 1.5).
    Games window..floor_at-1 decay linearly from ``peak`` down to 1.0.
    Games floor_at and beyond get 1.0.

    Returns 1.0 for ``games_back < 0`` (defensive; shouldn't happen).
    """
    if games_back < 0:
        return 1.0
    if games_back < window:
        return float(peak)
    if games_back >= floor_at:
        return 1.0
    # Linear interpolation between (window, peak) and (floor_at, 1.0).
    span = float(floor_at - window)
    if span <= 0:
        return 1.0
    progress = float(games_back - window) / span
    return float(peak) + (1.0 - float(peak)) * progress


def _sorted_team_contributions(
    games: list[dict],
    team_id: int,
    sport: str,
    config: PredictionConfig,
) -> list[tuple[int, int]]:
    """Return ``team_id``'s contributions as ``[(_engine_week, signed_capped_margin), ...]``
    sorted by ``_engine_week`` ascending. Games without scores or without a
    week are skipped. Each entry's margin is signed from ``team_id``'s
    perspective.
    """
    rows: list[tuple[int, int]] = []
    for g in games:
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        h = g.get("home_team_id")
        a = g.get("away_team_id")
        if h != team_id and a != team_id:
            continue
        w_raw = g.get("_engine_week", g.get("week_number"))
        if w_raw is None:
            continue
        try:
            w = int(w_raw)
        except (TypeError, ValueError):
            continue
        m = capped_margin(hs, as_, sport, config)
        if a == team_id:
            m = -m
        rows.append((w, int(m)))
    rows.sort(key=lambda r: r[0])
    return rows


def team_form_signal(
    games: list[dict],
    team_id: int,
    sport: str,
    config: PredictionConfig,
) -> float:
    """Recency-weighted average signed margin from ``team_id``'s perspective.

    Each game is weighted by :func:`game_recency_weight` based on how
    many games back it is from the team's most-recent appearance.
    Returns ``0.0`` if the team has zero contributing games (cold-start
    safe). Reuses :func:`capped_margin` for the per-game magnitude so
    recent form is also cap-protected against blowouts.

    Sorting: games are sorted by ``_engine_week`` ascending; the highest
    week is treated as ``games_back=0`` (most recent), the next-highest
    as ``games_back=1``, and so on.
    """
    rows = _sorted_team_contributions(games, team_id, sport, config)
    if not rows:
        return 0.0

    window = int(config.recent_form_window)
    peak = float(config.recent_form_weight)

    total = 0.0
    weight_sum = 0.0
    n = len(rows)
    # rows are oldest-first; the most-recent game is at index n-1.
    for idx, (_w, m) in enumerate(rows):
        games_back = (n - 1) - idx
        weight = game_recency_weight(games_back, window=window, peak=peak)
        total += weight * float(m)
        weight_sum += weight
    if weight_sum == 0.0:
        return 0.0
    return total / weight_sum


def precompute_team_week_form(
    games: list[dict],
    sport: str,
    config: PredictionConfig,
) -> dict[tuple[int, int], float]:
    """Build a ``{(team_id, week): recency_weighted_form_through_week}`` table.

    For each ``(team, week W)`` the entry holds the team's
    recency-weighted average signed capped-margin across every one of
    its games whose ``_engine_week`` is ``<= W``. This matches the
    through-week-inclusive convention of
    :func:`precompute_team_week_margins`, so the runner can look up at
    ``W-1`` and get the pre-game signal for a game scheduled in week
    ``W``.

    The lookup is dense in ``W``: if a team plays in weeks 1 and 3, the
    entries at weeks 1, 2, and 3 are all present (week 2 carries the
    same value as week 1) so the runner can index by any week without
    missing values.
    """
    if not games:
        return {}

    # Bucket each team's per-week contributions, signed from that team's POV.
    # We keep them in chronological order so games_back is meaningful when we
    # roll forward week by week.
    per_team: dict[int, list[tuple[int, int]]] = defaultdict(list)
    weeks_seen: set[int] = set()

    for g in games:
        w_raw = g.get("_engine_week")
        if w_raw is None:
            continue
        try:
            w = int(w_raw)
        except (TypeError, ValueError):
            continue
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        h = g.get("home_team_id")
        a = g.get("away_team_id")
        m = capped_margin(hs, as_, sport, config)
        if h is not None:
            per_team[h].append((w, int(m)))
        if a is not None:
            per_team[a].append((w, int(-m)))
        weeks_seen.add(w)

    if not weeks_seen:
        return {}

    min_week = min(weeks_seen)
    max_week = max(weeks_seen)

    window = int(config.recent_form_window)
    peak = float(config.recent_form_weight)

    out: dict[tuple[int, int], float] = {}
    for team_id, rows in per_team.items():
        # Sort oldest-first; the last item is the most recent.
        rows.sort(key=lambda r: r[0])
        # As W advances, the set of games included grows by prefix. Recompute
        # the recency-weighted mean for each week W in the active range.
        included: list[int] = []  # signed capped margins in chronological order
        rows_idx = 0
        last_signal = 0.0
        had_any = False
        for w in range(min_week, max_week + 1):
            # Absorb all of this team's games whose week is <= w.
            while rows_idx < len(rows) and rows[rows_idx][0] <= w:
                included.append(rows[rows_idx][1])
                rows_idx += 1
            if not included:
                continue
            n = len(included)
            total = 0.0
            weight_sum = 0.0
            for idx, m in enumerate(included):
                games_back = (n - 1) - idx
                weight = game_recency_weight(games_back, window=window, peak=peak)
                total += weight * float(m)
                weight_sum += weight
            if weight_sum > 0.0:
                last_signal = total / weight_sum
                had_any = True
                out[(team_id, w)] = last_signal
            elif had_any:
                out[(team_id, w)] = last_signal
    return out
