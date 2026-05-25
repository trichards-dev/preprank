"""Report writers for Phase 0 audit results.

Three on-disk artifacts + one DB persist:
  * reports/data_audit/<sport>_<season>.json    — full per-check results
  * reports/data_audit/SUMMARY.md               — pivot pass/warn/fail per sport
  * reports/data_audit/anomalies.csv            — flat anomaly list
  * data_audit_results table                    — run-id keyed history
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.audit.checks import CheckResult
from scripts.audit.reclass_events import ReclassEvent


STATUS_RANK = {"fail": 3, "warn": 2, "pass": 1, "info": 0}
BLOCKING_CHECKS = {"0.1_home_away_sanity", "0.2_score_distribution",
                   "0.3_team_game_balance", "0.4_league_arithmetic",
                   "0.7_cross_source"}
ALL_CHECK_ORDER = [
    "0.1_home_away_sanity",
    "0.2_score_distribution",
    "0.3_team_game_balance",
    "0.4_league_arithmetic",
    "0.5_mercy_rule",
    "0.6_division_drift",
    "0.7_cross_source",
]
STATUS_BADGE = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "info": "INFO"}


def _ensure_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)


def write_json_per_sport_season(results: list[CheckResult], output_dir: Path) -> list[Path]:
    """One JSON file per (sport_name, season_year). Cross-sport (drift) gets its own."""
    _ensure_dir(output_dir)
    by_key: dict[tuple[str, int | None], list[CheckResult]] = {}
    for r in results:
        key = (r.sport_name or "_global", r.season_year)
        by_key.setdefault(key, []).append(r)

    written: list[Path] = []
    for (sport, season), bucket in sorted(by_key.items(), key=lambda x: (x[0][0], x[0][1] or 0)):
        safe_sport = sport.replace(" ", "_")
        season_str = season if season is not None else "cross-season"
        path = output_dir / f"{safe_sport}_{season_str}.json"
        payload = {
            "sport": sport,
            "season_year": season,
            "n_checks": len(bucket),
            "results": [r.to_dict() for r in bucket],
        }
        path.write_text(json.dumps(payload, indent=2, default=str))
        written.append(path)
    return written


def _worst(statuses: list[str]) -> str:
    if not statuses:
        return "info"
    return max(statuses, key=lambda s: STATUS_RANK.get(s, -1))


def _readiness(by_check: dict[str, str]) -> str:
    statuses = [by_check.get(c, "info") for c in BLOCKING_CHECKS]
    worst = _worst(statuses)
    if worst == "fail":
        return "BLOCKED"
    if worst == "warn":
        return "WATCH"
    return "READY"


def write_summary_md(
    results: list[CheckResult],
    output_dir: Path,
    run_id: str,
    reclass_events: list[ReclassEvent] | None = None,
) -> Path:
    _ensure_dir(output_dir)
    path = output_dir / "SUMMARY.md"

    # Pivot 1: per-sport rollup (worst status across seasons per check)
    by_sport: dict[str, dict[str, list[str]]] = {}
    for r in results:
        if not r.sport_name:
            continue
        by_sport.setdefault(r.sport_name, {}).setdefault(r.check_name, []).append(r.status)

    sports = sorted(by_sport.keys())
    lines: list[str] = []
    lines.append(f"# Phase 0 Data Audit — SUMMARY")
    lines.append("")
    lines.append(f"Run ID: `{run_id}`  ")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")

    # Gating-metric section: Cat 1 / Cat 2 / Cat 3 rates for football
    football_cat = [
        (r.season_year,
         r.metrics.get("cat1_team_rate"),
         r.metrics.get("cat2_team_rate"),
         r.metrics.get("cat3_team_rate"),
         r.metrics.get("n_rows_compared"),
         r.status)
        for r in results
        if r.sport_name == "Football" and r.check_name == "0.7_cross_source"
    ]
    if football_cat:
        lines.append("## Gating metric: Football Cat 1 / Cat 2 / Cat 3 rates")
        lines.append("")
        lines.append("| Season | Cat 1 (missing) | Cat 2 (extras) | Cat 3 (wrong winner) | Teams cmp | Status |")
        lines.append("|---|---|---|---|---|---|")
        for season, c1, c2, c3, n_cmp, st in sorted(football_cat):
            c1s = "n/a" if c1 is None else f"{c1}"
            c2s = "n/a" if c2 is None else f"{c2}"
            c3s = "n/a" if c3 is None else f"{c3}"
            lines.append(f"| {season} | {c1s} | {c2s} | {c3s} | {n_cmp or 0} | **{st.upper()}** |")
        lines.append("")
        lines.append("Cat 1 PASS ≤5% / WARN ≤10% / FAIL >10%. Cat 2 PASS ≤10% / WARN ≤20% / "
                     "FAIL >20%. Cat 3 PASS ≤2% / WARN ≤5% / FAIL >5%. Status = worst-of.")
        lines.append("")

    # Reclassification events (distinct section per Reese's 2026-05-25 review)
    if reclass_events:
        lines.append("## Reclassification events detected")
        lines.append("")
        lines.append("Fleet-wide division-change events (≥ threshold of teams changed division "
                     "vs prior season). Load-bearing for walk-forward fold construction.")
        lines.append("")
        lines.append("| Sport | Season | Prior | Schools both seasons | Changed | Fraction | Threshold |")
        lines.append("|---|---|---|---|---|---|---|")
        for ev in sorted(reclass_events, key=lambda e: (e.sport_name, e.season_year)):
            lines.append(
                f"| {ev.sport_name} | {ev.season_year} | {ev.prior_season} | "
                f"{ev.n_schools_both_seasons} | {ev.n_changed} | {ev.change_fraction} | {ev.threshold} |"
            )
        lines.append("")
        for ev in sorted(reclass_events, key=lambda e: (e.sport_name, e.season_year)):
            lines.append(f"- **{ev.sport_name} {ev.prior_season}→{ev.season_year}** top transitions:")
            for transition, n in list(ev.division_transitions.items())[:5]:
                lines.append(f"  - `{transition}`: {n}")
        lines.append("")

    lines.append("## Overall verdict by sport")
    lines.append("")
    header = "| Sport | " + " | ".join(c.split("_", 1)[0] for c in ALL_CHECK_ORDER) + " | Readiness |"
    sep = "|---" * (len(ALL_CHECK_ORDER) + 2) + "|"
    lines.append(header)
    lines.append(sep)
    for sport in sports:
        cells = []
        by_check: dict[str, str] = {}
        for c in ALL_CHECK_ORDER:
            worst = _worst(by_sport[sport].get(c, []))
            by_check[c] = worst
            cells.append(STATUS_BADGE[worst])
        readiness = _readiness(by_check)
        lines.append(f"| {sport} | " + " | ".join(cells) + f" | **{readiness}** |")
    lines.append("")
    lines.append("Blocking checks (any FAIL ⇒ BLOCKED): " + ", ".join(sorted(BLOCKING_CHECKS)))
    lines.append("")

    # Pivot 2: per-sport season-by-season detail
    for sport in sports:
        lines.append(f"## {sport}")
        lines.append("")
        # Collect seasons present for per-season checks
        per_season: dict[int, dict[str, CheckResult]] = {}
        cross_season_rows: list[CheckResult] = []
        for r in results:
            if r.sport_name != sport:
                continue
            if r.season_year is None:
                cross_season_rows.append(r)
            else:
                per_season.setdefault(r.season_year, {})[r.check_name] = r
        if per_season:
            per_season_checks = [c for c in ALL_CHECK_ORDER if c != "0.6_classification_drift"]
            hdr = "| Season | " + " | ".join(c.split("_", 1)[0] for c in per_season_checks) + " |"
            sp = "|---" * (len(per_season_checks) + 1) + "|"
            lines.append(hdr)
            lines.append(sp)
            for season in sorted(per_season.keys()):
                cells = []
                for c in per_season_checks:
                    r = per_season[season].get(c)
                    if r is None:
                        cells.append("—")
                    else:
                        cells.append(f"{STATUS_BADGE[r.status]} {_inline_metric(r)}")
                lines.append(f"| {season} | " + " | ".join(cells) + " |")
            lines.append("")
        if cross_season_rows:
            lines.append("**Cross-season checks:**")
            for r in cross_season_rows:
                lines.append(f"- {r.check_name}: {STATUS_BADGE[r.status]} — {_inline_metric(r)}")
            lines.append("")

    path.write_text("\n".join(lines))
    return path


def _inline_metric(r: CheckResult) -> str:
    """Pluck a one-glance number for the SUMMARY cell."""
    m = r.metrics
    if r.check_name == "0.1_home_away_sanity":
        return f"({m.get('home_win_rate')})"
    if r.check_name == "0.2_score_distribution":
        return f"(μ={m.get('total_score_mean')})"
    if r.check_name == "0.3_team_game_balance":
        return f"({m.get('frac_balanced')})"
    if r.check_name == "0.4_league_arithmetic":
        return f"({m.get('n_divisions')} div)"
    if r.check_name == "0.5_mercy_rule":
        return f"({m.get('mercy_rate')})"
    if r.check_name == "0.6_division_drift":
        return f"({m.get('n_drifted_above_threshold')}/{m.get('n_schools')} drift)"
    if r.check_name == "0.7_cross_source":
        c1 = m.get("cat1_team_rate")
        c2 = m.get("cat2_team_rate")
        c3 = m.get("cat3_team_rate")
        n_cmp = m.get("n_rows_compared")
        n_pdfs = m.get("n_pdfs_parsed")
        return f"(C1 {c1} / C2 {c2} / C3 {c3}, {n_cmp or 0} cmp, {n_pdfs or 0} PDFs)"
    return ""


def write_anomalies_csv(results: list[CheckResult], output_dir: Path) -> Path:
    """Flat one-row-per-anomaly CSV across all checks."""
    _ensure_dir(output_dir)
    path = output_dir / "anomalies.csv"

    rows: list[dict[str, Any]] = []
    for r in results:
        for a in r.anomalies:
            row = {
                "sport": r.sport_name,
                "season": r.season_year,
                "check": r.check_name,
                "status": r.status,
            }
            # Flatten anomaly dict to string-coerced values; JSON-blob nested.
            for k, v in a.items():
                if isinstance(v, (dict, list)):
                    row[k] = json.dumps(v, default=str)
                else:
                    row[k] = v
            rows.append(row)

    if not rows:
        path.write_text("sport,season,check,status\n")
        return path

    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def persist_to_db(sb, results: list[CheckResult], run_id: str) -> int:
    """Insert one row per result into data_audit_results.

    Returns the count inserted. Chunks at 200 to stay friendly to the REST API.
    """
    payload = [
        {
            "run_id": run_id,
            "sport_id": r.sport_id,
            "season_year": r.season_year,
            "check_name": r.check_name,
            "status": r.status,
            "details": {
                "metrics": r.metrics,
                "thresholds": r.thresholds,
                "anomaly_count": len(r.anomalies),
            },
        }
        for r in results
    ]
    written = 0
    for i in range(0, len(payload), 200):
        batch = payload[i : i + 200]
        sb.table("data_audit_results").insert(batch).execute()
        written += len(batch)
    return written
