"""Phase 4c feature: log-compressed historical scoring margin (Δf_margin, β₃).

Per `docs/model_specification.md` §"Δf_margin — log-compressed historical
scoring margin":

    f_margin(t, y, w) = mean over team t's games in [season_start, week w-1] of:
                           sign(team_score - opp_score) · ln(|team_score - opp_score| + 1)

    Δf_margin(g) = f_margin(h, y, w) − f_margin(a, y, w)

The log compression mutes blowouts without discarding them: a 49-7 win
contributes ln(43) ≈ 3.76 vs a 21-14 win's ln(8) ≈ 2.08. Informative
ordering, not hostage to runaway scores. No scale parameter needed
because β₃ absorbs it.

Distinct from `features.margin.precompute_team_week_margins` (legacy
v1 capped-mean) and `features.recent_form.precompute_team_week_form`
(v1-era recency-weighted). This is the v2-spec-compliant feature for
the β₃ slot in `predict_game_v3` and is consumed by the Phase 4c
ablation runner.

Temporal-boundary contract matches the existing per-week precomputes:
``out[(team_id, w)]`` holds the cumulative log-margin signal across all
of team_id's games with ``_engine_week <= w``. The runner queries with
``W-1`` to get the strictly-before-the-game signal. The lookup is dense
in W (week 2 carries the same value as week 1 if no games landed in
week 2) so the runner can index by any week without missing values.
"""
from __future__ import annotations

import math
from collections import defaultdict


def log_compressed_margin(home_score: int, away_score: int) -> float:
    """Signed log-compressed margin from the home team's perspective.

    ``sign(s_h - s_a) · ln(|s_h - s_a| + 1)``. Returns 0.0 for a tie.
    No per-sport cap (the log itself bounds the influence of blowouts).
    """
    raw = int(home_score) - int(away_score)
    if raw == 0:
        return 0.0
    return float(math.copysign(math.log(abs(raw) + 1), raw))


def team_log_margin_signal(
    games: list[dict],
    team_id: int,
) -> float:
    """Mean log-compressed margin per game, signed from ``team_id``'s POV.

    Each game contributes ``+log_compressed_margin`` if ``team_id`` was
    the home side, ``-log_compressed_margin`` if they were away, and is
    skipped if the team did not play in it or the row is missing a
    score. Returns ``0.0`` for a team with zero contributing games
    (cold-start safe).

    This is the function-level (whole-history) signal. For pre-game
    per-week lookups, use :func:`precompute_team_week_log_margins`.
    """
    total = 0.0
    n = 0
    for g in games:
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        h = g.get("home_team_id")
        a = g.get("away_team_id")
        if h == team_id:
            total += log_compressed_margin(hs, as_)
            n += 1
        elif a == team_id:
            total += -log_compressed_margin(hs, as_)
            n += 1
    if n == 0:
        return 0.0
    return total / float(n)


def precompute_team_week_log_margins(
    games: list[dict],
) -> dict[tuple[int, int], float]:
    """Build a ``{(team_id, week): cumulative_mean_log_margin}`` lookup.

    Cumulative mean log-compressed margin across every one of the team's
    games whose ``_engine_week <= W``, signed from the team's POV. The
    runner queries with ``(team_id, W-1)`` for the strictly-before
    pre-game signal.

    Cold-start safe: a team with no contributing games gets no entry in
    the dict; the runner's default ``form.get((team_id, W-1), 0.0)``
    pattern handles the miss.

    Dense in W between min_week and max_week_seen so the runner can
    index by any intermediate week.
    """
    if not games:
        return {}

    # Bucket each team's per-week contributions, signed from that team's POV.
    per_team_per_week: dict[int, dict[int, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    weeks_seen: set[int] = set()
    teams_seen: set[int] = set()

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
        m = log_compressed_margin(hs, as_)
        if h is not None:
            per_team_per_week[h][w].append(m)
            teams_seen.add(h)
        if a is not None:
            per_team_per_week[a][w].append(-m)
            teams_seen.add(a)
        weeks_seen.add(w)

    if not weeks_seen:
        return {}

    min_week = min(weeks_seen)
    max_week = max(weeks_seen)

    out: dict[tuple[int, int], float] = {}
    for team_id in teams_seen:
        by_week = per_team_per_week[team_id]
        running_sum = 0.0
        running_n = 0
        for w in range(min_week, max_week + 1):
            for m in by_week.get(w, ()):
                running_sum += m
                running_n += 1
            if running_n > 0:
                out[(team_id, w)] = running_sum / float(running_n)
    return out
