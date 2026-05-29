#!/usr/bin/env python3
"""Ingest LHSAA game history for 7 non-football sports (2021-2025).

Scrapes lhsaaonline.org schedule/results pages for:
  Volleyball, Boys Basketball, Girls Basketball, Baseball, Softball,
  Boys Soccer, Girls Soccer

Usage:
    python scripts/ingest_sports_historical.py --dry-run
    python scripts/ingest_sports_historical.py --sports volleyball
    python scripts/ingest_sports_historical.py --sports all
    python scripts/ingest_sports_historical.py --seasons 2024 2025
"""

from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher

import httpx
from bs4 import BeautifulSoup

# Allow "scripts.oos_helper" import when running this file directly (not as a module).
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from scripts.oos_helper import detect_oos_state, get_or_create_oos_school

# ---------------------------------------------------------------------------
# Supabase config
# ---------------------------------------------------------------------------

import os

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ywlaekkxkwfznwuupggi.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# ---------------------------------------------------------------------------
# Sport configs
# ---------------------------------------------------------------------------

@dataclass
class SportConfig:
    name: str
    sport_id: int
    base_url: str
    form_path: str
    report_suffix: str  # e.g. "?p=1" or "?p=1&bb=1"
    year_field: str     # "y" or "yr"
    filter_field: str   # "d"
    filter_values: list[str]  # classes or divisions to query
    years: list[int]
    score_type: str     # "sets", "points", "runs", "goals"
    week_snapshot: int  # week_number to label the rating snapshot
    score_format: str = "perspective"  # "perspective" (default) or "winner_first"

    @property
    def form_url(self) -> str:
        return self.base_url + self.form_path

    @property
    def report_url(self) -> str:
        return self.base_url + "ReportSchedule.asp" + self.report_suffix

    @property
    def division_filter(self) -> bool:
        """True if filter_values are divisions (I/II/…), False if classes (5A/4A/…)."""
        return self.filter_values[0] in ("I", "II", "III", "IV", "V")


# DEPRECATED 2026-05-25: phantom Div V trace identified CLASS_TO_DIV as the
# root cause of fleet-wide division mis-labelling. teams.division now comes
# from LHSAA PDFs via scripts/refresh_team_divisions.py — NEVER inferred
# from school classification. Kept only for the extract_division() function
# below that's invoked by legacy callers; do not introduce new uses.
CLASS_TO_DIV = {"5A": "I", "4A": "II", "3A": "III", "2A": "IV", "1A": "V", "B": "V", "C": "V"}

