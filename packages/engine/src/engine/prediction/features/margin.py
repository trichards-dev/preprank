"""Phase-2a score-margin feature.

The LHSAA power-rating formula in ``power_rating.py`` is fixed — it does
not look at score margin. This module computes a downstream signal that
augments the *prediction layer*: for each (team, week) we accumulate the
team's mean signed margin (clipped per-sport so blowouts don't dominate)
across all of its prior games. The validator's predictor adds
``alpha * margin_signal`` to each side's pre-game rating before feeding
the matchup into ``win_probability_v2``.

All functions here are pure; they take dicts/lists in and return floats
or new dicts. None of them touch the DB.
"""
from __future__ import annotations

from collections import defaultdict

from engine.prediction.config import PredictionConfig


def capped_margin(
    home_score: int,
    away_score: int,
    sport: str,
    config: PredictionConfig,
) -> int:
    """Signed margin from the home team's perspective, clipped per-sport.

    The cap comes from ``config.margin_cap_by_sport.get(sport)``; if the
    sport is missing from the map we fall back to the largest cap in the
    table (Football=35) as a safe default — callers should always pass a
    sport that exists in the map.

    Returns a positive int when home scored more, negative when home
    scored less. Zero when the game was tied.
    """
    raw = int(home_score) - int(away_score)
    cap = config.margin_cap_by_sport.get(sport)
    if cap is None:
        # Defensive default: take the maximum cap in the table, so unknown
        # sports don't silently clip to zero.
        cap = max(config.margin_cap_by_sport.values(), default=35)
    if raw > cap:
        return int(cap)
    if raw < -cap:
        return int(-cap)
    return raw


def team_margin_signal(
    games: list[dict],
    team_id: int,
    sport: str,
    config: PredictionConfig,
) -> float:
    """Mean capped-margin per game, signed from ``team_id``'s perspective.

    Each game contributes ``+capped_margin`` if ``team_id`` was the home
    side, ``-capped_margin`` if they were away, and is skipped if the
    team did not play in it or the row is missing a score. Returns
    ``0.0`` when the team has zero contributing games (cold start safe).
    """
    total = 0
    n = 0
    for g in games:
        h = g.get("home_team_id")
        a = g.get("away_team_id")
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        if h == team_id:
            total += capped_margin(hs, as_, sport, config)
            n += 1
        elif a == team_id:
            total += -capped_margin(hs, as_, sport, config)
            n += 1
    if n == 0:
        return 0.0
    return float(total) / float(n)


def precompute_team_week_margins(
    games: list[dict],
    sport: str,
    config: PredictionConfig,
) -> dict[tuple[int, int], float]:
    """Build a ``{(team_id, week): cumulative_mean_margin}`` lookup table.

    For each ``(team, week W)`` the entry holds the team's average signed
    capped-margin across every one of its games whose ``_engine_week``
    is ``<= W``. This is what the runner queries with ``W-1`` to get the
    pre-game signal for a game scheduled in week ``W`` (i.e. the signal
    only sees games *strictly before* the game being predicted).

    The lookup is dense in ``W``: if a team plays in weeks 1 and 3, we
    still emit entries at weeks 1, 2, and 3 (week 2 carries the same
    cumulative value as week 1) so the runner can index by any week
    without missing values.
    """
    if not games:
        return {}

    # First pass: bucket each team's contributions by week
    per_team_per_week: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    weeks_seen: set[int] = set()
    teams_seen: set[int] = set()

    for g in games:
        w = g.get("_engine_week")
        if w is None:
            continue
        try:
            w = int(w)
        except (TypeError, ValueError):
            continue
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        h = g.get("home_team_id")
        a = g.get("away_team_id")
        margin = capped_margin(hs, as_, sport, config)
        if h is not None:
            per_team_per_week[h][w].append(margin)
            teams_seen.add(h)
        if a is not None:
            per_team_per_week[a][w].append(-margin)
            teams_seen.add(a)
        weeks_seen.add(w)

    if not weeks_seen:
        return {}

    max_week = max(weeks_seen)
    min_week = min(weeks_seen)

    out: dict[tuple[int, int], float] = {}
    for team_id in teams_seen:
        by_week = per_team_per_week[team_id]
        running_sum = 0
        running_n = 0
        for w in range(min_week, max_week + 1):
            for m in by_week.get(w, ()):
                running_sum += m
                running_n += 1
            if running_n > 0:
                out[(team_id, w)] = float(running_sum) / float(running_n)
    return out
