#!/usr/bin/env python3
"""Ingest LHSAA football game results from lhsaaonline.org (2021-2025).

Fetches all regular-season game results, matches school names to the DB,
creates team records for historical seasons as needed, inserts games, then
runs the power-rating engine and stores weekly ratings in power_ratings.

Usage:
    python scripts/ingest_football_historical.py --dry-run
    python scripts/ingest_football_historical.py --seasons 2025
    python scripts/ingest_football_historical.py --seasons 2021 2022 2023 2024 2025
    python scripts/ingest_football_historical.py --seasons 2025 --skip-ratings
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

import os

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ywlaekkxkwfznwuupggi.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

LHSAA_FORM_URL = (
    "https://www.lhsaaonline.org/pr/fbpr/admin/RptSearchFootballSchedule.asp"
)
LHSAA_REPORT_URL = (
    "https://www.lhsaaonline.org/pr/fbpr/admin/ReportFootballSchedule.asp?p=1"
)

WEEKS = [f"Week {i}" for i in range(1, 11)]

CLASS_TO_DIV = {"5A": "I", "4A": "II", "3A": "III", "2A": "IV", "1A": "V"}

REQUEST_DELAY = 0.5  # seconds between lhsaaonline requests


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    return name.lower().strip()


def match_school(query: str, candidates: dict[str, int], threshold: float = 0.75) -> int | None:
    """Return school_id for query, or None if no match above threshold."""
    q = _normalize(query)
    for name, sid in candidates.items():
        if _normalize(name) == q:
            return sid
    best_score, best_id = 0.0, None
    for name, sid in candidates.items():
        score = SequenceMatcher(None, q, _normalize(name)).ratio()
        if score > best_score and score >= threshold:
            best_score = score
            best_id = sid
    return best_id


# ---------------------------------------------------------------------------
# lhsaaonline scraping
# ---------------------------------------------------------------------------

def fetch_week_games(session: httpx.Client, year: int, week: str) -> list[dict]:
    """Fetch one week's game rows from lhsaaonline.org. Returns raw row dicts."""
    data = {
        "y": str(year), "w": week, "n": "", "d": "", "f": "",
        "resultdate": "", "tbd": "-1", "s": "", "n1": "", "d1": "", "y1": "",
    }
    r = session.post(LHSAA_REPORT_URL, data=data,
                     headers={"Referer": LHSAA_FORM_URL}, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 3:
        return []

    rows = tables[2].find_all("tr")[1:]  # skip header row
    results = []
    for row in rows:
        cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        if len(cols) < 11:
            continue
        school, week_str, date_str, opponent, _loc, class_, district, ha, oos, wl, score = cols[:11]

        # Skip unplayed games
        if not score or not wl or wl.strip() == "":
            continue

        results.append({
            "school": school.strip(),
            "week_str": week_str.strip(),
            "date_str": date_str.strip(),
            "opponent": opponent.strip(),
            "class_": class_.strip(),
            "district": district.strip(),
            "home_away": ha.strip().upper(),
            "is_oos": oos.strip().lower() == "yes",
            "wl": wl.strip(),
            "score": score.strip(),
        })
    return results


def parse_scores(score_str: str, is_home: bool) -> tuple[int | None, int | None]:
    """
    score_str is always 'my_score-opponent_score' from the reporting school's view.
    Returns (home_score, away_score).
    """
    # Handle forfeit notation like "2-0" or plain scores
    score_str = score_str.replace("(f)", "").strip()
    parts = score_str.split("-")
    if len(parts) != 2:
        return None, None
    try:
        my_score, opp_score = int(parts[0]), int(parts[1])
    except ValueError:
        return None, None

    if is_home:
        return my_score, opp_score  # reporting school is home
    else:
        return opp_score, my_score  # reporting school is away; flip


def is_forfeit(wl: str) -> bool:
    return "(f)" in wl.lower()


def deduplicate_games(rows: list[dict]) -> list[dict]:
    """
    lhsaaonline returns one row per team per game — deduplicate to one per game.
    Keep the 'Home' (H) row; synthesize from Away row if Home not present.
    """
    # Key: frozenset of both names + date (independent of home/away ordering)
    seen: dict[tuple, dict] = {}
    for row in rows:
        key = (min(row["school"], row["opponent"]),
               max(row["school"], row["opponent"]),
               row["date_str"])
        if key not in seen:
            seen[key] = row
        else:
            # Prefer the Home row
            if row["home_away"] == "H":
                seen[key] = row
    return list(seen.values())


def week_number(week_str: str) -> int | None:
    """'Week 3' -> 3"""
    parts = week_str.strip().split()
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return None


def parse_date(date_str: str) -> str | None:
    """'9/5/2025' -> '2025-09-05'"""
    try:
        return datetime.strptime(date_str, "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# DB helpers (Supabase Python client)
# ---------------------------------------------------------------------------

def load_schools(sb) -> dict[str, int]:
    """name -> school_id"""
    res = sb.table("schools").select("id,name").execute()
    return {r["name"]: r["id"] for r in res.data}


def load_teams(sb, sport_id: int) -> dict[tuple[int, int], int]:
    """(school_id, season_year) -> team_id"""
    res = sb.table("teams").select("id,school_id,season_year").eq("sport_id", sport_id).execute()
    return {(r["school_id"], r["season_year"]): r["id"] for r in res.data}


def get_or_create_team(sb, school_id: int, sport_id: int, season_year: int,
                       division: str, select_status: str,
                       team_cache: dict, dry_run: bool) -> int | None:
    """Return team_id, creating a new team record if needed."""
    key = (school_id, season_year)
    if key in team_cache:
        return team_cache[key]

    if dry_run:
        print(f"  [dry-run] Would create team: school_id={school_id} "
              f"sport_id={sport_id} year={season_year} div={division} sel={select_status}")
        return None

    res = sb.table("teams").insert({
        "school_id": school_id,
        "sport_id": sport_id,
        "season_year": season_year,
        "division": division,
        "select_status": select_status,
    }).execute()
    if res.data:
        tid = res.data[0]["id"]
        team_cache[key] = tid
        return tid
    return None


# ---------------------------------------------------------------------------
# Power rating calculation
# ---------------------------------------------------------------------------

def calculate_and_store_ratings(sb, sport_id: int, season_year: int,
                                 team_cache: dict[tuple, int],
                                 dry_run: bool):
    """Load games from DB for this season, run engine, upsert power_ratings."""
    from engine.power_rating import calculate_all_ratings
    from engine.types import TeamRecord, GameResult, GameStatus

    print(f"\n  Calculating power ratings for {season_year} football...")

    # Load all final games for this season — paginate past PostgREST's 1000-row default
    all_games = []
    page_size = 1000
    offset = 0
    while True:
        res = sb.table("games").select(
            "id,home_team_id,away_team_id,home_score,away_score,week_number,status,is_out_of_state"
        ).eq("sport_id", sport_id).eq("season_year", season_year).range(offset, offset + page_size - 1).execute()
        if not res.data:
            break
        all_games.extend(res.data)
        if len(res.data) < page_size:
            break
        offset += page_size

    if not all_games:
        print("  No games found — skipping rating calculation.")
        return

    print(f"  Loaded {len(all_games)} games from DB.")

    # Build inverse team cache: team_id -> (school_id, season_year)
    inv_team = {v: k for k, v in team_cache.items() if k[1] == season_year}

    # Load school info for classification/division
    all_team_ids = set()
    for g in all_games:
        all_team_ids.add(g["home_team_id"])
        all_team_ids.add(g["away_team_id"])

    teams_res = sb.table("teams").select(
        "id,school_id,division,select_status"
    ).in_("id", list(all_team_ids)).execute()
    team_info = {r["id"]: r for r in teams_res.data}

    # Load school names
    school_ids = list({r["school_id"] for r in teams_res.data})
    schools_res = sb.table("schools").select("id,name,classification").in_("id", school_ids).execute()
    school_info = {r["id"]: r for r in schools_res.data}

    # Build TeamRecord objects
    team_records: dict[int, TeamRecord] = {}
    for tid, tinfo in team_info.items():
        sid = tinfo["school_id"]
        sch = school_info.get(sid, {})
        team_records[tid] = TeamRecord(
            team_id=tid,
            school_name=sch.get("name", f"school_{sid}"),
            division=tinfo.get("division") or CLASS_TO_DIV.get(sch.get("classification", "5A"), "I"),
            classification=sch.get("classification", "5A"),
            wins=0,
            losses=0,
        )

    # Build GameResult objects (using engine types)
    game_results: list[GameResult] = []
    for g in all_games:
        if g.get("is_out_of_state"):
            continue
        if g["home_score"] is None or g["away_score"] is None:
            continue
        status = GameStatus.FINAL if g["status"] == "final" else GameStatus.SCHEDULED
        game_results.append(GameResult(
            game_id=g["id"],
            home_team_id=g["home_team_id"],
            away_team_id=g["away_team_id"],
            home_score=g["home_score"],
            away_score=g["away_score"],
            status=status,
            week_number=g["week_number"],
        ))

    if not game_results:
        print("  No valid game results — skipping.")
        return

    print(f"  Running engine on {len(game_results)} games, {len(team_records)} teams...")
    updated = calculate_all_ratings(team_records, game_results)

    # Compute ranks per division+select bracket
    from collections import defaultdict
    brackets: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for tid, rec in updated.items():
        bracket = f"{rec.division}"
        brackets[bracket].append((rec.power_rating, tid))

    ranks: dict[int, tuple[int, int]] = {}  # tid -> (rank, total)
    for bracket, entries in brackets.items():
        entries.sort(reverse=True)
        total = len(entries)
        for rank, (_, tid) in enumerate(entries, start=1):
            ranks[tid] = (rank, total)

    # Find the max week_number in the games (to label the rating snapshot)
    max_week = max((g["week_number"] or 0) for g in all_games)

    # Build upsert payload
    ratings_payload = []
    for tid, rec in updated.items():
        rank, total = ranks.get(tid, (0, 0))
        ratings_payload.append({
            "team_id": tid,
            "week_number": max_week,
            "season_year": season_year,
            "power_rating": round(float(rec.power_rating), 2),
            "strength_factor": round(float(rec.strength_factor), 2),
            "rank_in_division": rank,
            "total_teams_in_division": total,
        })

    if dry_run:
        print(f"  [dry-run] Would upsert {len(ratings_payload)} power rating rows.")
        sample = sorted(ratings_payload, key=lambda r: r["power_rating"], reverse=True)[:5]
        for r in sample:
            print(f"    team_id={r['team_id']} rating={r['power_rating']} "
                  f"rank={r['rank_in_division']}/{r['total_teams_in_division']}")
        return

    print(f"  Upserting {len(ratings_payload)} power rating rows...")
    # Batch into chunks of 200
    for i in range(0, len(ratings_payload), 200):
        chunk = ratings_payload[i:i+200]
        sb.table("power_ratings").upsert(
            chunk, on_conflict="team_id,week_number,season_year"
        ).execute()
    print(f"  Done. Top 3: {sorted(ratings_payload, key=lambda r: r['power_rating'], reverse=True)[:3]}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(seasons: list[int], dry_run: bool, skip_ratings: bool):
    from supabase import create_client
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY env var not set — get it from Supabase Dashboard → Project Settings → API")
    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    print("Loading schools and teams from DB...")
    school_name_to_id = load_schools(sb)
    FOOTBALL_SPORT_ID = next(
        r["id"] for r in sb.table("sports").select("id,name").execute().data
        if r["name"] == "Football"
    )
    team_cache = load_teams(sb, FOOTBALL_SPORT_ID)
    print(f"  {len(school_name_to_id)} schools, {len(team_cache)} existing team records")

    unmatched_schools: set[str] = set()
    total_inserted = 0

    with httpx.Client(follow_redirects=True, timeout=30) as session:
        for season_year in seasons:
            print(f"\n{'='*60}")
            print(f"Season: {season_year} football")
            print(f"{'='*60}")

            season_games: list[dict] = []

            for week in WEEKS:
                print(f"  Fetching {week}...", end=" ", flush=True)
                try:
                    rows = fetch_week_games(session, season_year, week)
                except Exception as e:
                    print(f"ERROR: {e}")
                    continue

                unique_rows = deduplicate_games(rows)
                print(f"{len(unique_rows)} unique games", flush=True)
                season_games.extend(unique_rows)
                time.sleep(REQUEST_DELAY)

            print(f"\n  Total unique games scraped: {len(season_games)}")

            # Build game records for DB insertion
            games_to_insert: list[dict] = []
            for row in season_games:
                school_name = row["school"]
                opp_name = row["opponent"]
                is_home = row["home_away"] == "H"

                # Match school names to DB
                school_id = match_school(school_name, school_name_to_id)
                opp_id = match_school(opp_name, school_name_to_id)

                if school_id is None:
                    unmatched_schools.add(school_name)
                    continue
                if opp_id is None:
                    # Out-of-state or unknown opponent — skip game
                    if not row["is_oos"]:
                        unmatched_schools.add(opp_name)
                    continue

                # Determine home/away school
                if is_home:
                    home_school_id, away_school_id = school_id, opp_id
                    home_class = row["class_"]
                    away_class = row["class_"]  # lhsaaonline only shows reporter's class
                else:
                    home_school_id, away_school_id = opp_id, school_id
                    home_class = row["class_"]
                    away_class = row["class_"]

                home_div = CLASS_TO_DIV.get(home_class, "I")
                away_div = CLASS_TO_DIV.get(away_class, "I")

                # Get or create team records for this season
                home_team_id = get_or_create_team(
                    sb, home_school_id, FOOTBALL_SPORT_ID, season_year,
                    home_div, "Non-Select", team_cache, dry_run
                )
                away_team_id = get_or_create_team(
                    sb, away_school_id, FOOTBALL_SPORT_ID, season_year,
                    away_div, "Non-Select", team_cache, dry_run
                )

                if home_team_id is None or away_team_id is None:
                    continue

                home_score, away_score = parse_scores(row["score"], is_home)
                if home_score is None:
                    continue

                wk = week_number(row["week_str"])
                gdate = parse_date(row["date_str"])

                games_to_insert.append({
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "sport_id": FOOTBALL_SPORT_ID,
                    "season_year": season_year,
                    "game_date": gdate,
                    "week_number": wk,
                    "home_score": home_score,
                    "away_score": away_score,
                    "status": "final",
                    "is_district": False,
                    "is_playoff": False,
                    "is_championship": False,
                    "is_out_of_state": row["is_oos"],
                    "source": "lhsaaonline",
                })

            print(f"  Games ready to insert: {len(games_to_insert)}")

            if dry_run:
                print(f"  [dry-run] Would insert {len(games_to_insert)} games.")
                if games_to_insert:
                    print(f"  Sample game: {games_to_insert[0]}")
            else:
                print(f"  Inserting {len(games_to_insert)} games in batches...")
                for i in range(0, len(games_to_insert), 200):
                    chunk = games_to_insert[i:i+200]
                    sb.table("games").insert(chunk).execute()
                    print(f"    Inserted batch {i//200 + 1} ({len(chunk)} rows)")
                total_inserted += len(games_to_insert)
                print(f"  Season {season_year}: {len(games_to_insert)} games inserted.")

            if not skip_ratings and not dry_run:
                calculate_and_store_ratings(sb, FOOTBALL_SPORT_ID, season_year,
                                            team_cache, dry_run)
            elif not skip_ratings and dry_run:
                calculate_and_store_ratings(sb, FOOTBALL_SPORT_ID, season_year,
                                            team_cache, dry_run)

    # Summary
    print(f"\n{'='*60}")
    print(f"DONE. Total games inserted: {total_inserted}")
    if unmatched_schools:
        print(f"\nUnmatched schools ({len(unmatched_schools)}) — these games were skipped:")
        for name in sorted(unmatched_schools):
            print(f"  - {name!r}")


def main():
    parser = argparse.ArgumentParser(description="Ingest LHSAA football game history")
    parser.add_argument("--seasons", nargs="+", type=int,
                        default=[2021, 2022, 2023, 2024, 2025],
                        help="Season years to ingest (e.g. 2021 2022 2025)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be inserted without writing to DB")
    parser.add_argument("--skip-ratings", action="store_true",
                        help="Skip power rating calculation after game insertion")
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"PrepRank Football History Ingest")
    print(f"Seasons: {args.seasons}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    run(args.seasons, args.dry_run, args.skip_ratings)


if __name__ == "__main__":
    main()