SPORTS: dict[str, SportConfig] = {
    "volleyball": SportConfig(
        name="Volleyball", sport_id=2,
        base_url="https://www.lhsaaonline.org/pr/vbpr/admin/",
        form_path="SearchVolleyballSchedule.asp",
        report_suffix="?p=1",
        year_field="y", filter_field="d",
        filter_values=["I", "II", "III", "IV", "V"],
        years=[2021, 2022, 2023, 2024, 2025],
        score_type="sets", week_snapshot=12,
    ),
    "boys_basketball": SportConfig(
        name="Boys Basketball", sport_id=5,
        base_url="https://www.lhsaaonline.org/pr/bbpr/admin/",
        form_path="SearchBoysBasketballSchedule.asp",
        report_suffix="?p=1&bb=1",
        year_field="yr", filter_field="d",
        filter_values=["5A", "4A", "3A", "2A", "1A"],
        years=[2021, 2022, 2023, 2024, 2025],
        score_type="points", week_snapshot=20,
    ),
    "girls_basketball": SportConfig(
        name="Girls Basketball", sport_id=6,
        base_url="https://www.lhsaaonline.org/pr/bbpr/admin/",
        form_path="SearchGirlsBasketballSchedule.asp",
        report_suffix="?p=1&bb=2",
        year_field="yr", filter_field="d",
        filter_values=["5A", "4A", "3A", "2A", "1A"],
        years=[2021, 2022, 2023, 2024, 2025],
        score_type="points", week_snapshot=20,
    ),
    "baseball": SportConfig(
        name="Baseball", sport_id=11,
        base_url="https://www.lhsaaonline.org/pr/bpr/admin/",
        form_path="SearchBaseballSchedule.asp",
        report_suffix="?p=1&bb=1",
        year_field="y", filter_field="d",
        filter_values=["5A", "4A", "3A", "2A", "1A"],
        years=[2021, 2022, 2023, 2024, 2025],
        score_type="runs", week_snapshot=14,
        # 2026-05-25: baseball page format is winner_first, not perspective.
        # Phase 0 audit showed 87.6% home-win rate vs ~54% for other sports.
        # Forensic analysis (see decisions.md 2026-05-24 entry) traced this
        # to parse_scores treating "X-Y" as my_score-opp_score when LHSAA's
        # baseball pages actually publish it as winner_score-loser_score.
        score_format="winner_first",
    ),
    "softball": SportConfig(
        name="Softball", sport_id=12,
        base_url="https://www.lhsaaonline.org/pr/sbpr/admin/",
        form_path="SearchSoftballSchedule.asp",
        report_suffix="?p=1&bb=2",
        year_field="y", filter_field="d",
        filter_values=["5A", "4A", "3A", "2A", "1A"],
        years=[2021, 2022, 2023, 2024, 2025],
        score_type="runs", week_snapshot=14,
    ),
    "boys_soccer": SportConfig(
        name="Boys Soccer", sport_id=13,
        base_url="https://www.lhsaaonline.org/pr/sopr/admin/",
        form_path="SearchboyssoccerSchedule.asp",
        report_suffix="?p=1&so=1",
        year_field="yr", filter_field="d",
        filter_values=["5A", "4A", "3A", "2A", "1A"],
        years=[2021, 2022, 2023, 2024, 2025],
        score_type="goals", week_snapshot=15,
    ),
    "girls_soccer": SportConfig(
        name="Girls Soccer", sport_id=14,
        base_url="https://www.lhsaaonline.org/pr/sopr/admin/",
        form_path="SearchgirlssoccerSchedule.asp",
        report_suffix="?p=1&so=2",
        year_field="yr", filter_field="d",
        filter_values=["5A", "4A", "3A", "2A", "1A"],
        years=[2021, 2022, 2023, 2024, 2025],
        score_type="goals", week_snapshot=15,
    ),
}

REQUEST_DELAY = 0.4


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    return name.lower().strip()


def match_school(query: str, candidates: dict[str, int], threshold: float = 0.75) -> int | None:
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
# HTML scraping
# ---------------------------------------------------------------------------

# Fixed column indices for data rows. lhsaaonline returns one table per school;
# each data row always has the same structure regardless of table header format.
# 12-col schema: volleyball, baseball, softball, soccer
# 13-col schema: basketball (has OT column between Win/Loss and Score)
_SCHEMA_12 = {"school": 1, "dist_div": 2, "date": 3, "opponent": 4, "opp_dist_div": 5,
              "dt_flag": 6, "home_away": 9, "wl": 10, "score": 11}
_SCHEMA_13 = {"school": 1, "dist_div": 2, "date": 3, "opponent": 4, "opp_dist_div": 5,
              "dt_flag": 6, "home_away": 9, "wl": 10, "score": 12}


