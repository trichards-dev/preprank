#!/usr/bin/env python3
"""Generate a Layer-1 validation report comparing engine ratings vs LHSAA officials.

Reads `power_ratings` (both source='engine' and source='lhsaa_official'),
plus `games`, `teams`, `schools`, `sports`. Writes:

  - data/validation/<sport>_<season>_weekly.csv   — wide table per team per week
  - docs/validation/engine_vs_lhsaa_<date>.md      — summary report with stats,
                                                     per-sport-season-division rankings,
                                                     and biggest disagreements

Usage:
    python scripts/validate_engine_vs_lhsaa.py
    python scripts/validate_engine_vs_lhsaa.py --only-sport Football
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

from supabase import create_client


SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ywlaekkxkwfznwuupggi.supabase.co")
ROOT = Path(__file__).resolve().parents[1]
VALIDATION_CSV_DIR = ROOT / "data" / "validation"
REPORT_DIR = ROOT / "docs" / "validation"

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


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation. Returns None if undefined."""
    if len(xs) < 2 or len(xs) != len(ys):
        return None

    def rank(vals: list[float]) -> list[float]:
        idx = sorted(range(len(vals)), key=lambda i: -vals[i])  # highest = rank 1
        ranks = [0.0] * len(vals)
        # Handle ties by averaging
        i = 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and vals[idx[j + 1]] == vals[idx[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[idx[k]] = avg_rank
            i = j + 1
        return ranks

    rx = rank(xs)
    ry = rank(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(len(rx)))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(len(rx))))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(len(ry))))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(len(xs)))
    dx = math.sqrt(sum((xs[i] - mx) ** 2 for i in range(len(xs))))
    dy = math.sqrt(sum((ys[i] - my) ** 2 for i in range(len(ys))))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _load_sports_map(sb) -> dict[int, str]:
    res = sb.table("sports").select("id,name").execute()
    return {r["id"]: r["name"] for r in res.data}


def _load_teams_with_schools(sb) -> dict[int, dict]:
    """team_id -> {school_name, division, classification, season_year, sport_id, select_status}"""
    out: dict[int, dict] = {}
    offset, page = 0, 1000
    while True:
        res = (sb.table("teams").select("id,school_id,division,select_status,season_year,sport_id")
               .range(offset, offset + page - 1).execute())
        if not res.data:
            break
        for r in res.data:
            out[r["id"]] = r
        if len(res.data) < page:
            break
        offset += page

    school_ids = list({r["school_id"] for r in out.values() if r.get("school_id")})
    schools: dict[int, dict] = {}
    for i in range(0, len(school_ids), 500):
        chunk = school_ids[i : i + 500]
        res = sb.table("schools").select("id,name,classification").in_("id", chunk).execute()
        for s in res.data:
            schools[s["id"]] = s
    for t in out.values():
        sch = schools.get(t.get("school_id"), {})
        t["school_name"] = sch.get("name", f"sid:{t.get('school_id')}")
        t["classification"] = sch.get("classification")
    return out


def _load_ratings(sb, source: str, season_year: int, sport_id: int | None = None) -> list[dict]:
    """Load all power_ratings rows for a source+season, optionally filtered to teams in one sport.

    The DB doesn't store sport_id on power_ratings; we filter post-hoc via team_id.
    """
    out: list[dict] = []
    offset, page = 0, 1000
    q = (sb.table("power_ratings")
         .select("team_id,week_number,season_year,power_rating,strength_factor,"
                 "rank_in_division,source,snapshot_date")
         .eq("source", source).eq("season_year", season_year))
    while True:
        res = q.range(offset, offset + page - 1).execute()
        if not res.data:
            break
        out.extend(res.data)
        if len(res.data) < page:
            break
        offset += page
    return out


def _write_weekly_csv(path: Path, engine_rows: list[dict], teams: dict[int, dict],
                     lhsaa_final_by_team: dict[int, float]) -> None:
    """Write a CSV: rows=teams sorted by final engine rating DESC,
    cols = school, division, week_1..week_N, engine_final, lhsaa_final, rating_delta."""
    if not engine_rows:
        return
    by_team_week: dict[int, dict[int, float]] = defaultdict(dict)
    for r in engine_rows:
        by_team_week[r["team_id"]][r["week_number"]] = float(r["power_rating"])
    max_week = max(r["week_number"] for r in engine_rows)
    team_ids = sorted(
        by_team_week.keys(),
        key=lambda t: -by_team_week[t].get(max_week, by_team_week[t][max(by_team_week[t])])
    )
    week_cols = [f"week_{w}" for w in range(1, max_week + 1)]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["team_id", "school", "division", *week_cols,
             "engine_final", "lhsaa_final", "rating_delta"]
        )
        for tid in team_ids:
            t = teams.get(tid, {})
            engine_final = by_team_week[tid].get(max_week)
            if engine_final is None and by_team_week[tid]:
                engine_final = by_team_week[tid][max(by_team_week[tid])]
            lhsaa_final = lhsaa_final_by_team.get(tid)
            delta = (engine_final - lhsaa_final) if (engine_final is not None and lhsaa_final is not None) else ""
            row = [tid, t.get("school_name", ""), t.get("division", "")]
            for w in range(1, max_week + 1):
                v = by_team_week[tid].get(w)
                row.append(f"{v:.4f}" if v is not None else "")
            row.append(f"{engine_final:.4f}" if engine_final is not None else "")
            row.append(f"{lhsaa_final:.4f}" if lhsaa_final is not None else "")
            row.append(f"{delta:.4f}" if delta != "" else "")
            writer.writerow(row)


