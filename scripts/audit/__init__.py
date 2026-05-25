"""Phase 0 data audit package — v2 TASK 2.

Public entry point: ``run_full_audit``. Used by the CLI in ``__main__.py``
and by unit tests with a stub Supabase client.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from scripts.audit.checks import (
    CheckResult,
    check_0_1_home_away_sanity,
    check_0_2_score_distribution,
    check_0_3_team_game_balance,
    check_0_4_league_arithmetic,
    check_0_5_mercy_rule,
    check_0_6_classification_drift,
)
from scripts.audit.cross_source import check_0_7_cross_source
from scripts.audit.db import (
    ALL_SPORTS,
    load_games_unfiltered,
    load_sports_map,
    load_teams_with_schools,
    name_to_sport_id,
)
from scripts.audit.reclass_events import (
    DEFAULT_EVENT_THRESHOLD,
    ReclassEvent,
    detect_reclass_events,
)
from scripts.audit.report import (
    persist_to_db,
    write_anomalies_csv,
    write_json_per_sport_season,
    write_summary_md,
)


def _filter_teams(teams: dict[int, dict], sport_id: int, season_year: int) -> dict[int, dict]:
    return {
        tid: t for tid, t in teams.items()
        if t.get("sport_id") == sport_id and t.get("season_year") == season_year
    }


def run_full_audit(
    sb,
    sports: list[str] | None = None,
    seasons: list[int] | None = None,
    output_dir: Path | str | None = None,
    persist: bool = True,
    skip_cross_source: bool = False,
    run_id: str | None = None,
    schools_by_name: dict[str, int] | None = None,
    reclass_threshold: float = DEFAULT_EVENT_THRESHOLD,
    log_fn=print,
) -> tuple[str, list[CheckResult], list[ReclassEvent], dict[str, Path]]:
    """Run all Phase 0 checks; write artifacts; optionally persist to DB.

    Returns (run_id, results, reclass_events, {summary_md, anomalies_csv, json_dir}).
    """
    sports = sports or list(ALL_SPORTS)
    seasons = seasons or [2021, 2022, 2023, 2024, 2025]
    output_dir = Path(output_dir) if output_dir else Path("reports/data_audit")
    run_id = run_id or str(uuid.uuid4())

    log_fn(f"[audit] run_id={run_id}")
    log_fn(f"[audit] sports={sports}, seasons={seasons}")

    sport_id_by_name = name_to_sport_id(sb)
    teams = load_teams_with_schools(sb)
    if schools_by_name is None:
        schools_by_name = {}
        for t in teams.values():
            name = t.get("school_name")
            sid = t.get("school_id")
            if name and sid is not None:
                schools_by_name.setdefault(name, sid)

    results: list[CheckResult] = []
    reclass_events: list[ReclassEvent] = []

    for sport_name in sports:
        sport_id = sport_id_by_name.get(sport_name)
        if sport_id is None:
            log_fn(f"[audit] WARN: sport '{sport_name}' not in sports table; skipping")
            continue

        for season in seasons:
            teams_ss = _filter_teams(teams, sport_id, season)
            games = load_games_unfiltered(sb, sport_id, season)
            log_fn(f"[audit] {sport_name} {season}: {len(games)} games, {len(teams_ss)} teams")
            if not games and not teams_ss:
                continue

            results.append(check_0_1_home_away_sanity(games, sport_id, sport_name, season))
            results.append(check_0_2_score_distribution(games, sport_id, sport_name, season))
            results.append(check_0_3_team_game_balance(games, teams_ss, sport_id, sport_name, season))
            results.append(check_0_4_league_arithmetic(games, teams_ss, sport_id, sport_name, season))
            results.append(check_0_5_mercy_rule(games, sport_id, sport_name, season))

            if not skip_cross_source:
                results.append(
                    check_0_7_cross_source(
                        sport_id=sport_id,
                        sport_name=sport_name,
                        season_year=season,
                        games=games,
                        teams_for_sport_season=teams_ss,
                        schools_by_name=schools_by_name,
                    )
                )

        teams_for_sport_all = [
            {**t, "sport_id": t.get("sport_id")}
            for tid, t in teams.items()
            if t.get("sport_id") == sport_id
        ]
        results.append(
            check_0_6_classification_drift(teams_for_sport_all, sport_id, sport_name)
        )
        sport_events = detect_reclass_events(
            teams_for_sport_all, sport_id, sport_name, threshold=reclass_threshold
        )
        reclass_events.extend(sport_events)
        if sport_events:
            log_fn(f"[audit] {sport_name}: {len(sport_events)} reclass event(s) detected")

    log_fn(f"[audit] writing {len(results)} results + {len(reclass_events)} reclass events to {output_dir}")
    json_paths = write_json_per_sport_season(results, output_dir)
    summary_path = write_summary_md(results, output_dir, run_id, reclass_events=reclass_events)
    anomalies_path = write_anomalies_csv(results, output_dir)

    if persist:
        n = persist_to_db(sb, results, run_id)
        log_fn(f"[audit] persisted {n} rows to data_audit_results")

    return run_id, results, reclass_events, {
        "summary_md": summary_path,
        "anomalies_csv": anomalies_path,
        "json_dir": output_dir,
    }