def fetch_games(session: httpx.Client, cfg: SportConfig, year: int, fval: str) -> list[dict]:
    """Fetch all game rows for one sport/year/filter-value combination.

    lhsaaonline renders one table per school on the results page (sometimes two
    tables per school in different HTML layouts). We collect rows from ALL tables
    that have 'School' and 'Win/Loss' in the header; the dedup pass handles any
    rows that appear in multiple tables.
    """
    data = {
        cfg.year_field: str(year),
        cfg.filter_field: fval,
        "resultdate": "", "n": "", "h": "", "f": "",
    }
    r = session.post(cfg.report_url, data=data,
                     headers={"Referer": cfg.form_url}, timeout=60)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    results = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [td.get_text(strip=True) for td in rows[0].find_all(["td", "th"])]
        # 'Win/Loss' for most sports; 'Win/Loss/Tie' for baseball/softball
        if "School" not in header or not any("Win/Loss" in h for h in header):
            continue

        for row in rows[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cols) == 12:
                s = _SCHEMA_12
            elif len(cols) == 13:
                s = _SCHEMA_13
            else:
                continue  # header rows, empty rows, division-label rows

            wl = cols[s["wl"]].strip().upper()
            if wl not in ("W", "L"):
                continue  # unplayed or bye

            school = cols[s["school"]].strip()
            opponent = cols[s["opponent"]].strip()
            if not school or not opponent:
                continue

            dt_flag = cols[s["dt_flag"]].strip()
            results.append({
                "school": school,
                "opponent": opponent,
                "game_date": _parse_date(cols[s["date"]]),
                "home_away": cols[s["home_away"]].strip().upper(),
                "wl": wl,
                "score": cols[s["score"]],
                "is_district": dt_flag.upper() == "D",
                "dist_div": cols[s["dist_div"]],
                "opp_dist_div": cols[s["opp_dist_div"]],
                "filter_val": fval,
            })

    return results


def _parse_date(raw: str) -> str | None:
    """Extract YYYY-MM-DD from various date formats used by lhsaaonline."""
    # Try "MM/DD/YYYY" possibly followed by time/day
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2))).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def parse_scores(
    score_str: str,
    wl: str,
    is_home: bool,
    score_type: str,
    score_format: str = "perspective",
) -> tuple[int, int]:
    """
    Returns (home_score, away_score) for the games table.

    score_format:
      - "perspective" (default): lhsaaonline.org row's "X-Y" means my-opponent
      - "winner_first": "X-Y" means winner-loser regardless of perspective
        (baseball pages use this format per 2026-05-25 audit)

    Falls back to 1/0 encoding if parsing fails.
    """
    won = wl == "W"

    if score_type == "sets":
        # Volleyball: "25-22, 16-25, 25-23" — count sets won by each side
        sets_me = 0
        sets_opp = 0
        for s in score_str.split(","):
            parts = s.strip().split("-")
            if len(parts) == 2:
                try:
                    a, b = int(parts[0]), int(parts[1])
                    if a > b:
                        sets_me += 1
                    else:
                        sets_opp += 1
                except ValueError:
                    pass
        if sets_me + sets_opp > 0:
            if is_home:
                return sets_me, sets_opp
            else:
                return sets_opp, sets_me

    elif score_type in ("points", "runs", "goals"):
        # Single "X-Y" score (format depends on score_format flag)
        clean = score_str.replace("(f)", "").replace("(F)", "").strip()
        # Handle OT markers like "62-45 OT"
        clean = re.sub(r"\s*(OT|OT\d*)$", "", clean, flags=re.IGNORECASE).strip()
        parts = clean.split("-")
        if len(parts) == 2:
            try:
                a, b = int(parts[0]), int(parts[1])
                # Normalize to (my_score, opp_score) regardless of source format
                if score_format == "winner_first":
                    # "winner-loser" — assign by W/L not perspective
                    my_score = a if won else b
                    opp_score = b if won else a
                else:
                    # "perspective" — already my-opp
                    my_score, opp_score = a, b
                if is_home:
                    return my_score, opp_score
                else:
                    return opp_score, my_score
            except ValueError:
                pass

    # Fallback: encode W/L as 1/0
    if is_home:
        return (1, 0) if won else (0, 1)
    else:
        return (0, 1) if won else (1, 0)


