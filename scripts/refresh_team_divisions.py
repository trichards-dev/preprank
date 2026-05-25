"""Refresh teams.division and teams.select_status from LHSAA PDFs only.

Replaces the ingest scripts' broken CLASS_TO_DIV fallback as the canonical
source of (division, select_status) per (school, sport, season). Run order:

    1. Clear teams.division and teams.select_status across the board.
    2. For every PDF entry in scripts/lhsaa_pdf_index.json, parse and
       fuzzy-match each PDF row to an existing team via
       (school_id, sport_id, season_year). UPDATE division + select_status.
    3. Report coverage: teams updated, teams left NULL, unmatched PDF rows
       (PDF row has a team not in our DB), gap summary per (sport, season).

Per Reese's 2026-05-25 plan: PDFs are the canonical source. NULL is the
ONLY fallback — never inferred from class. The ingest scripts will be
patched separately to stop writing division during scrape.

Usage:
    python -m scripts.refresh_team_divisions [--dry-run] [--sports football,...]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from supabase import Client, create_client

from scripts.parse_lhsaa_pdf import parse_pdf


SPORT_NAME_TO_ID: dict[str, int] = {
    "football": 1,
    "volleyball": 2,
    "boys basketball": 5,
    "girls basketball": 6,
    "baseball": 11,
    "softball": 12,
    "boys soccer": 13,
    "girls soccer": 14,
}


def _supabase() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY required in env or apps/api/.env")
    return create_client(url, key)


def _normalize(name: str) -> str:
    return (name or "").lower().strip()


def _fuzzy_match(query: str, candidates: dict[str, int], threshold: float = 0.75) -> int | None:
    q = _normalize(query)
    for name, sid in candidates.items():
        if _normalize(name) == q:
            return sid
    best_score, best_id = 0.0, None
    for name, sid in candidates.items():
        score = SequenceMatcher(None, q, _normalize(name)).ratio()
        if score > best_score and score >= threshold:
            best_score, best_id = score, sid
    return best_id


def _load_schools(sb: Client) -> dict[str, int]:
    res = sb.table("schools").select("id,name").execute()
    return {r["name"]: r["id"] for r in res.data}


def _load_teams(sb: Client) -> dict[tuple[int, int, int], int]:
    """(school_id, sport_id, season_year) -> team_id"""
    out: dict[tuple[int, int, int], int] = {}
    offset, page = 0, 1000
    while True:
        res = (sb.table("teams")
               .select("id,school_id,sport_id,season_year")
               .range(offset, offset + page - 1)
               .execute())
        if not res.data:
            break
        for r in res.data:
            if r["school_id"] is None or r["sport_id"] is None:
                continue
            out[(r["school_id"], r["sport_id"], int(r["season_year"]))] = r["id"]
        if len(res.data) < page:
            break
        offset += page
    return out


def _clear_all_divisions(
    sb: Client,
    dry_run: bool,
    sport_ids: set[int] | None = None,
) -> int:
    """Set teams.division + teams.select_status to NULL.

    When sport_ids is provided, only teams belonging to those sports are cleared
    — protects other sports' divisions when refreshing a single sport.
    """
    if dry_run:
        scope = f"sports={sport_ids}" if sport_ids else "all rows"
        print(f"[dry-run] would clear teams.division + teams.select_status ({scope})")
        return 0
    q = sb.table("teams").update({"division": None, "select_status": None})
    if sport_ids is not None:
        q = q.in_("sport_id", list(sport_ids))
    else:
        q = q.gt("id", 0)
    res = q.execute()
    return len(res.data or [])


def refresh(
    sb: Client,
    sports_filter: set[str] | None = None,
    dry_run: bool = False,
) -> dict:
    pdf_index_path = Path(__file__).resolve().parent / "lhsaa_pdf_index.json"
    pdf_entries = json.loads(pdf_index_path.read_text())["pdfs"]
    if sports_filter:
        pdf_entries = [e for e in pdf_entries if _normalize(e.get("sport", "")) in sports_filter]

    print(f"[refresh] loading schools + teams from DB...")
    schools_by_name = _load_schools(sb)
    teams_index = _load_teams(sb)
    print(f"[refresh] {len(schools_by_name)} schools, {len(teams_index)} teams")

    # Inventory which (sport, season) combos exist in our teams table.
    # Anything WITHOUT a matching PDF after this run is a coverage gap.
    sport_seasons_in_db = {(sport_id, season) for (_, sport_id, season) in teams_index.keys()}

    # Step 1: clear (scoped to filtered sports if --sports was specified)
    clear_sport_ids: set[int] | None = None
    if sports_filter:
        clear_sport_ids = {SPORT_NAME_TO_ID[s] for s in sports_filter if s in SPORT_NAME_TO_ID}
    cleared = _clear_all_divisions(sb, dry_run, sport_ids=clear_sport_ids)
    scope_msg = f" (sports={sorted(clear_sport_ids)})" if clear_sport_ids else ""
    print(f"[refresh] cleared {cleared} team rows{scope_msg} (division + select_status → NULL)")

    # Step 2: parse each PDF, accumulate UPDATEs by team_id
    updates_by_team: dict[int, dict] = {}
    pdf_stats: list[dict] = []
    unmatched_pdf_rows: list[dict] = []
    covered_sport_seasons: set[tuple[int, int]] = set()

    for entry in pdf_entries:
        sport_name = entry.get("sport", "")
        sport_id = SPORT_NAME_TO_ID.get(_normalize(sport_name))
        season = int(entry.get("season_year", 0))
        if sport_id is None or season == 0:
            continue

        try:
            rows = parse_pdf(entry)
        except Exception as exc:
            pdf_stats.append({"entry": entry["url"], "status": "parse_error", "msg": str(exc)[:120]})
            continue
        if not rows:
            pdf_stats.append({"entry": entry["url"], "status": "empty_parse"})
            continue

        covered_sport_seasons.add((sport_id, season))
        rows_matched = rows_unmatched = rows_skipped_no_team = 0
        for r in rows:
            school_id = _fuzzy_match(r.school_name, schools_by_name)
            if school_id is None:
                rows_unmatched += 1
                unmatched_pdf_rows.append({
                    "pdf": entry["url"], "school": r.school_name,
                    "division": r.division, "select_status": r.select_status,
                })
                continue
            team_id = teams_index.get((school_id, sport_id, season))
            if team_id is None:
                rows_skipped_no_team += 1
                continue
            # Last-write-wins for a team when multiple PDFs cover it; prefer
            # the entry with a more specific snapshot (later in the index).
            updates_by_team[team_id] = {
                "division": r.division or None,
                "select_status": r.select_status or None,
            }
            rows_matched += 1
        pdf_stats.append({
            "entry": entry["url"], "status": "ok",
            "rows_total": len(rows), "rows_matched": rows_matched,
            "rows_unmatched_school": rows_unmatched,
            "rows_skipped_no_team_for_season": rows_skipped_no_team,
        })

    # Step 3: apply updates
    print(f"[refresh] applying {len(updates_by_team)} team updates...")
    applied = 0
    if not dry_run:
        # Supabase REST doesn't have a multi-row UPDATE with per-row values,
        # so we issue one UPDATE per distinct (division, select_status) pair
        # using an `in_("id", chunk)` filter.
        by_payload: dict[tuple, list[int]] = defaultdict(list)
        for tid, p in updates_by_team.items():
            by_payload[(p["division"], p["select_status"])].append(tid)
        for (div, sel), tids in by_payload.items():
            payload = {"division": div, "select_status": sel}
            for i in range(0, len(tids), 200):
                chunk = tids[i:i + 200]
                sb.table("teams").update(payload).in_("id", chunk).execute()
                applied += len(chunk)

    # Step 4: coverage report
    gap_sport_seasons = sorted(sport_seasons_in_db - covered_sport_seasons)
    teams_left_null = len(teams_index) - len(updates_by_team)

    summary = {
        "n_teams_total": len(teams_index),
        "n_teams_updated": len(updates_by_team),
        "n_teams_left_null": teams_left_null,
        "n_pdfs_processed": sum(1 for s in pdf_stats if s["status"] == "ok"),
        "n_pdfs_failed": sum(1 for s in pdf_stats if s["status"] != "ok"),
        "n_unmatched_pdf_rows": len(unmatched_pdf_rows),
        "covered_sport_seasons": sorted([list(t) for t in covered_sport_seasons]),
        "gap_sport_seasons": [list(t) for t in gap_sport_seasons],
        "pdf_stats": pdf_stats,
        "updates_applied": applied,
        "dry_run": dry_run,
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(repo_root / "apps" / "api" / ".env")

    p = argparse.ArgumentParser(prog="python -m scripts.refresh_team_divisions")
    p.add_argument("--dry-run", action="store_true",
                   help="report what would change without writing to DB")
    p.add_argument("--sports", default=None,
                   help="comma-list of sport names; default = all")
    p.add_argument("--output-json", default="reports/refresh_team_divisions_log.json")
    args = p.parse_args(argv)

    sports_filter = None
    if args.sports:
        sports_filter = {_normalize(s) for s in args.sports.split(",")}

    sb = _supabase()
    summary = refresh(sb, sports_filter=sports_filter, dry_run=args.dry_run)

    out_path = Path(args.output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print()
    print(f"=== refresh_team_divisions ({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")
    print(f"teams total:          {summary['n_teams_total']}")
    print(f"teams updated:        {summary['n_teams_updated']}")
    print(f"teams left NULL:      {summary['n_teams_left_null']}")
    print(f"PDFs processed:       {summary['n_pdfs_processed']}")
    print(f"PDFs failed/empty:    {summary['n_pdfs_failed']}")
    print(f"unmatched PDF rows:   {summary['n_unmatched_pdf_rows']}")
    print(f"gap (sport,season):   {len(summary['gap_sport_seasons'])} combos")
    print(f"log JSON:             {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
