"""Step 0 — phantom_share 40-cell diagnostic.

Reese 2026-05-27 evening: Phase 4d halted. Thomas' LHSAA 2025-2026
participation matrix shows real sport-participation rates that don't
match the engine's universe size. Hypothesis: the engine treats every
team in the `teams` table with matching (sport_id, season_year) as
in-universe, but many of those teams don't actually field that sport
in that season → "phantom teams" pollute LS basis, recent_form
neighborhoods, etc.

For each (sport, season) in 2021-2025, compute:
  - engine_universe   = |{tid : teams.sport_id == sport AND teams.season_year == season}|
                        (matches engine.validator.data._filter_team_ids_for_sport_season)
  - actual_participants = |{home_team_id ∪ away_team_id} across games with that sport+season,
                           filtered to final/forfeit + scored + non-OOS,
                           matching engine.validator.data.load_games filters|
  - phantom_share = (engine_universe - actual_participants) / engine_universe

Cross-validation against LHSAA 2025-2026 published counts:
  Football 324, Volleyball 284, Boys Basketball 404,
  Girls Basketball 410, Boys Soccer 196, Girls Soccer 189,
  Baseball 375, Softball 388

Output: reports/audits/phantom_share_diagnostic.{md,json}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / "apps" / "api" / ".env")


SPORTS = [
    "Football",
    "Volleyball",
    "Boys Basketball",
    "Girls Basketball",
    "Boys Soccer",
    "Girls Soccer",
    "Baseball",
    "Softball",
]
SEASONS = [2021, 2022, 2023, 2024, 2025]

LHSAA_2025_2026 = {
    "Football": 324,
    "Volleyball": 284,
    "Boys Basketball": 404,
    "Girls Basketball": 410,
    "Boys Soccer": 196,
    "Girls Soccer": 189,
    "Baseball": 375,
    "Softball": 388,
}


def make_supabase():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def load_sport_id_map(sb) -> dict[str, int]:
    res = sb.table("sports").select("id, name").execute()
    return {row["name"]: row["id"] for row in res.data}


def engine_universe_size(sb, sport_id: int, season_year: int) -> int:
    """Mirror engine.validator.data._filter_team_ids_for_sport_season:
    teams.sport_id == sport_id AND teams.season_year == season_year.
    """
    n = 0
    offset, page = 0, 1000
    while True:
        res = (
            sb.table("teams")
            .select("id", count="exact" if offset == 0 else None)
            .eq("sport_id", sport_id)
            .eq("season_year", season_year)
            .range(offset, offset + page - 1)
            .execute()
        )
        if not res.data:
            break
        n += len(res.data)
        if len(res.data) < page:
            break
        offset += page
    return n


def actual_participants(sb, sport_id: int, season_year: int) -> tuple[int, int, int]:
    """Distinct teams appearing as home_team or away_team in games with this
    sport+season, applying engine.validator.data.load_games filters:
      - status in (final, forfeit)
      - scores non-null
      - not OOS

    Returns (n_distinct_teams, n_games_after_filter, n_games_before_filter).
    """
    rows = []
    offset, page = 0, 1000
    while True:
        res = (
            sb.table("games")
            .select("home_team_id, away_team_id, status, home_score, away_score, is_out_of_state")
            .eq("sport_id", sport_id)
            .eq("season_year", season_year)
            .range(offset, offset + page - 1)
            .execute()
        )
        if not res.data:
            break
        rows.extend(res.data)
        if len(res.data) < page:
            break
        offset += page

    n_raw = len(rows)
    filtered = [
        g for g in rows
        if g.get("status") in ("final", "forfeit")
        and g.get("home_score") is not None
        and g.get("away_score") is not None
        and not g.get("is_out_of_state")
    ]
    n_filt = len(filtered)
    teams_in_games = set()
    for g in filtered:
        if g.get("home_team_id") is not None:
            teams_in_games.add(g["home_team_id"])
        if g.get("away_team_id") is not None:
            teams_in_games.add(g["away_team_id"])
    return len(teams_in_games), n_filt, n_raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="reports/audits")
    args = ap.parse_args()

    sb = make_supabase()
    sport_id_map = load_sport_id_map(sb)
    missing = [s for s in SPORTS if s not in sport_id_map]
    if missing:
        print(f"[phantom] WARNING: sports not found in sports table: {missing}")

    matrix = []  # list of dicts: {sport, season, engine_universe, actual_participants, phantom_share}
    for sport in SPORTS:
        sid = sport_id_map.get(sport)
        if sid is None:
            continue
        for season in SEASONS:
            eng = engine_universe_size(sb, sid, season)
            actual, n_games, n_raw = actual_participants(sb, sid, season)
            phantom = (eng - actual) / eng if eng > 0 else float("nan")
            matrix.append({
                "sport": sport,
                "season": season,
                "engine_universe": eng,
                "actual_participants": actual,
                "phantom_share": phantom,
                "n_games_filtered": n_games,
                "n_games_raw": n_raw,
            })
            print(f"  {sport:18} {season}  eng={eng:>4}  actual={actual:>4}  "
                  f"phantom={phantom*100:>+5.1f}%  games={n_games}/{n_raw}")

    # ---------------------------------------------------------------------------
    # Cross-validation against LHSAA 2025-2026 published counts
    # ---------------------------------------------------------------------------
    cross_val = []
    for sport, lhsaa_n in LHSAA_2025_2026.items():
        row = next((r for r in matrix if r["sport"] == sport and r["season"] == 2025), None)
        if not row:
            continue
        engine = row["engine_universe"]
        actual = row["actual_participants"]
        cross_val.append({
            "sport": sport,
            "lhsaa_published": lhsaa_n,
            "engine_universe_2025": engine,
            "actual_participants_2025": actual,
            "engine_vs_lhsaa_diff": engine - lhsaa_n,
            "actual_vs_lhsaa_diff": actual - lhsaa_n,
            "actual_vs_lhsaa_pct": (actual - lhsaa_n) / lhsaa_n if lhsaa_n else float("nan"),
        })

    # Artifacts
    now = datetime.utcnow().isoformat() + "Z"
    output_dir = REPO_ROOT / args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    out_json = output_dir / "phantom_share_diagnostic.json"
    out_md = output_dir / "phantom_share_diagnostic.md"
    out_json.write_text(json.dumps({
        "generated_utc": now,
        "sports": SPORTS,
        "seasons": SEASONS,
        "matrix": matrix,
        "cross_validation_2025": cross_val,
        "lhsaa_published_2025_2026": LHSAA_2025_2026,
    }, indent=2, default=str))

    # Markdown — 40-cell phantom_share table + cross-validation + summary
    lines = []
    lines.append("# Phantom-Share Diagnostic — Step 0")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append("")
    lines.append("**Engine universe**: teams.sport_id == sport AND teams.season_year == season")
    lines.append("  (mirrors `engine.validator.data._filter_team_ids_for_sport_season`)")
    lines.append("")
    lines.append("**Actual participants**: distinct home_team_id ∪ away_team_id across games")
    lines.append("  with that sport+season, filtered to status ∈ (final, forfeit), scored,")
    lines.append("  not OOS (mirrors `engine.validator.data.load_games`)")
    lines.append("")
    lines.append("**phantom_share** = (engine_universe − actual_participants) / engine_universe")
    lines.append("")
    lines.append("## 40-cell phantom_share matrix")
    lines.append("")
    header = "| Sport | " + " | ".join(str(s) for s in SEASONS) + " |"
    sep = "|---|" + ":---:|" * len(SEASONS)
    lines.append(header)
    lines.append(sep)
    for sport in SPORTS:
        row_cells = [sport]
        for season in SEASONS:
            cell = next((r for r in matrix if r["sport"] == sport and r["season"] == season), None)
            if cell is None:
                row_cells.append("n/a")
            else:
                phantom = cell["phantom_share"] * 100
                row_cells.append(
                    f"{cell['actual_participants']}/{cell['engine_universe']} ({phantom:+.1f}%)"
                )
        lines.append("| " + " | ".join(row_cells) + " |")
    lines.append("")
    lines.append("Cell format: `actual/engine (phantom%)`. Negative phantom% means actual > engine (would be unusual — flag).")
    lines.append("")

    lines.append("## Cross-validation against LHSAA 2025-2026 published participation")
    lines.append("")
    lines.append("| Sport | LHSAA published | Engine universe (2025) | Actual participants (2025) | Actual vs LHSAA | Engine vs LHSAA |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for c in cross_val:
        actual_pct = c["actual_vs_lhsaa_pct"] * 100
        lines.append(
            f"| {c['sport']} | {c['lhsaa_published']} | {c['engine_universe_2025']} | "
            f"{c['actual_participants_2025']} | {c['actual_vs_lhsaa_diff']:+d} ({actual_pct:+.1f}%) | "
            f"{c['engine_vs_lhsaa_diff']:+d} |"
        )
    lines.append("")

    # Summary
    lines.append("## Summary stats")
    lines.append("")
    n_cells = len(matrix)
    n_with_phantom_gt_5pct = sum(1 for r in matrix if r["phantom_share"] > 0.05)
    n_with_phantom_gt_20pct = sum(1 for r in matrix if r["phantom_share"] > 0.20)
    lines.append(f"- Cells with phantom_share > 5%: {n_with_phantom_gt_5pct} / {n_cells}")
    lines.append(f"- Cells with phantom_share > 20%: {n_with_phantom_gt_20pct} / {n_cells}")
    if matrix:
        avg = sum(r["phantom_share"] for r in matrix) / len(matrix)
        lines.append(f"- Mean phantom_share across all cells: {avg*100:+.1f}%")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if n_with_phantom_gt_5pct < n_cells // 4:
        lines.append("**Phantom-team hypothesis NOT confirmed in our data.** "
                     "If engine_universe ≈ actual_participants everywhere, the engine is already "
                     "doing the filter. Phase 4d Massey lift would not be primarily phantom-driven; "
                     "the structural Massey fix proceeds as originally planned.")
    else:
        lines.append("**Phantom-team hypothesis CONFIRMED.** Engine universe materially exceeds "
                     "actual participants on many (sport, season) cells. Cascade implications for "
                     "Phase 2 baseline, Phase 4a/4b/4c, and Phase 4d results. Step 1 (universe "
                     "filter at data layer) proceeds.")
    lines.append("")
    lines.append("Halt after Step 0 per Reese 2026-05-27 evening sequencing. No code changes "
                 "to massey_od.py / runner_v2.py / feature modules until sign-off.")

    out_md.write_text("\n".join(lines))

    print()
    print("=" * 70)
    print(f"Cells with phantom > 5%:  {n_with_phantom_gt_5pct} / {n_cells}")
    print(f"Cells with phantom > 20%: {n_with_phantom_gt_20pct} / {n_cells}")
    print(f"Artifacts:")
    print(f"  {out_md.relative_to(REPO_ROOT)}")
    print(f"  {out_json.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