def deduplicate(rows: list[dict]) -> list[dict]:
    """
    Deduplicate games — lhsaaonline returns one row per school per game.
    Key: (sorted pair of names, date). Prefer Home perspective.

    NOTE: this is a STRING-BASED first-pass dedup. It does NOT catch the
    case where two rows have different school name spellings that both
    resolve to the same DB team_id pair downstream. See
    deduplicate_by_constraint() below for the post-resolution second pass
    that closes that hole.
    """
    seen: dict[tuple, dict] = {}
    for row in rows:
        key = (min(row["school"], row["opponent"]),
               max(row["school"], row["opponent"]),
               row["game_date"] or "")
        if key not in seen:
            seen[key] = row
        elif row["home_away"] == "H":
            seen[key] = row
    return list(seen.values())


def deduplicate_by_constraint(rows: list[dict]) -> tuple[list[dict], int]:
    """Post-resolution second-pass dedup.

    The string-based deduplicate() above keys on raw lhsaaonline school
    names. After match_school() / B1.1 alias resolution, two rows with
    different name spellings (e.g., "St. Mary's" vs "St Marys", or the
    same game appearing in two classification filter sweeps under name
    variants) can survive that pass and resolve to the SAME
    (home_team_id, away_team_id, sport_id, season_year, game_date) tuple.

    When that happens, the upsert chunk fails with Postgres error 21000
    ("ON CONFLICT DO UPDATE command cannot affect row a second time").

    This pass dedupes by the exact constraint columns the upsert uses,
    picking the richer survivor per collision group. Returns
    (deduped_rows, n_collisions_resolved) so callers can log the rate —
    a high rate is evidence of systematic source-side name-variation
    drift that warrants a separate cleanup workstream.

    Discovered 2026-05-28 when GBB 2022 crashed mid-upsert; the
    deduplicate() above was the original string-dedup, this second pass
    is the integrity guarantee for the new uq_games_matchup constraint.
    """
    by_constraint: dict[tuple, dict] = {}
    n_collisions = 0
    for row in rows:
        key = (
            row["home_team_id"], row["away_team_id"],
            row["sport_id"], row["season_year"], row["game_date"],
        )
        existing = by_constraint.get(key)
        if existing is None:
            by_constraint[key] = row
            continue
        n_collisions += 1
        if _is_richer_game_row(row, existing):
            by_constraint[key] = row
    return list(by_constraint.values()), n_collisions


def _is_richer_game_row(candidate: dict, current: dict) -> bool:
    """Returns True if `candidate` should replace `current` in the
    post-resolution dedup. Ordering (descending priority):

      1. status == 'final' wins
      2. score completeness — number of non-NULL scores
      3. metadata richness — is_district + is_playoff truthy + week_number non-NULL
      4. tie → keep later-seen (return True on equal so the LATER source
         row replaces the earlier one — a later classification filter
         sweep is more likely to be the corrected/updated entry)

    Mirrors the cleanup ORDER BY used in the 2026-05-28 Softball 2024
    de-dupe (see migration dc98fac605a9 docstring).
    """
    def status_rank(r):
        return 1 if r.get("status") == "final" else 0

    def score_rank(r):
        return ((r.get("home_score") is not None)
                + (r.get("away_score") is not None))

    def meta_rank(r):
        return (int(bool(r.get("is_district")))
                + int(bool(r.get("is_playoff")))
                + (1 if r.get("week_number") is not None else 0))

    if status_rank(candidate) != status_rank(current):
        return status_rank(candidate) > status_rank(current)
    if score_rank(candidate) != score_rank(current):
        return score_rank(candidate) > score_rank(current)
    if meta_rank(candidate) != meta_rank(current):
        return meta_rank(candidate) > meta_rank(current)
    return True  # equal — prefer later-seen


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def load_schools(sb) -> dict[str, int]:
    res = sb.table("schools").select("id,name").execute()
    return {r["name"]: r["id"] for r in res.data}


