"""Out-of-state opponent helper.

Used by both `ingest_football_historical.py` and `ingest_sports_historical.py`
to detect OOS opponents during scrape and create synthetic `schools` rows
for them. Previously both scripts silently dropped any game whose opponent
wasn't in our (Louisiana-only) `schools` table — see the 2026-05-25 Cat 1
diagnostic at `reports/data_audit/cat1_diagnostic/RESULTS.md`.

Design (per Reese's 2026-05-25 Path C spec):
- Keep referential integrity: every game still has a real `away_team_id`
  pointing at a real `schools.id`.
- OOS schools are tagged via `schools.parish = "OOS-XX"` (or `"OOS"` when
  the state can't be parsed) so they're queryable but distinguishable
  from LA schools.
- `division` and `select_status` stay NULL — refresh_team_divisions.py
  is the canonical division source and only populates from LHSAA PDFs.
"""
from __future__ import annotations

import re

# All 50 US states + DC + PR/VI/territories that LHSAA schools have
# played historically. Used to validate the " - XX" suffix pattern.
# LA is excluded — a "School - LA" suffix is unusual and shouldn't trigger
# OOS treatment (caller logs as unmatched name variant instead).
US_STATE_CODES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY",       "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "VI",
})

# "Name - XX" (state suffix) — sports scrapers (volleyball, basketball, etc.)
# encode OOS opponents this way because the lhsaaonline.org sports schedule
# pages don't surface a dedicated OOS column the way football does.
_OOS_SUFFIX_RE = re.compile(r"\s+-\s+([A-Z]{2})$")


def detect_oos_state(opponent_name: str) -> str | None:
    """Returns 2-letter state code if `opponent_name` looks like an OOS school.

    Matches the `" - XX"` suffix pattern (where XX is a recognized US state
    abbreviation other than LA). Used by the sports ingest as a fallback
    for the missing `is_oos` column.

    >>> detect_oos_state("Alto - TX")
    'TX'
    >>> detect_oos_state("Acadiana Renaissance Charter") is None
    True
    """
    m = _OOS_SUFFIX_RE.search(opponent_name or "")
    if not m:
        return None
    code = m.group(1)
    if code == "LA" or code not in US_STATE_CODES:
        return None
    return code


def get_or_create_oos_school(
    sb,
    opponent_name: str,
    state_code: str | None,
    school_cache: dict[str, int],
    dry_run: bool = False,
) -> int | None:
    """Return school_id for an OOS opponent, creating the row if needed.

    Caches by opponent_name within a single ingest run to avoid duplicate
    INSERTs when the same OOS school shows up on many LA teams' schedules.

    The new schools row gets:
        name   = opponent_name (as scraped, including " - XX" suffix)
        parish = "OOS-XX" when state_code is known, else "OOS"

    Other columns are left NULL — division/select_status are owned by
    `refresh_team_divisions.py` which only writes from LHSAA PDFs.
    """
    if not opponent_name:
        return None
    if opponent_name in school_cache:
        return school_cache[opponent_name]

    if dry_run:
        return None

    # First check: maybe we already have it from a prior ingest run.
    existing = sb.table("schools").select("id").eq("name", opponent_name).execute()
    if existing.data:
        sid = existing.data[0]["id"]
        school_cache[opponent_name] = sid
        return sid

    parish_value = f"OOS-{state_code}" if state_code else "OOS"
    res = sb.table("schools").insert({
        "name": opponent_name,
        "parish": parish_value,
    }).execute()
    if res.data:
        sid = res.data[0]["id"]
        school_cache[opponent_name] = sid
        return sid
    return None