def _build_lhsaa_final_map(lhsaa_rows: list[dict]) -> dict[int, float]:
    """team_id -> LHSAA Final power_rating (snapshot_date IS NULL OR latest).
    Final snapshots have snapshot_date=NULL by convention from the loader.
    """
    finals: dict[int, float] = {}
    by_team: dict[int, list[dict]] = defaultdict(list)
    for r in lhsaa_rows:
        by_team[r["team_id"]].append(r)
    for tid, rows in by_team.items():
        nulls = [r for r in rows if r.get("snapshot_date") is None]
        if nulls:
            finals[tid] = float(nulls[0]["power_rating"])
            continue
        dated = sorted(rows, key=lambda r: r.get("snapshot_date") or "")
        if dated:
            finals[tid] = float(dated[-1]["power_rating"])
    return finals


def _summarize(engine_rows: list[dict], lhsaa_finals: dict[int, float],
              teams: dict[int, dict]) -> dict:
    """Per-sport-season summary including per-division Spearman/Pearson."""
    if not engine_rows:
        return {"teams_engine": 0}

    max_week = max(r["week_number"] for r in engine_rows)
    engine_final: dict[int, float] = {}
    for r in engine_rows:
        if r["week_number"] == max_week:
            engine_final[r["team_id"]] = float(r["power_rating"])

    matched = [(tid, engine_final[tid], lhsaa_finals[tid])
               for tid in engine_final if tid in lhsaa_finals]

    by_div: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for tid, eng, lhs in matched:
        div = (teams.get(tid, {}) or {}).get("division") or "?"
        by_div[div].append((eng, lhs))

    div_stats = {}
    for div, pairs in by_div.items():
        engs = [p[0] for p in pairs]
        lhss = [p[1] for p in pairs]
        div_stats[div] = {
            "n": len(pairs),
            "spearman": _spearman(engs, lhss),
            "pearson": _pearson(engs, lhss),
        }

    overall_engs = [p[0] for div in by_div.values() for p in div]
    overall_lhss = [p[1] for div in by_div.values() for p in div]
    overall = {
        "n_matched": len(matched),
        "spearman_overall": _spearman(overall_engs, overall_lhss) if overall_engs else None,
        "pearson_overall": _pearson(overall_engs, overall_lhss) if overall_engs else None,
    }
    return {
        "teams_engine": len(engine_final),
        "teams_lhsaa": len(lhsaa_finals),
        "teams_matched": len(matched),
        "max_week": max_week,
        "by_division": div_stats,
        **overall,
    }


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _top_disagreements(engine_rows: list[dict], lhsaa_finals: dict[int, float],
                      teams: dict[int, dict], n: int = 10) -> list[dict]:
    """Where engine rank ≠ LHSAA rank within division by the widest margin."""
    if not engine_rows or not lhsaa_finals:
        return []
    max_week = max(r["week_number"] for r in engine_rows)

    # Build engine final rank within division
    by_div: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for r in engine_rows:
        if r["week_number"] != max_week:
            continue
        div = (teams.get(r["team_id"], {}) or {}).get("division") or "?"
        by_div[div].append((r["team_id"], float(r["power_rating"])))
    engine_rank: dict[int, int] = {}
    for div, lst in by_div.items():
        lst.sort(key=lambda x: -x[1])
        for i, (tid, _) in enumerate(lst, start=1):
            engine_rank[tid] = i

    # Build LHSAA final rank within division (using same team→division)
    lhs_by_div: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for tid, r in lhsaa_finals.items():
        div = (teams.get(tid, {}) or {}).get("division") or "?"
        lhs_by_div[div].append((tid, r))
    lhsaa_rank: dict[int, int] = {}
    for div, lst in lhs_by_div.items():
        lst.sort(key=lambda x: -x[1])
        for i, (tid, _) in enumerate(lst, start=1):
            lhsaa_rank[tid] = i

    rows = []
    for tid in engine_rank:
        if tid not in lhsaa_rank:
            continue
        delta = engine_rank[tid] - lhsaa_rank[tid]
        rows.append({
            "team_id": tid,
            "school": (teams.get(tid, {}) or {}).get("school_name", ""),
            "division": (teams.get(tid, {}) or {}).get("division", ""),
            "engine_rank": engine_rank[tid],
            "lhsaa_rank": lhsaa_rank[tid],
            "delta": delta,
        })
    rows.sort(key=lambda r: -abs(r["delta"]))
    return rows[:n]