def load_teams_for_sport(sb, sport_id: int) -> dict[tuple[int, int], int]:
    """(school_id, season_year) -> team_id"""
    all_teams = []
    offset, page = 0, 1000
    while True:
        res = sb.table("teams").select("id,school_id,season_year") \
                .eq("sport_id", sport_id).range(offset, offset + page - 1).execute()
        if not res.data:
            break
        all_teams.extend(res.data)
        if len(res.data) < page:
            break
        offset += page
    return {(r["school_id"], r["season_year"]): r["id"] for r in all_teams}


def get_or_create_team(sb, school_id: int, sport_id: int, season_year: int,
                        division: str | None, select_status: str | None,
                        team_cache: dict, dry_run: bool) -> int | None:
    """Return team_id, creating a new row when needed.

    2026-05-25: NEVER writes division/select_status during scrape — those
    are owned by scripts/refresh_team_divisions.py. New teams created here
    will have NULL for both columns; the refresh script populates them
    from LHSAA PDFs after the scrape.

    Existing team in cache → return cached id without touching the row.
    """
    key = (school_id, season_year)
    if key in team_cache:
        return team_cache[key]

    if dry_run:
        return None

    payload = {
        "school_id": school_id, "sport_id": sport_id,
        "season_year": season_year,
    }
    # Only set division/select_status if explicitly provided (legacy callers).
    # The 2026-05-25 ingest pipeline passes None for both.
    if division is not None:
        payload["division"] = division
    if select_status is not None:
        payload["select_status"] = select_status

    res = sb.table("teams").insert(payload).execute()
    if res.data:
        tid = res.data[0]["id"]
        team_cache[key] = tid
        return tid
    return None


def extract_division(dist_div: str, cfg: SportConfig) -> str:
    """Extract division from 'District-Division' or 'District-Class' strings."""
    if not dist_div:
        return "I"
    part = dist_div.split("-")[-1].strip()
    if cfg.division_filter:
        return part if part in ("I", "II", "III", "IV", "V") else "I"
    else:
        return CLASS_TO_DIV.get(part, "I")


# ---------------------------------------------------------------------------
# Power rating calculation
# ---------------------------------------------------------------------------

