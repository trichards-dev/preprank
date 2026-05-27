"""Schools/teams ingest extension for the LHSAA alignment seed.

Per Reese 2026-05-27 B1.2a: idempotent ingest that uses the
B1.1 alias resolver to avoid duplicate-row creation, with source
attribution on every insert. Cross-references existing
``teams.sport_id`` rows before inserting; only true new
``(school, sport, season)`` tuples land.

Design
------
- All operations are idempotent: re-running the same ingest with the
  same input produces no DB changes after the first call.
- Alias resolution: every canonical school name flows through
  ``engine.data.school_aliases.resolve_school`` before any insert.
  If the resolver returns an existing DB row, we use that row's id
  rather than inserting a duplicate.
- Source attribution: every insert records the canonical source
  (e.g., "LHSAA 2025-2026 alignment, consolidated by Thomas") so
  ingest provenance is auditable.
- DB I/O is isolated behind callable interfaces so the ingest logic
  can be unit-tested without a real Supabase connection.

This module DOES NOT scrape game data — that's B1.2b's per-sport
execution step. This module only adds school + team rows so that the
B1.2b game-scrape step has the right ``teams.id`` to attach games to.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from engine.data.school_aliases import normalize_name, resolve_school


@dataclass
class IngestResult:
    """Summary of an alignment-ingest run.

    All counts are cumulative across the (school_id × sport × season)
    tuples processed in this run.
    """

    schools_inserted: list[dict] = field(default_factory=list)
    schools_resolved_via_alias: list[dict] = field(default_factory=list)
    schools_already_present: list[dict] = field(default_factory=list)
    teams_inserted: list[dict] = field(default_factory=list)
    teams_already_present: list[dict] = field(default_factory=list)
    skipped_with_reasons: list[dict] = field(default_factory=list)
    source_attribution: str = ""

    @property
    def n_schools_inserted(self) -> int:
        return len(self.schools_inserted)

    @property
    def n_schools_resolved_via_alias(self) -> int:
        return len(self.schools_resolved_via_alias)

    @property
    def n_teams_inserted(self) -> int:
        return len(self.teams_inserted)

    @property
    def n_teams_already_present(self) -> int:
        return len(self.teams_already_present)


def ingest_alignment(
    *,
    participation_data: dict[str, Any],
    sport_id_map: dict[str, int],
    season_year: int,
    db_schools: list[dict],
    db_teams: list[dict],
    insert_school_fn: Callable[[dict], dict],
    insert_team_fn: Callable[[dict], dict],
    source_attribution: str = "LHSAA 2025-2026 alignment, consolidated by Thomas",
) -> IngestResult:
    """Idempotent ingest of an LHSAA alignment file into schools + teams.

    Parameters
    ----------
    participation_data : dict
        Output of ``load_lhsaa_participation`` — a dict with
        ``{season, source, participation: {sport: [{school, city, classification}, ...]}}``.
    sport_id_map : dict[str, int]
        Maps sport name to ``sports.id``. Sports not in the map are
        skipped with a reason logged.
    season_year : int
        Season-year to associate with new team rows.
    db_schools : list[dict]
        Current ``schools`` table (snapshot). Each row has at least
        ``id, name, classification, parish``. Used for alias resolution
        and to detect "already present" schools.
    db_teams : list[dict]
        Current ``teams`` table (snapshot, filtered to relevant
        sport-seasons or full). Each row has at least
        ``id, school_id, sport_id, season_year``.
    insert_school_fn : callable(dict) -> dict
        Inserts a school row and returns the inserted dict (with id).
        Caller controls actual DB I/O. For tests, pass a closure that
        appends to a list.
    insert_team_fn : callable(dict) -> dict
        Inserts a team row and returns the inserted dict (with id).
    source_attribution : str
        Recorded on every IngestResult.

    Returns
    -------
    IngestResult with detailed per-row outcomes.
    """
    result = IngestResult(source_attribution=source_attribution)

    # Index db_schools by normalized name AND id for fast lookup
    db_schools_by_norm = {normalize_name(s["name"]): s for s in db_schools if s.get("name")}
    db_schools_by_id = {s["id"]: s for s in db_schools}

    # Index db_teams by (school_id, sport_id, season_year) for fast presence check
    db_teams_by_tuple = {
        (t["school_id"], t["sport_id"], t["season_year"]): t
        for t in db_teams
    }

    # Track schools we've already processed within this run so we don't
    # double-insert when the same school fields multiple sports
    schools_processed_this_run: dict[str, int] = {}  # normalized_name -> school_id

    participation = participation_data.get("participation", {})
    for sport, entries in participation.items():
        sport_id = sport_id_map.get(sport)
        if sport_id is None:
            result.skipped_with_reasons.append({
                "reason": "sport_not_in_id_map",
                "sport": sport,
                "entries_skipped": len(entries),
            })
            continue

        for entry in entries:
            canonical_name = entry.get("school") or entry.get("name") or ""
            canonical_city = entry.get("city")
            canonical_class = entry.get("classification")
            norm = normalize_name(canonical_name)
            if not norm:
                result.skipped_with_reasons.append({
                    "reason": "empty_school_name",
                    "sport": sport,
                    "entry": entry,
                })
                continue

            # Step 1: resolve school
            school_id: int | None = schools_processed_this_run.get(norm)
            if school_id is None:
                # Try resolver (explicit aliases + exact normalized match)
                resolved = resolve_school(canonical_name, db_schools)
                if resolved is not None:
                    # If resolved via alias (not exact), record it
                    if normalize_name(resolved["name"]) != norm:
                        result.schools_resolved_via_alias.append({
                            "canonical_name": canonical_name,
                            "resolved_to_id": resolved["id"],
                            "resolved_to_name": resolved["name"],
                        })
                    else:
                        result.schools_already_present.append({
                            "name": canonical_name,
                            "id": resolved["id"],
                        })
                    school_id = resolved["id"]
                else:
                    # No alias, no exact match — INSERT new school row
                    new_school_payload = {
                        "name": canonical_name,
                        "city": canonical_city,
                        "classification": canonical_class,
                        "parish": None,   # LHSAA-considered schools have parish=NULL
                        "_source": source_attribution,
                    }
                    inserted = insert_school_fn(new_school_payload)
                    if inserted is None or "id" not in inserted:
                        result.skipped_with_reasons.append({
                            "reason": "insert_school_fn_failed",
                            "payload": new_school_payload,
                        })
                        continue
                    school_id = inserted["id"]
                    result.schools_inserted.append({
                        "id": school_id,
                        "name": canonical_name,
                        "classification": canonical_class,
                        "source": source_attribution,
                    })
                    # Reflect in our in-memory snapshots so subsequent iterations
                    # see the just-inserted school
                    db_schools.append(inserted)
                    db_schools_by_norm[norm] = inserted
                    db_schools_by_id[school_id] = inserted
                schools_processed_this_run[norm] = school_id

            # Step 2: insert team row if (school_id, sport_id, season_year) is new
            team_key = (school_id, sport_id, season_year)
            if team_key in db_teams_by_tuple:
                result.teams_already_present.append({
                    "school_id": school_id,
                    "sport": sport,
                    "season_year": season_year,
                    "existing_team_id": db_teams_by_tuple[team_key]["id"],
                })
                continue

            new_team_payload = {
                "school_id": school_id,
                "sport_id": sport_id,
                "season_year": season_year,
                "_source": source_attribution,
            }
            inserted_team = insert_team_fn(new_team_payload)
            if inserted_team is None or "id" not in inserted_team:
                result.skipped_with_reasons.append({
                    "reason": "insert_team_fn_failed",
                    "payload": new_team_payload,
                })
                continue
            team_id = inserted_team["id"]
            result.teams_inserted.append({
                "team_id": team_id,
                "school_id": school_id,
                "sport": sport,
                "season_year": season_year,
                "source": source_attribution,
            })
            # Reflect in our snapshot
            db_teams_by_tuple[team_key] = inserted_team

    return result