def _write_report(report_path: Path, sport_season_results: list[dict]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Engine vs LHSAA Validation Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("Compares engine-computed power ratings against LHSAA's published")
    lines.append("end-of-season Power Ratings (where available). Engine ratings are")
    lines.append("the final-week snapshot from the weekly backfill.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Sport | Season | Engine N | LHSAA N | Matched | Spearman ρ | Pearson r |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in sport_season_results:
        s = r.get("summary", {}) or {}
        lines.append(
            f"| {r['sport']} | {r['season']} | {s.get('teams_engine', 0)} | "
            f"{s.get('teams_lhsaa', 0)} | {s.get('teams_matched', 0)} | "
            f"{_fmt(s.get('spearman_overall'))} | {_fmt(s.get('pearson_overall'))} |"
        )
    lines.append("")

    for r in sport_season_results:
        s = r.get("summary", {}) or {}
        slug = f"{r['sport'].replace(' ', '-').lower()}-{r['season']}"
        lines.append(f"## {r['sport']} {r['season']} <a id=\"{slug}\"></a>")
        lines.append("")
        lines.append(f"- Engine teams: **{s.get('teams_engine', 0)}** (max week {s.get('max_week', '—')})")
        lines.append(f"- LHSAA teams: **{s.get('teams_lhsaa', 0)}**")
        lines.append(f"- Matched (overlap): **{s.get('teams_matched', 0)}**")
        lines.append(f"- Spearman ρ overall: **{_fmt(s.get('spearman_overall'))}**")
        lines.append(f"- Pearson r overall : **{_fmt(s.get('pearson_overall'))}**")
        lines.append("")

        if s.get("by_division"):
            lines.append("**Per-division correlation:**")
            lines.append("")
            lines.append("| Division | N | Spearman ρ | Pearson r |")
            lines.append("|---|---|---|---|")
            for div in sorted(s["by_division"].keys()):
                d = s["by_division"][div]
                lines.append(f"| {div} | {d['n']} | {_fmt(d['spearman'])} | {_fmt(d['pearson'])} |")
            lines.append("")

        disagreements = r.get("disagreements", [])
        if disagreements:
            lines.append("**Top 10 rank disagreements (engine − LHSAA):**")
            lines.append("")
            lines.append("| School | Division | Engine rank | LHSAA rank | Δ |")
            lines.append("|---|---|---|---|---|")
            for d in disagreements:
                lines.append(
                    f"| {d['school']} | {d['division']} | {d['engine_rank']} | {d['lhsaa_rank']} | "
                    f"{d['delta']:+d} |"
                )
            lines.append("")

        csv_path = r.get("csv_path")
        if csv_path:
            try:
                rel = Path(csv_path).resolve().relative_to(ROOT)
                lines.append(f"📊 Weekly trajectories: [`{rel}`]({rel})")
                lines.append("")
            except ValueError:
                lines.append(f"📊 Weekly trajectories: `{csv_path}`")
                lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only-sport", default=None)
    p.add_argument("--only-season", type=int, default=None)
    args = p.parse_args()

    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not service_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY env var is required")
    sb = create_client(SUPABASE_URL, service_key)

    sports_map = _load_sports_map(sb)
    name_to_id = {n.lower(): i for i, n in sports_map.items()}
    teams = _load_teams_with_schools(sb)

    sports = [args.only_sport] if args.only_sport else SPORTS
    seasons = [args.only_season] if args.only_season else SEASONS

    results: list[dict] = []
    for sport_name in sports:
        sid = name_to_id.get(sport_name.lower())
        if sid is None:
            print(f"  [skip] Sport not in DB: {sport_name!r}")
            continue

        for season in seasons:
            print(f"  Loading {sport_name} {season}...")
            all_engine = _load_ratings(sb, "engine", season)
            all_lhsaa = _load_ratings(sb, "lhsaa_official", season)
            # Filter to teams in this sport
            sport_team_ids = {tid for tid, t in teams.items()
                              if t.get("sport_id") == sid and t.get("season_year") == season}
            engine_rows = [r for r in all_engine if r["team_id"] in sport_team_ids]
            lhsaa_rows = [r for r in all_lhsaa if r["team_id"] in sport_team_ids]

            lhsaa_finals = _build_lhsaa_final_map(lhsaa_rows)
            summary = _summarize(engine_rows, lhsaa_finals, teams)
            disagreements = _top_disagreements(engine_rows, lhsaa_finals, teams, n=10)

            csv_path = VALIDATION_CSV_DIR / f"{sport_name.replace(' ', '_').lower()}_{season}_weekly.csv"
            if engine_rows:
                _write_weekly_csv(csv_path, engine_rows, teams, lhsaa_finals)

            results.append({
                "sport": sport_name, "season": season,
                "summary": summary, "disagreements": disagreements,
                "csv_path": str(csv_path) if engine_rows else None,
            })

    stamp = datetime.now().strftime("%Y%m%d")
    report_path = REPORT_DIR / f"engine_vs_lhsaa_{stamp}.md"
    _write_report(report_path, results)
    print(f"\nReport: {report_path}")
    print(f"CSVs  : {VALIDATION_CSV_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