def calculate_and_store_ratings(sb, cfg: SportConfig, season_year: int,
                                 team_cache: dict, dry_run: bool):
    from engine.power_rating import calculate_all_ratings
    from engine.types import TeamRecord, GameResult, GameStatus

    print(f"\n  Calculating power ratings for {season_year} {cfg.name}...")

    all_games = []
    offset, page = 0, 1000
    while True:
        res = sb.table("games").select(
            "id,home_team_id,away_team_id,home_score,away_score,week_number,status,is_out_of_state"
        ).eq("sport_id", cfg.sport_id).eq("season_year", season_year).range(offset, offset + page - 1).execute()
        if not res.data:
            break
        all_games.extend(res.data)
        if len(res.data) < page:
            break
        offset += page

    if not all_games:
        print("  No games found — skipping.")
        return

    print(f"  Loaded {len(all_games)} games from DB.")

    all_team_ids = {g["home_team_id"] for g in all_games} | {g["away_team_id"] for g in all_games}
    teams_res = sb.table("teams").select("id,school_id,division,select_status") \
                  .in_("id", list(all_team_ids)).execute()
    team_info = {r["id"]: r for r in teams_res.data}

    school_ids = list({r["school_id"] for r in teams_res.data})
    schools_res = sb.table("schools").select("id,name,classification,parish") \
                    .in_("id", school_ids).execute()
    school_info = {r["id"]: r for r in schools_res.data}

    team_records: dict[int, TeamRecord] = {}
    for tid, ti in team_info.items():
        sid = ti["school_id"]
        sch = school_info.get(sid, {})
        # 2026-05-28 (Reese B1.2b post-mortem, Option B): OOS schools have
        # parish like 'OOS-XX' and classification=NULL. Their games are
        # already filtered out of game_results below. Skip them here so
        # they never enter team_records — otherwise the NULL classification
        # crashes TeamRecord pydantic validation.
        # Belt-and-suspenders: also catches in-state placeholder rows with
        # NULL classification (e.g., "Applied for Membership" entries) that
        # would still crash pydantic on the same NULL-classification door.
        if (sch.get("parish") or "").startswith("OOS") or not sch.get("classification"):
            continue
        # 2026-05-25: teams.division comes from refresh_team_divisions.py
        # (PDFs as source of truth). Fall back to "I" only for engine
        # bracketing when the team is uncovered by any PDF — does NOT
        # write back to DB.
        div = ti.get("division") or "I"
        team_records[tid] = TeamRecord(
            team_id=tid,
            school_name=sch.get("name", f"sid:{sid}"),
            division=div,
            classification=sch.get("classification", "5A"),
            wins=0, losses=0,
        )

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
            week_number=g.get("week_number"),
        ))

    if not game_results:
        print("  No valid game results — skipping.")
        return

    print(f"  Running engine on {len(game_results)} games, {len(team_records)} teams...")
    updated = calculate_all_ratings(team_records, game_results)

    from collections import defaultdict
    brackets: dict[str, list] = defaultdict(list)
    for tid, rec in updated.items():
        brackets[rec.division].append((rec.power_rating, tid))

    ranks: dict[int, tuple[int, int]] = {}
    for bracket, entries in brackets.items():
        entries.sort(reverse=True)
        total = len(entries)
        for rank, (_, tid) in enumerate(entries, start=1):
            ranks[tid] = (rank, total)

    payload = []
    for tid, rec in updated.items():
        rank, total = ranks.get(tid, (0, 0))
        payload.append({
            "team_id": tid,
            "week_number": cfg.week_snapshot,
            "season_year": season_year,
            "power_rating": round(float(rec.power_rating), 2),
            "strength_factor": round(float(rec.strength_factor), 2),
            "rank_in_division": rank,
            "total_teams_in_division": total,
        })

    if dry_run:
        print(f"  [dry-run] Would upsert {len(payload)} power rating rows.")
        for r in sorted(payload, key=lambda x: x["power_rating"], reverse=True)[:3]:
            print(f"    team_id={r['team_id']} rating={r['power_rating']} "
                  f"rank={r['rank_in_division']}/{r['total_teams_in_division']}")
        return

    print(f"  Upserting {len(payload)} power rating rows...")
    for i in range(0, len(payload), 200):
        # 2026-05-28 (Workstream B1.2b post-mortem): on_conflict columns MUST
        # match power_ratings.uq_power_ratings_team_week_season_source_snapshot
        # at apps/api/app/models.py PowerRating.__table_args__ (5 columns,
        # NULLS NOT DISTINCT). Engine path writes source='engine' + snapshot_date=NULL;
        # the NULLS NOT DISTINCT semantics make engine reruns upsert in place.
        # CI enforcement: test_b1_2b_bundle.test_power_ratings_constraint_columns_match_scraper_on_conflict.
        sb.table("power_ratings").upsert(
            payload[i:i+200],
            on_conflict="team_id,week_number,season_year,source,snapshot_date",
        ).execute()
    top = sorted(payload, key=lambda x: x["power_rating"], reverse=True)[:3]
    print(f"  Done. Top 3: {[(r['team_id'], r['power_rating']) for r in top]}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_sport(sb, cfg: SportConfig, seasons: list[int], dry_run: bool,
              school_name_to_id: dict, skip_ratings: bool):
    print(f"\n{'='*60}")
    print(f"Sport: {cfg.name} (sport_id={cfg.sport_id})")
    print(f"{'='*60}")

    team_cache = load_teams_for_sport(sb, cfg.sport_id)
    print(f"  Existing team records: {len(team_cache)}")

    unmatched: set[str] = set()
    # OOS school cache keyed by opponent name; shared across all seasons so
    # we don't double-insert the same OOS opponent. Pre-seeded with any
    # existing OOS schools already in the DB (parish LIKE 'OOS%') so
    # subsequent re-scrapes resolve to the same school_id.
    oos_school_cache: dict[str, int] = {
        s["name"]: s["id"]
        for s in (sb.table("schools").select("id,name,parish").like("parish", "OOS%").execute().data or [])
    }
    total_inserted = 0

    with httpx.Client(follow_redirects=True, timeout=60) as session:
        # Warm up session
        session.get(cfg.form_url)

        for season_year in seasons:
            if season_year not in cfg.years:
                print(f"  Season {season_year} not available for {cfg.name}, skipping.")
                continue

            print(f"\n  Season: {season_year}")
            all_rows: list[dict] = []

            for fval in cfg.filter_values:
                try:
                    rows = fetch_games(session, cfg, season_year, fval)
                    all_rows.extend(rows)
                    print(f"    {fval}: {len(rows)} rows", end="  ", flush=True)
                except Exception as e:
                    print(f"    {fval}: ERROR {e}", end="  ", flush=True)
                time.sleep(REQUEST_DELAY)
            print()

            unique_rows = deduplicate(all_rows)
            print(f"  Unique games after dedup: {len(unique_rows)}")

            games_to_insert: list[dict] = []
            for row in unique_rows:
                school_name = row["school"]
                opp_name = row["opponent"]

                # Skip open dates / byes
                if not school_name or not opp_name:
                    continue
                if "OPEN DATE" in school_name.upper() or "OPEN DATE" in opp_name.upper():
                    continue

                school_id = match_school(school_name, school_name_to_id)
                opp_id = match_school(opp_name, school_name_to_id)

                if school_id is None:
                    unmatched.add(school_name)
                    continue

                # 2026-05-25 Path C fix: detect OOS opponents and create
                # synthetic schools instead of dropping. See
                # reports/data_audit/cat1_diagnostic/RESULTS.md.
                opp_state_code: str | None = None
                if opp_id is None:
                    opp_state_code = detect_oos_state(opp_name)
                    if opp_state_code:
                        opp_id = get_or_create_oos_school(
                            sb, opp_name, opp_state_code, oos_school_cache, dry_run
                        )
                    if opp_id is None:
                        unmatched.add(opp_name)
                        continue

                is_home = row["home_away"] == "H"
                if is_home:
                    home_school_id, away_school_id = school_id, opp_id
                    home_div = extract_division(row["dist_div"], cfg)
                    away_div = extract_division(row["opp_dist_div"], cfg)
                else:
                    home_school_id, away_school_id = opp_id, school_id
                    home_div = extract_division(row["opp_dist_div"], cfg)
                    away_div = extract_division(row["dist_div"], cfg)

                # 2026-05-25: stopped passing division/select_status from
                # scraper data. teams.division is owned by
                # scripts/refresh_team_divisions.py (PDFs as source of truth).
                # New teams created here get NULL; existing teams keep their
                # PDF-derived values via the cache hit.
                home_team_id = get_or_create_team(
                    sb, home_school_id, cfg.sport_id, season_year,
                    None, None, team_cache, dry_run)
                away_team_id = get_or_create_team(
                    sb, away_school_id, cfg.sport_id, season_year,
                    None, None, team_cache, dry_run)

                if home_team_id is None or away_team_id is None:
                    continue

                home_score, away_score = parse_scores(
                    row["score"], row["wl"], is_home, cfg.score_type,
                    score_format=cfg.score_format)

                games_to_insert.append({
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "sport_id": cfg.sport_id,
                    "season_year": season_year,
                    "game_date": row["game_date"],
                    "week_number": None,
                    "home_score": home_score,
                    "away_score": away_score,
                    "status": "final",
                    "is_district": row["is_district"],
                    "is_playoff": False,
                    "is_championship": False,
                    # 2026-05-25: true when the opponent was resolved via the
                    # OOS-helper path (state suffix matched). Was hardcoded to
                    # False, which along with the opp_id-None skip silently
                    # dropped every OOS game from our DB.
                    "is_out_of_state": opp_state_code is not None,
                    "source": "lhsaaonline",
                })

            # 2026-05-28 (Workstream B1.2b followup): post-resolution dedup.
            # The string-based deduplicate() at L347 keys on raw school names
            # and can leak name-variant duplicates that resolve to the same
            # team_id pair. This second pass closes that hole — without it,
            # the upsert crashes with Postgres 21000 on within-batch dupes
            # (discovered GBB 2022). Logs the collision count so source-side
            # name-variation drift is visible. See task #90.
            games_to_insert, n_within_batch_collisions = deduplicate_by_constraint(
                games_to_insert
            )
            if n_within_batch_collisions > 0:
                print(f"  Post-resolution dedup: collapsed "
                      f"{n_within_batch_collisions} duplicate rows resolving "
                      f"to the same team_id tuple "
                      f"(likely lhsaaonline name-spelling variants and/or "
                      f"cross-classification filter overlap).")

            print(f"  Games ready: {len(games_to_insert)}")

            if dry_run:
                print(f"  [dry-run] Would insert {len(games_to_insert)} games.")
                if games_to_insert:
                    print(f"  Sample: {games_to_insert[0]}")
            else:
                print(f"  Inserting in batches...")
                for i in range(0, len(games_to_insert), 200):
                    chunk = games_to_insert[i:i+200]
                    # 2026-05-28 (Workstream B1.2b): upsert (not insert) so the
                    # scraper is idempotent against the games unique constraint.
                    # on_conflict columns MUST match the constraint at
                    # apps/api/app/models.py Game.__table_args__ (uq_games_matchup)
                    # and migration dc98fac605a9. Drift = silent no-op corruption.
                    # CI enforcement: test_b1_2b_bundle.test_constraint_columns_match_scraper_on_conflict.
                    sb.table("games").upsert(
                        chunk,
                        on_conflict="home_team_id,away_team_id,sport_id,season_year,game_date",
                    ).execute()
                total_inserted += len(games_to_insert)
                # Count is rows-attempted, not new-rows-created. On idempotent
                # re-runs this number stays the same but the DB row count won't grow.
                print(f"  Season {season_year}: {len(games_to_insert)} games upsert-attempted "
                      f"(existing rows update in place via uq_games_matchup).")

            if not skip_ratings:
                calculate_and_store_ratings(sb, cfg, season_year, team_cache, dry_run)

    print(f"\n{cfg.name} total games inserted: {total_inserted}")
    if unmatched:
        print(f"Unmatched schools ({len(unmatched)}):")
        for name in sorted(unmatched)[:20]:
            print(f"  - {name!r}")
        if len(unmatched) > 20:
            print(f"  ... and {len(unmatched) - 20} more")


