"""Phase-2e uncapped scoring-totals feature.

The LHSAA power-rating formula and the Phase-2a capped-margin signal both
clip score margins. That clipping is correct for the rating formula
(blowouts shouldn't snowball a team's rating), but it discards real signal
about *how much* a team scores and allows in absolute terms. Phase 2e adds
two per-team running averages — offensive strength (points scored per
game) and defensive weakness (points allowed per game) — and wires the
matchup-specific differential

    home_signal = home_offensive_strength - away_defensive_weakness
    away_signal = away_offensive_strength - home_defensive_weakness

into the predictor as separate additive terms on each side's effective
rating. Critically, neither side is capped: the whole point of this phase
is to recover signal that the capped-margin term throws away.

All functions here are pure; they take dicts/lists in and return floats
or new dicts. None of them touch the DB.
"""
from __future__ import annotations

from collections import defaultdict


def team_offense_defense(
    games: list[dict],
    team_id: int,
) -> tuple[float, float]:
    """Mean points scored and points allowed by ``team_id`` over ``games``.

    Returns ``(offensive_strength, defensive_weakness)``:

    * ``offensive_strength`` = mean points scored by ``team_id`` across
      every game in ``games`` where it appeared and both scores are set.
    * ``defensive_weakness`` = mean points allowed by ``team_id`` across
      that same set of games.

    Out-of-state games and games missing either score are skipped — they
    aren't usable for averaging. Returns ``(0.0, 0.0)`` if the team has
    zero contributing games (cold-start safe).

    No capping: the value of Phase 2e is in the uncapped totals signal
    that capped margin discards.
    """
    scored = 0
    allowed = 0
    n = 0
    for g in games:
        if g.get("is_out_of_state"):
            continue
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        h = g.get("home_team_id")
        a = g.get("away_team_id")
        if h == team_id:
            scored += int(hs)
            allowed += int(as_)
            n += 1
        elif a == team_id:
            scored += int(as_)
            allowed += int(hs)
            n += 1
    if n == 0:
        return 0.0, 0.0
    return float(scored) / float(n), float(allowed) / float(n)


def precompute_team_week_totals(
    games: list[dict],
) -> dict[tuple[int, int], tuple[float, float]]:
    """Build ``{(team_id, week): (offense, defense)}`` aggregated through week.

    For each ``(team, week W)`` the entry holds the team's mean uncapped
    points-scored and points-allowed across every one of its games whose
    ``_engine_week`` is ``<= W``. This is what the runner queries with
    ``W-1`` to get the pre-game signal for a game scheduled in week ``W``
    (signal sees only games strictly before the game being predicted).

    Same densification convention as
    :func:`engine.prediction.features.margin.precompute_team_week_margins`:
    if a team plays in weeks 1 and 3, we still emit entries at weeks 1,
    2, and 3 (week 2 carries the same cumulative value as week 1) so the
    runner can index by any week without missing values.
    """
    if not games:
        return {}

    # First pass: bucket each team's per-game contributions by week.
    per_team_per_week: dict[int, dict[int, list[tuple[int, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    weeks_seen: set[int] = set()
    teams_seen: set[int] = set()

    for g in games:
        if g.get("is_out_of_state"):
            continue
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
        if h is not None:
            # (scored, allowed) from the home team's perspective.
            per_team_per_week[int(h)][w].append((int(hs), int(as_)))
            teams_seen.add(int(h))
        if a is not None:
            # (scored, allowed) from the away team's perspective.
            per_team_per_week[int(a)][w].append((int(as_), int(hs)))
            teams_seen.add(int(a))
        weeks_seen.add(w)

    if not weeks_seen:
        return {}

    min_week = min(weeks_seen)
    max_week = max(weeks_seen)

    out: dict[tuple[int, int], tuple[float, float]] = {}
    for team_id in teams_seen:
        by_week = per_team_per_week[team_id]
        running_scored = 0
        running_allowed = 0
        running_n = 0
        for w in range(min_week, max_week + 1):
            for scored, allowed in by_week.get(w, ()):
                running_scored += scored
                running_allowed += allowed
                running_n += 1
            if running_n > 0:
                out[(team_id, w)] = (
                    float(running_scored) / float(running_n),
                    float(running_allowed) / float(running_n),
                )
    return out
