#!/usr/bin/env python3
"""Load LHSAA official power-rating PDFs into power_ratings.source = 'lhsaa_official'.

Reads scripts/lhsaa_pdf_index.json, parses each PDF via parse_lhsaa_pdf.parse_pdf,
resolves school_name → team_id (reusing helpers from ingest_sports_historical.py),
and batch-upserts rows into the LHSAA partial unique index
(team_id, season_year, source, snapshot_date) WHERE source <> 'engine'.

Usage:
    python scripts/load_lhsaa_official.py --dry-run
    python scripts/load_lhsaa_official.py --only-sport Football
    python scripts/load_lhsaa_official.py --only-year 2025
    python scripts/load_lhsaa_official.py --max-firecrawl-fallbacks 20
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from difflib import SequenceMatcher
from pathlib import Path

from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_lhsaa_pdf import parse_pdf  # noqa: E402


SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ywlaekkxkwfznwuupggi.supabase.co")

INDEX_PATH = Path(__file__).resolve().parent / "lhsaa_pdf_index.json"

# Mirrors overview.md sport-id table. Verified against the live `sports` row IDs.
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


def _normalize(name: str) -> str:
    return name.lower().strip()


def match_school(query: str, candidates: dict[str, int], threshold: float = 0.75) -> int | None:
    """Fuzzy school-name match (copied verbatim from ingest_sports_historical.py)."""
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


def load_schools(sb) -> dict[str, int]:
    res = sb.table("schools").select("id,name").execute()
    return {r["name"]: r["id"] for r in res.data}


def load_teams_for_sport(sb, sport_id: int) -> dict[tuple[int, int], int]:
    """(school_id, season_year) -> team_id"""
    all_teams: list[dict] = []
    offset, page = 0, 1000
    while True:
        res = (sb.table("teams").select("id,school_id,season_year")
               .eq("sport_id", sport_id).range(offset, offset + page - 1).execute())
        if not res.data:
            break
        all_teams.extend(res.data)
        if len(res.data) < page:
            break
        offset += page
    return {(r["school_id"], r["season_year"]): r["id"] for r in all_teams}


def get_or_create_team(sb, school_id: int, sport_id: int, season_year: int,
                       division: str, select_status: str,
                       team_cache: dict, dry_run: bool) -> int | None:
    key = (school_id, season_year)
    if key in team_cache:
        return team_cache[key]
    if dry_run:
        return None
    payload = {
        "school_id": school_id,
        "sport_id": sport_id,
        "season_year": season_year,
        "division": division or "I",
    }
    if select_status:
        payload["select_status"] = select_status
    res = sb.table("teams").insert(payload).execute()
    if res.data:
        tid = res.data[0]["id"]
        team_cache[key] = tid
        return tid
    return None


def _resolve_sport_id(sport_name: str) -> int | None:
    return SPORT_NAME_TO_ID.get(_normalize(sport_name))


def _batched_insert(sb, rows: list[dict], chunk: int = 200) -> int:
    """Plain INSERT. Caller is responsible for DELETE-ing pre-existing
    source='lhsaa_official' rows for the (season, snapshot_date) combo first
    so this insert never collides. ON CONFLICT against a partial unique index
    isn't expressible via the supabase-py REST client.
    """
    written = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i : i + chunk]
        sb.table("power_ratings").insert(batch).execute()
        written += len(batch)
    return written


def _wipe_lhsaa_rows_for_entry(sb, season_year: int, sport_team_ids: list[int],
                                snapshot_iso: str | None) -> int:
    """Delete any pre-existing source='lhsaa_official' rows that match this
    PDF's (season, sport teams, snapshot_date) tuple so re-runs are idempotent.
    """
    if not sport_team_ids:
        return 0
    deleted = 0
    for i in range(0, len(sport_team_ids), 500):
        chunk = sport_team_ids[i : i + 500]
        q = (sb.table("power_ratings").delete()
             .eq("source", "lhsaa_official").eq("season_year", season_year)
             .in_("team_id", chunk))
        if snapshot_iso is None:
            q = q.is_("snapshot_date", "null")
        else:
            q = q.eq("snapshot_date", snapshot_iso)
        res = q.execute()
        deleted += len(res.data) if res.data else 0
    return deleted


def process_entry(
    sb,
    entry: dict,
    schools_by_name: dict[str, int],
    team_caches: dict[int, dict[tuple[int, int], int]],
    unmatched: set[str],
    dry_run: bool,
    force_firecrawl: bool,
) -> tuple[int, int, int]:
    """Parse one PDF entry, build power_rating rows, upsert.

    Returns (parsed_count, mapped_count, written_count).
    """
    sport_id = _resolve_sport_id(entry["sport"])
    if sport_id is None:
        print(f"  [skip] Unknown sport: {entry['sport']!r}")
        return (0, 0, 0)

    parsed = parse_pdf(entry, force_firecrawl=force_firecrawl)
    if not parsed:
        return (0, 0, 0)

    if sport_id not in team_caches:
        team_caches[sport_id] = load_teams_for_sport(sb, sport_id)
    team_cache = team_caches[sport_id]

    rows_to_write: list[dict] = []
    mapped = 0
    for r in parsed:
        sid = match_school(r.school_name, schools_by_name)
        if sid is None:
            unmatched.add(r.school_name)
            continue
        team_id = get_or_create_team(
            sb, sid, sport_id, r.season_year, r.division, r.select_status,
            team_cache, dry_run,
        )
        if team_id is None:
            continue
        mapped += 1
        rows_to_write.append({
            "team_id": team_id,
            "week_number": 99,  # LHSAA "Final" sentinel; mid-season rows still distinguished by snapshot_date
            "season_year": r.season_year,
            "power_rating": float(r.power_rating),
            "strength_factor": float(r.strength_factor) if r.strength_factor is not None else None,
            "rank_in_division": r.rank,
            "source": "lhsaa_official",
            "snapshot_date": r.snapshot_date.isoformat() if r.snapshot_date else None,
        })

    # Dedupe by team_id (keep first occurrence) — some PDFs have appendix
    # sections like "Schools not playing in the Playoff" that re-list teams,
    # which the parser picks up. The first occurrence is the canonical ranked row.
    seen_team_ids: set[int] = set()
    deduped: list[dict] = []
    for r in rows_to_write:
        if r["team_id"] in seen_team_ids:
            continue
        seen_team_ids.add(r["team_id"])
        deduped.append(r)
    rows_to_write = deduped

    written = 0
    if rows_to_write and not dry_run:
        snapshot_iso = rows_to_write[0]["snapshot_date"]
        team_ids = list({r["team_id"] for r in rows_to_write})
        season = rows_to_write[0]["season_year"]
        _wipe_lhsaa_rows_for_entry(sb, season, team_ids, snapshot_iso)
        written = _batched_insert(sb, rows_to_write)

    return (len(parsed), mapped, written)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only-sport", default=None, help="Filter entries by sport name (case-insensitive)")
    p.add_argument("--only-year", type=int, default=None)
    p.add_argument("--max-firecrawl-fallbacks", type=int, default=20)
    p.add_argument("--force-firecrawl", default=None,
                   help="A single URL to force through Firecrawl (skips other entries)")
    args = p.parse_args()

    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not service_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY env var is required")
    sb = create_client(SUPABASE_URL, service_key)

    index_data = json.loads(INDEX_PATH.read_text())
    entries = index_data["pdfs"]

    if args.force_firecrawl:
        entries = [e for e in entries if e["url"] == args.force_firecrawl]
        if not entries:
            print(f"No index entry matches URL {args.force_firecrawl}", file=sys.stderr)
            return 2

    if args.only_sport:
        s = _normalize(args.only_sport)
        entries = [e for e in entries if _normalize(e["sport"]) == s]
    if args.only_year:
        entries = [e for e in entries if int(e["season_year"]) == args.only_year]

    if not entries:
        print("No entries match filters; nothing to do.")
        return 0

    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Processing {len(entries)} PDF entries")
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Firecrawl fallback cap: {args.max_firecrawl_fallbacks}")
    print()

    schools_by_name = load_schools(sb)
    print(f"Loaded {len(schools_by_name)} schools from DB")

    team_caches: dict[int, dict[tuple[int, int], int]] = {}
    unmatched: set[str] = set()
    firecrawl_used = 0
    total_parsed = total_mapped = total_written = 0
    failures: list[tuple[str, str]] = []

    for i, entry in enumerate(entries, 1):
        label = f"{entry['sport']} {entry['season_year']} ({entry.get('division','all')}/{entry.get('select_status','all')}) — {entry.get('snapshot','')}"
        print(f"[{i}/{len(entries)}] {label}")
        try:
            force_fc = bool(args.force_firecrawl) and entry["url"] == args.force_firecrawl
            if firecrawl_used >= args.max_firecrawl_fallbacks and not force_fc:
                # cap reached; skip Firecrawl path by aborting on 0-pdfplumber-rows entries
                parsed_count, mapped, written = process_entry(
                    sb, entry, schools_by_name, team_caches, unmatched,
                    args.dry_run, force_firecrawl=False,
                )
            else:
                parsed_count, mapped, written = process_entry(
                    sb, entry, schools_by_name, team_caches, unmatched,
                    args.dry_run, force_firecrawl=force_fc,
                )
        except Exception as e:
            failures.append((entry["url"], f"{type(e).__name__}: {e}"))
            print(f"    ERROR: {e}")
            continue

        total_parsed += parsed_count
        total_mapped += mapped
        total_written += written
        print(f"    parsed={parsed_count} mapped={mapped} written={written}")

    print()
    print("=" * 60)
    print(f"Total parsed rows : {total_parsed}")
    print(f"Total mapped rows : {total_mapped}")
    print(f"Total written rows: {total_written} {'(dry-run, no writes)' if args.dry_run else ''}")
    print(f"Unmatched schools : {len(unmatched)}")
    if unmatched:
        print("  Unmatched names (sample, up to 30):")
        for name in sorted(unmatched)[:30]:
            print(f"    - {name}")
    if failures:
        print(f"Failures          : {len(failures)}")
        for url, err in failures:
            print(f"  ! {url}\n      {err}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