def main():
    parser = argparse.ArgumentParser(description="Ingest LHSAA non-football sports history")
    parser.add_argument("--sports", nargs="+", default=["all"],
                        choices=list(SPORTS.keys()) + ["all"],
                        help="Sports to ingest (default: all)")
    parser.add_argument("--seasons", nargs="+", type=int,
                        default=[2021, 2022, 2023, 2024, 2025],
                        help="Season years")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-ratings", action="store_true")
    args = parser.parse_args()

    sports_to_run = list(SPORTS.keys()) if "all" in args.sports else args.sports

    print(f"{'='*60}")
    print(f"PrepRank Multi-Sport History Ingest")
    print(f"Sports: {sports_to_run}")
    print(f"Seasons: {args.seasons}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}")

    from supabase import create_client
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY env var not set — get it from Supabase Dashboard → Project Settings → API")
    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    school_name_to_id = {r["name"]: r["id"]
                         for r in sb.table("schools").select("id,name").execute().data}
    print(f"Loaded {len(school_name_to_id)} schools from DB.")

    for key in sports_to_run:
        cfg = SPORTS[key]
        run_sport(sb, cfg, args.seasons, args.dry_run, school_name_to_id, args.skip_ratings)

    print(f"\n{'='*60}")
    print("ALL DONE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
