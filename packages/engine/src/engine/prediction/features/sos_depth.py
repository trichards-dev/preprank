"""Phase-2d opponent-of-opponents (depth-2) SOS adjustment.

The LHSAA power-rating formula uses a shallow opponents-win-percent term
(effectively depth-1 SOS). This module computes a *prediction-layer*
signal that captures the difference between a team's depth-2 SOS (the
average LHSAA rating of the opponents-of-opponents set) and its depth-1
SOS (the average LHSAA rating of its own opponents). The validator's
predictor adds ``alpha * sos_depth_signal`` to each side's pre-game
rating before feeding the matchup into ``win_probability_v2``.

Positive signal means a team's opponents' opponents are *stronger* than
its own opponents — its schedule is harder than the surface SOS would
suggest. Negative signal means the opposite. Zero (the cold-start
default) is bit-for-bit neutral against the predictor.

All functions here are pure. None of them touch the DB.
"""
from __future__ import annotations

from collections import defaultdict

from engine.prediction.config import PredictionConfig


def team_opponents_through_week(
    games: list[dict],
    team_id: int,
    through_week: int,
) -> set[int]:
    """Set of team IDs that ``team_id`` has played through ``through_week`` (inclusive).

    ``games`` are season rows carrying the validator's derived
    ``_engine_week`` key. Rows missing scores, missing a week, or
    flagged ``is_out_of_state`` are skipped.
    """
    opponents: set[int] = set()
    for g in games:
        if g.get("is_out_of_state"):
            continue
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        w_raw = g.get("_engine_week")
        if w_raw is None:
            continue
        try:
            w = int(w_raw)
        except (TypeError, ValueError):
            continue
        if w > int(through_week):
            continue
        h = g.get("home_team_id")
        a = g.get("away_team_id")
        if h == team_id and a is not None:
            opponents.add(int(a))
        elif a == team_id and h is not None:
            opponents.add(int(h))
    return opponents


def _resolve_rating_at_or_before(
    ratings_by_team_week: dict[tuple[int, int], float],
    team_id: int,
    week: int,
) -> float | None:
    """Return the most-recent rating for ``team_id`` at week ``<= week``.

    Walks backwards from ``week`` to 1 looking for a populated rating.
    Returns ``None`` if no rating exists at any week <= ``week`` (true
    cold-start opponent — caller should drop them from the mean rather
    than substitute 0.0 and contaminate the average).
    """
    # Fast path: exact week present.
    r = ratings_by_team_week.get((team_id, week))
    if r is not None:
        return float(r)
    # Walk backwards.
    for w in range(week - 1, 0, -1):
        r = ratings_by_team_week.get((team_id, w))
        if r is not None:
            return float(r)
    return None


def _mean_rating_for_set(
    team_ids: set[int],
    ratings_by_team_week: dict[tuple[int, int], float],
    week: int,
) -> float | None:
    """Mean LHSAA rating for ``team_ids`` at week ``<= week``, dropping
    teams with no rating at any week up to ``week``.

    Returns ``None`` when the resolved set is empty (no opponents have a
    rating yet — caller should treat the signal as 0.0).
    """
    if not team_ids:
        return None
    total = 0.0
    n = 0
    for tid in team_ids:
        r = _resolve_rating_at_or_before(ratings_by_team_week, tid, week)
        if r is None:
            continue
        total += float(r)
        n += 1
    if n == 0:
        return None
    return total / float(n)


def precompute_depth_sos_signal(
    games: list[dict],
    ratings_by_team_week: dict[tuple[int, int], float],
    sport: str,
    config: PredictionConfig,
) -> dict[tuple[int, int], float]:
    """Build a ``{(team_id, week): depth2_sos - depth1_sos}`` lookup table.

    For every ``(team T, week W)`` covered by ``games``, the entry holds
    the depth-2 minus depth-1 SOS *as of end of week W* (i.e. it sees
    every game T or T's opponents played whose ``_engine_week`` is
    ``<= W``).

    Implementation:

    * Walk ``games`` once to bucket per-team weeks where the team played.
    * For each (team T, played-week W), compute:
        - ``opponents`` = ``team_opponents_through_week(T, W)``
        - ``depth1`` = mean rating of ``opponents`` at week W
                       (most recent rating <= W per opponent; opponents
                       without a rating are dropped from the mean)
        - ``oo``     = union of every opponent's opponents through W,
                       excluding T itself
        - ``depth2`` = mean rating of ``oo`` at week W (same rule)
        - ``signal`` = depth2 - depth1
    * Densify by week: between two played weeks, carry the last
      computed signal forward so the runner can index by any week
      without missing values.

    Cold-start safety:

    * A team with no opponents through W gets a 0.0 entry at W.
    * If depth1 or depth2 collapses to an empty set (all opponents are
      cold-start themselves), the corresponding side is treated as 0.0
      — so the signal degrades gracefully to 0 rather than throwing.

    The ``sport`` and ``config`` arguments are accepted for parity with
    the margin/recent_form precompute signatures and for future
    extensions (e.g. per-sport rating-resolution rules); they are not
    used by the current implementation.
    """
    # The sport/config args are reserved for future per-sport rating
    # resolution; intentionally unused right now.
    del sport, config

    if not games:
        return {}

    # Collect played weeks per team and all weeks seen at all.
    played_weeks: dict[int, set[int]] = defaultdict(set)
    weeks_seen: set[int] = set()
    for g in games:
        if g.get("is_out_of_state"):
            continue
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        w_raw = g.get("_engine_week")
        if w_raw is None:
            continue
        try:
            w = int(w_raw)
        except (TypeError, ValueError):
            continue
        h = g.get("home_team_id")
        a = g.get("away_team_id")
        if h is not None:
            played_weeks[int(h)].add(w)
        if a is not None:
            played_weeks[int(a)].add(w)
        weeks_seen.add(w)

    if not weeks_seen:
        return {}

    min_week = min(weeks_seen)
    max_week = max(weeks_seen)

    out: dict[tuple[int, int], float] = {}
    for team_id, team_played_weeks in played_weeks.items():
        last_signal = 0.0
        had_any = False
        for w in range(min_week, max_week + 1):
            if w in team_played_weeks:
                # Recompute signal at the end of week w.
                opponents = team_opponents_through_week(games, team_id, w)
                if not opponents:
                    last_signal = 0.0
                else:
                    # Opponents of opponents, excluding T itself.
                    oo: set[int] = set()
                    for o in opponents:
                        for x in team_opponents_through_week(games, o, w):
                            if x == team_id:
                                continue
                            oo.add(x)

                    depth1 = _mean_rating_for_set(opponents, ratings_by_team_week, w)
                    depth2 = _mean_rating_for_set(oo, ratings_by_team_week, w)

                    # Degrade missing pieces to 0.0 so we always emit
                    # a finite signal even when the rating lookup is
                    # sparse (cold-start opponents).
                    d1 = 0.0 if depth1 is None else depth1
                    d2 = 0.0 if depth2 is None else depth2
                    last_signal = float(d2 - d1)
                out[(team_id, w)] = last_signal
                had_any = True
            elif had_any:
                # Densify between played weeks so the runner's W-1
                # lookup can't miss.
                out[(team_id, w)] = last_signal
    return out
