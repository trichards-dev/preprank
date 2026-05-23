#!/usr/bin/env python3
"""Backfill weekly engine power ratings for every (sport, season) pair.

For each (sport, season):
  1. Wipe existing source='engine' rows for that sport-season.
  2. Load all games. For football, use the stored week_number. For other
     sports (week_number is NULL on games), derive a synthetic week from
     game_date: week 1 = first 7 days from min(game_date), and so on.
  3. For W = 1..max_week, run calculate_all_ratings() on games where
     derived_week <= W and status in (final, forfeit), and upsert ~N
     rows (one per team) tagged source='engine', week_number=W.

The engine is a pure function of (teams, games), so each weekly run is
independent — no state carries forward.

Usage:
    python scripts/backfill_weekly_engine_ratings.py --dry-run
    python scripts/backfill_weekly_engine_ratings.py --only-sport Football
    python scripts/backfill_weekly_engine_ratings.py --only-season 2025
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, datetime

from supabase import create_client

# packages/engine is installed as `engine` in the venv via pip install -e
from engine.power_rating import calculate_all_ratings
from engine.types import GameResult, GameStatus, TeamRecord


SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ywlaekkxkwfznwuupggi.supabase.co")
CLASS_TO_DIV = {"5A": "I", "4A": "II", "3A": "III", "2A": "IV", "1A": "V", "B": "V", "C": "V"}

# Sports to process. Names must match `sports.name` in the DB.
SPORTS = [
    "Football",
    "Volleyball",
    "Boys Basketball",
    "Girls Basketball",
    "Baseball",
    "Softball",
    "Boys Soccer",
    "Girls Soccer",
]
SEASONS = [2021, 2022, 2023, 2024, 2025]

# Upper bound on the derived weekly index per sport. Games whose game_date
# implies a week beyond this are treated as data outliers and dropped from
# the engine input. Real LHSAA seasons fit comfortably under these caps.
MAX_WEEKS_BY_SPORT = {
    "Football": 16,
    "Volleyball": 14,
    "Boys Basketball": 18,
    "Girls Basketball": 18,
    "Baseball": 14,
    "Softball": 14,
    "Boys Soccer": 16,
    "Girls Soccer": 16,
}


def _parse_date(d: str | None) -> date | None:
    if not d:
        return None
    try:
        return datetime.fromisoformat(d[:10]).date()
    except (ValueError, TypeError):
        return None


def _derive_week(game_date: date | None, season_start: date | None) -> int | None:
    if game_date is None or season_start is None:
        return None
    delta = (game_date - season_start).days
    if delta < 0:
        return 1
    return delta // 7 + 1


def _load_sport_id(sb, sport_name: str) -> int | None:
    res = sb.table("sports").select("id,name").ilike("name", sport_name).execute()
    return res.data[0]["id"] if res.data else None


def _load_games(sb, sport_id: int, season_year: int) -> list[dict]:
    out: list[dict] = []
    offset, page = 0, 1000
    while True:
        res = (sb.table("games")
               .select("id,home_team_id,away_team_id,home_score,away_score,"
                       "week_number,status,is_out_of_state,game_date")
               .eq("sport_id", sport_id).eq("season_year", season_year)
               .range(offset, offset + page - 1).execute())
        if not res.data:
            break
        out.extend(res.data)
        if len(res.data) < page:
            break
        offset += page
    return out


def _load_teams_for_games(sb, games: list[dict]) -> tuple[dict[int, dict], dict[int, dict]]:
    team_ids = list({g["home_team_id"] for g in games if g.get("home_team_id")} |
                    {g["away_team_id"] for g in games if g.get("away_team_id")})
    if not team_ids:
        return {}, {}
    teams_res = (sb.table("teams")
                 .select("id,school_id,division,select_status,season_year,sport_id")
                 .in_("id", team_ids).execute())
    teams = {r["id"]: r for r in teams_res.data}

    school_ids = list({r["school_id"] for r in teams_res.data if r.get("school_id")})
    if school_ids:
        schools_res = (sb.table("schools")
                       .select("id,name,classification")
                       .in_("id", school_ids).execute())
        schools = {r["id"]: r for r in schools_res.data}
    else:
        schools = {}
    return teams, schools


def _build_team_records(teams: dict[int, dict], schools: dict[int, dict]) -> dict[int, TeamRecord]:
    records: dict[int, TeamRecord] = {}
    for tid, t in teams.items():
        sch = schools.get(t.get("school_id"), {})
        div = t.get("division") or CLASS_TO_DIV.get(sch.get("classification", "5A"), "I")
        records[tid] = TeamRecord(
            team_id=tid,
            school_name=sch.get("name", f"sid:{t.get('school_id')}"),
            division=div,
            classification=sch.get("classification", "5A"),
            wins=0, losses=0,
        )
    return records


def _build_game_results(games_for_week: list[dict]) -> list[GameResult]:
    out: list[GameResult] = []
    for g in games_for_week:
        if g.get("is_out_of_state"):
            continue
        if g.get("home_score") is None or g.get("away_score") is None:
            continue
        if g.get("status") not in ("final", "forfeit"):
            continue
        out.append(GameResult(
            game_id=g["id"],
            home_team_id=g["home_team_id"],
            away_team_id=g["away_team_id"],
            home_score=g["home_score"],
            away_score=g["away_score"],
            status=GameStatus.FINAL,
            week_number=g.get("_engine_week"),
        ))
    return out


def _wipe_engine_rows(sb, team_ids: list[int], season_year: int, dry_run: bool) -> int:
    """DELETE FROM power_ratings WHERE source='engine' AND season_year=Y AND team_id IN (...)"""
    if dry_run or not team_ids:
        return 0
    # Supabase REST limits `in` filter list size; chunk to be safe.
    deleted = 0
    for i in range(0, len(team_ids), 500):
        chunk = team_ids[i : i + 500]
        res = (sb.table("power_ratings").delete()
               .eq("source", "engine").eq("season_year", season_year)
               .in_("team_id", chunk).execute())
        deleted += len(res.data) if res.data else 0
    return deleted


def _insert_ratings(sb, rows: list[dict], dry_run: bool) -> int:
    """Plain INSERT — we DELETE all engine rows for the (sport, season) first,
    so there's no conflict to handle. Avoids the partial-unique-index ON CONFLICT
    inference issue (Supabase REST can't pass the WHERE predicate Postgres needs).
    """
    if dry_run or not rows:
        return 0
    written = 0
    for i in range(0, len(rows), 200):
        batch = rows[i : i + 200]
        sb.table("power_ratings").insert(batch).execute()
        written += len(batch)
    return written


def process_sport_season(sb, sport_name: str, season_year: int, dry_run: bool) -> dict:
    """Returns a summary dict for the report writer."""
    sport_id = _load_sport_id(sb, sport_name)
    if sport_id is None:
        print(f"  [skip] Unknown sport: {sport_name!r}")
        return {"sport": sport_name, "season": season_year, "status": "skip", "reason": "no sport_id"}

    games = _load_games(sb, sport_id, season_year)
    if not games:
        print(f"  No games for {sport_name} {season_year} — skipping.")
        return {"sport": sport_name, "season": season_year, "status": "skip", "reason": "no games"}

    # Filter to final/forfeit, with valid scores
    games = [g for g in games
             if g.get("status") in ("final", "forfeit")
             and g.get("home_score") is not None
             and g.get("away_score") is not None
             and not g.get("is_out_of_state")]
    if not games:
        return {"sport": sport_name, "season": season_year, "status": "skip", "reason": "no playable games"}

    # Derive engine_week per game
    if sport_name == "Football":
        for g in games:
            g["_engine_week"] = g.get("week_number")
    else:
        dates = [_parse_date(g.get("game_date")) for g in games]
        valid_dates = sorted(d for d in dates if d is not None)
        if not valid_dates:
            return {"sport": sport_name, "season": season_year, "status": "skip",
                    "reason": "no parseable game_date"}
        # 5th-percentile date as season_start — robust to a handful of misdated games
        idx = len(valid_dates) // 20  # 5th percentile
        season_start = valid_dates[idx] if len(valid_dates) >= 20 else valid_dates[0]
        max_week_cap = MAX_WEEKS_BY_SPORT.get(sport_name, 20)
        outliers = 0
        for g in games:
            w = _derive_week(_parse_date(g.get("game_date")), season_start)
            if w is None:
                g["_engine_week"] = None
            elif w < 1:
                g["_engine_week"] = 1  # clamp early outliers to week 1
            elif w > max_week_cap:
                g["_engine_week"] = None  # drop late outliers
                outliers += 1
            else:
                g["_engine_week"] = w
        if outliers:
            print(f"    Dropped {outliers} games with out-of-range game_date (likely data errors)")

    games = [g for g in games if g.get("_engine_week") is not None and g["_engine_week"] >= 1]
    if not games:
        return {"sport": sport_name, "season": season_year, "status": "skip",
                "reason": "no games after outlier filter"}
    max_week = max(g["_engine_week"] for g in games)

    teams, schools = _load_teams_for_games(sb, games)
    team_records = _build_team_records(teams, schools)
    team_ids = list(team_records.keys())

    print(f"  {sport_name} {season_year}: {len(games)} games, {len(team_records)} teams, max_week={max_week}")

    deleted = _wipe_engine_rows(sb, team_ids, season_year, dry_run)
    if not dry_run:
        print(f"    Wiped {deleted} prior engine rows.")

    total_written = 0
    weeks_with_data = 0
    for w in range(1, max_week + 1):
        games_for_week = [g for g in games if g["_engine_week"] <= w]
        if not games_for_week:
            continue
        game_results = _build_game_results(games_for_week)
        if not game_results:
            continue

        updated = calculate_all_ratings(team_records, game_results)
        if not updated:
            continue

        # Rank within division
        by_div: dict[str, list[tuple[float, int]]] = defaultdict(list)
        for tid, rec in updated.items():
            by_div[rec.division].append((rec.power_rating, tid))

        ranks: dict[int, tuple[int, int]] = {}
        for div, entries in by_div.items():
            entries.sort(reverse=True)
            total = len(entries)
            for r, (_, tid) in enumerate(entries, start=1):
                ranks[tid] = (r, total)

        payload = []
        for tid, rec in updated.items():
            rank, total = ranks.get(tid, (0, 0))
            payload.append({
                "team_id": tid,
                "week_number": w,
                "season_year": season_year,
                "power_rating": round(float(rec.power_rating), 4),
                "strength_factor": round(float(rec.strength_factor), 4),
                "rank_in_division": rank,
                "total_teams_in_division": total,
                "source": "engine",
            })

        written = _insert_ratings(sb, payload, dry_run)
        total_written += written if not dry_run else len(payload)
        weeks_with_data += 1

    return {
        "sport": sport_name, "season": season_year, "status": "ok",
        "max_week": max_week, "weeks_with_data": weeks_with_data,
        "teams": len(team_records), "rows_written": total_written,
        "rows_deleted": deleted,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only-sport", default=None)
    p.add_argument("--only-season", type=int, default=None)
    args = p.parse_args()

    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not service_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY env var is required")
    sb = create_client(SUPABASE_URL, service_key)

    sports = [args.only_sport] if args.only_sport else SPORTS
    seasons = [args.only_season] if args.only_season else SEASONS

    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Backfilling {len(sports)} sports × {len(seasons)} seasons")
    print()

    summaries: list[dict] = []
    for sport in sports:
        for season in seasons:
            print(f"=== {sport} {season} ===")
            try:
                summary = process_sport_season(sb, sport, season, args.dry_run)
            except Exception as e:
                print(f"    ERROR: {e}")
                summaries.append({"sport": sport, "season": season, "status": "error", "error": str(e)})
                continue
            summaries.append(summary)
            if summary["status"] == "ok":
                print(f"    rows_written={summary['rows_written']} (weeks={summary['weeks_with_data']}, teams={summary['teams']})")
            print()

    print("=" * 60)
    print(f"Total sport-seasons processed: {len(summaries)}")
    ok = [s for s in summaries if s["status"] == "ok"]
    print(f"  OK     : {len(ok)}")
    print(f"  Skip   : {sum(1 for s in summaries if s['status'] == 'skip')}")
    print(f"  Errors : {sum(1 for s in summaries if s['status'] == 'error')}")
    if ok:
        total = sum(s["rows_written"] for s in ok)
        print(f"Total rows written: {total}")

    return 0 if not any(s["status"] == "error" for s in summaries) else 1


if __name__ == "__main__":
    sys.exit(main())
