"""Supabase REST data loaders for the validator.

Mirrors the patterns in ``scripts/validate_engine_vs_lhsaa.py`` and
``scripts/backfill_weekly_engine_ratings.py`` so the validator runs against
the same underlying tables (``sports``, ``teams``, ``schools``,
``power_ratings``, ``games``) with the same week-derivation logic.

All readers take a ``supabase.Client`` (called ``sb``) and return plain
Python dicts/lists. None of them mutate the DB.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median

# Upper bound on the derived weekly index per sport. Mirrors
# ``MAX_WEEKS_BY_SPORT`` in ``scripts/backfill_weekly_engine_ratings.py``.
MAX_WEEKS_BY_SPORT: dict[str, int] = {
    "Football": 16,
    "Volleyball": 14,
    "Boys Basketball": 18,
    "Girls Basketball": 18,
    "Baseball": 14,
    "Softball": 14,
    "Boys Soccer": 16,
    "Girls Soccer": 16,
}

ALL_SPORTS: list[str] = list(MAX_WEEKS_BY_SPORT.keys())


# ---------------------------------------------------------------------------
# Date / week helpers (kept lock-step with backfill_weekly_engine_ratings.py)
# ---------------------------------------------------------------------------
def _parse_date(d: str | None) -> date | None:
    if not d:
        return None
    try:
        return datetime.fromisoformat(d[:10]).date()
    except (ValueError, TypeError):
        return None


def derive_game_week(
    game: dict,
    season_start_date: date | None,
    max_week_cap: int,
) -> int | None:
    """Return the synthetic week-index for ``game`` (1-based).

    For Football the stored ``week_number`` is authoritative. For other
    sports the week is derived from ``game_date`` relative to
    ``season_start_date`` with the same logic as the backfill script.

    Returns ``None`` when the game has no usable date or sits past
    ``max_week_cap`` (outlier).
    """
    # If the row already carries a stored week_number, prefer it
    stored = game.get("week_number")
    if stored is not None:
        try:
            w = int(stored)
        except (TypeError, ValueError):
            w = None
        if w is not None and 1 <= w <= max_week_cap:
            return w

    gd = _parse_date(game.get("game_date"))
    if gd is None or season_start_date is None:
        return None
    delta = (gd - season_start_date).days
    if delta < 0:
        return 1
    w = delta // 7 + 1
    if w > max_week_cap:
        return None
    return w


def _season_start_date(games: list[dict]) -> date | None:
    """Pick the 5th-percentile game_date as season-start, like the backfill."""
    dates = sorted(d for d in (_parse_date(g.get("game_date")) for g in games) if d is not None)
    if not dates:
        return None
    if len(dates) < 20:
        return dates[0]
    idx = len(dates) // 20  # 5th percentile
    return dates[idx]


# ---------------------------------------------------------------------------
# REST readers
# ---------------------------------------------------------------------------
def load_sports_map(sb) -> dict[int, str]:
    """sport_id -> sport_name."""
    res = sb.table("sports").select("id,name").execute()
    return {r["id"]: r["name"] for r in res.data}


def load_teams_with_schools(sb) -> dict[int, dict]:
    """team_id -> {school_name, division, classification, season_year, sport_id, select_status}."""
    teams: dict[int, dict] = {}
    offset, page = 0, 1000
    while True:
        res = (
            sb.table("teams")
            .select("id,school_id,division,select_status,season_year,sport_id")
            .range(offset, offset + page - 1)
            .execute()
        )
        if not res.data:
            break
        for r in res.data:
            teams[r["id"]] = r
        if len(res.data) < page:
            break
        offset += page

    school_ids = list({r["school_id"] for r in teams.values() if r.get("school_id")})
    schools: dict[int, dict] = {}
    for i in range(0, len(school_ids), 500):
        chunk = school_ids[i : i + 500]
        res = sb.table("schools").select("id,name,classification").in_("id", chunk).execute()
        for s in res.data:
            schools[s["id"]] = s

    for t in teams.values():
        sch = schools.get(t.get("school_id"), {})
        t["school_name"] = sch.get("name", f"sid:{t.get('school_id')}")
        t["classification"] = sch.get("classification")
    return teams


def _filter_team_ids_for_sport_season(
    teams: dict[int, dict], sport_id: int, season_year: int
) -> set[int]:
    return {
        tid
        for tid, t in teams.items()
        if t.get("sport_id") == sport_id and t.get("season_year") == season_year
    }


def load_engine_ratings(
    sb, sport_id: int, season_year: int, team_ids: set[int] | None = None
) -> dict[tuple[int, int], float]:
    """(team_id, week_number) -> power_rating, filtered to source='engine'.

    The power_ratings table doesn't carry sport_id, so we paginate the season
    rows and (optionally) post-filter to ``team_ids``.
    """
    out: dict[tuple[int, int], float] = {}
    offset, page = 0, 1000
    while True:
        res = (
            sb.table("power_ratings")
            .select("team_id,week_number,power_rating,source,season_year")
            .eq("source", "engine")
            .eq("season_year", season_year)
            .range(offset, offset + page - 1)
            .execute()
        )
        if not res.data:
            break
        for r in res.data:
            tid = r["team_id"]
            if team_ids is not None and tid not in team_ids:
                continue
            w = r.get("week_number")
            if w is None:
                continue
            out[(tid, int(w))] = float(r["power_rating"])
        if len(res.data) < page:
            break
        offset += page
    return out


def load_prior_season_final_ratings(
    sb, sport_id: int, season_year: int, teams_by_sport_season: dict[int, dict] | None = None
) -> dict[int, float]:
    """team_id -> end-of-season engine rating for ``season_year - 1``.

    "End-of-season" = max week_number per team in the prior season.

    The returned dict is keyed by the **current** season's team_id when we
    can identify a same-school + same-sport prior-season team; we map via
    (sport_id, school_id) to handle the fact that team_id is per-season.
    """
    prior_season = season_year - 1

    # Pull all engine rows for the prior season (any sport - filter via teams).
    rows: list[dict] = []
    offset, page = 0, 1000
    while True:
        res = (
            sb.table("power_ratings")
            .select("team_id,week_number,power_rating")
            .eq("source", "engine")
            .eq("season_year", prior_season)
            .range(offset, offset + page - 1)
            .execute()
        )
        if not res.data:
            break
        rows.extend(res.data)
        if len(res.data) < page:
            break
        offset += page

    if not rows:
        return {}

    # Group rows by team and pick the row at the max week_number.
    by_team: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("week_number") is None:
            continue
        by_team[r["team_id"]].append(r)
    prior_finals_by_prior_team: dict[int, float] = {}
    for tid, lst in by_team.items():
        best = max(lst, key=lambda r: int(r["week_number"]))
        prior_finals_by_prior_team[tid] = float(best["power_rating"])

    # If caller didn't pass team-mapping info, return the raw map.
    if teams_by_sport_season is None:
        return prior_finals_by_prior_team

    # Otherwise translate prior-season team_id -> current-season team_id via
    # (sport_id, school_id). We need the prior-season teams' (school_id, sport_id),
    # which we'll fetch lazily from `teams` filtered to the prior season.
    prior_team_ids = list(prior_finals_by_prior_team.keys())
    prior_teams: dict[int, dict] = {}
    for i in range(0, len(prior_team_ids), 500):
        chunk = prior_team_ids[i : i + 500]
        res = (
            sb.table("teams")
            .select("id,school_id,sport_id,season_year")
            .in_("id", chunk)
            .execute()
        )
        for r in res.data:
            prior_teams[r["id"]] = r

    # Build lookup: (sport_id, school_id) -> prior_team_id (only sport_id matches)
    prior_lookup: dict[tuple[int, int], int] = {}
    for ptid, t in prior_teams.items():
        if t.get("sport_id") != sport_id:
            continue
        sch = t.get("school_id")
        if sch is None:
            continue
        prior_lookup[(sport_id, sch)] = ptid

    # Map to current-season team_id
    out: dict[int, float] = {}
    for ctid, t in teams_by_sport_season.items():
        sch = t.get("school_id")
        if sch is None:
            continue
        ptid = prior_lookup.get((sport_id, sch))
        if ptid is None:
            continue
        if ptid in prior_finals_by_prior_team:
            out[ctid] = prior_finals_by_prior_team[ptid]
    return out


def load_games(sb, sport_id: int, season_year: int) -> list[dict]:
    """Final/forfeit games for one (sport, season).

    Returns the raw row dicts with: id, home_team_id, away_team_id,
    home_score, away_score, week_number, status, game_date, is_out_of_state.
    """
    out: list[dict] = []
    offset, page = 0, 1000
    while True:
        res = (
            sb.table("games")
            .select(
                "id,home_team_id,away_team_id,home_score,away_score,"
                "week_number,status,is_out_of_state,game_date"
            )
            .eq("sport_id", sport_id)
            .eq("season_year", season_year)
            .range(offset, offset + page - 1)
            .execute()
        )
        if not res.data:
            break
        out.extend(res.data)
        if len(res.data) < page:
            break
        offset += page

    return [
        g
        for g in out
        if g.get("status") in ("final", "forfeit")
        and g.get("home_score") is not None
        and g.get("away_score") is not None
        and not g.get("is_out_of_state")
    ]


# ---------------------------------------------------------------------------
# High-level: a single dataclass bundling everything one (sport, season) needs.
# ---------------------------------------------------------------------------
@dataclass
class RunInputs:
    sport_id: int
    sport_name: str
    season_year: int
    games: list[dict]              # final/forfeit only, each with _engine_week populated
    engine_ratings: dict[tuple[int, int], float]
    prior_finals: dict[int, float]
    teams: dict[int, dict]         # full teams_with_schools dict (all teams)
    sport_team_ids: set[int]
    division_prior_medians: dict[str, float]   # division -> median prior-season final rating
    max_week_cap: int
    season_start_date: date | None
    end_of_season_engine_ratings: dict[int, float]  # team_id -> latest weekly engine rating


def _final_engine_ratings(
    engine_ratings: dict[tuple[int, int], float], team_ids: set[int]
) -> dict[int, float]:
    by_team_max: dict[int, tuple[int, float]] = {}
    for (tid, w), r in engine_ratings.items():
        if team_ids is not None and tid not in team_ids:
            continue
        prev = by_team_max.get(tid)
        if prev is None or w > prev[0]:
            by_team_max[tid] = (w, r)
    return {tid: r for tid, (_, r) in by_team_max.items()}


def load_run_inputs(
    sb,
    sport_id: int,
    sport_name: str,
    season_year: int,
    teams: dict[int, dict] | None = None,
) -> RunInputs:
    """Assemble everything ``runner.run_validation`` needs for one (sport, season).

    Caller may pass a pre-loaded ``teams`` dict (the full teams map) to avoid
    re-fetching it once per sport-season; otherwise we fetch it here.
    """
    if teams is None:
        teams = load_teams_with_schools(sb)
    sport_team_ids = _filter_team_ids_for_sport_season(teams, sport_id, season_year)
    teams_for_sport_season = {tid: teams[tid] for tid in sport_team_ids}

    games = load_games(sb, sport_id, season_year)
    games = [
        g
        for g in games
        if g.get("home_team_id") in sport_team_ids
        and g.get("away_team_id") in sport_team_ids
    ]

    max_week_cap = MAX_WEEKS_BY_SPORT.get(sport_name, 20)
    season_start = _season_start_date(games)
    for g in games:
        g["_engine_week"] = derive_game_week(g, season_start, max_week_cap)
    games = [g for g in games if g.get("_engine_week") is not None and g["_engine_week"] >= 1]

    engine_ratings = load_engine_ratings(sb, sport_id, season_year, team_ids=sport_team_ids)
    prior_finals = load_prior_season_final_ratings(
        sb, sport_id, season_year, teams_by_sport_season=teams_for_sport_season
    )

    # Division-median fallback for teams with no prior-season rating
    by_div: dict[str, list[float]] = defaultdict(list)
    for tid, r in prior_finals.items():
        div = teams_for_sport_season.get(tid, {}).get("division")
        if div:
            by_div[div].append(r)
    division_prior_medians = {div: float(median(vals)) for div, vals in by_div.items() if vals}

    end_of_season_engine = _final_engine_ratings(engine_ratings, sport_team_ids)

    return RunInputs(
        sport_id=sport_id,
        sport_name=sport_name,
        season_year=season_year,
        games=games,
        engine_ratings=engine_ratings,
        prior_finals=prior_finals,
        teams=teams,
        sport_team_ids=sport_team_ids,
        division_prior_medians=division_prior_medians,
        max_week_cap=max_week_cap,
        season_start_date=season_start,
        end_of_season_engine_ratings=end_of_season_engine,
    )
