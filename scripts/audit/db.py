"""Data loaders for the Phase 0 audit.

Reuses ``engine.validator.data`` for the loaders the validator already needs
(sports map, teams+schools). Adds an *unfiltered* games loader because the
audit needs to count invalid rows (NULL scores, non-final status,
out-of-state) — the validator's ``load_games`` silently drops them.

A fresh ``supabase.Client`` is created on demand to side-step the HTTP/2
stream-limit issue seen in prior validator fits.
"""
from __future__ import annotations

import os

from supabase import Client, create_client

# Re-exported so audit callers can `from scripts.audit.db import ...` for everything.
from engine.validator.data import (  # noqa: F401  (re-exported)
    ALL_SPORTS,
    MAX_WEEKS_BY_SPORT,
    load_sports_map,
    load_teams_with_schools,
)


def supabase_client_factory() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) "
            "must be set in env or apps/api/.env."
        )
    return create_client(url, key)


def load_games_unfiltered(sb: Client, sport_id: int, season_year: int) -> list[dict]:
    """All games for (sport, season). No status/score/out-of-state filtering.

    Phase 0 wants to surface invalid rows, not hide them.
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
    return out


def name_to_sport_id(sb: Client) -> dict[str, int]:
    """Inverse of load_sports_map: name -> id (case-sensitive)."""
    return {name: sid for sid, name in load_sports_map(sb).items()}
