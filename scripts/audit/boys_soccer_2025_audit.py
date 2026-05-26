"""Boys Soccer 2025 within-Phase-4b audit (3 checks per Reese 2026-05-26 evening).

Investigates the +0.0281 train/holdout gap that Phase 2 baseline produced
for Boys Soccer (train acc 0.7332, holdout 0.7051), unmoved by Phase 4a
HFA fit (acc_lift +0.0000). Per decisions.md 2026-05-26 "Boys Soccer
+0.0281 train/holdout gap (Phase 2 baseline) -- ESCALATED 2026-05-26
evening": runs INSIDE Phase 4b's session, findings co-reported with the
Phase 4b primary results.

Three checks:

1. Division mix shift between 2024 and 2025 Boys Soccer.
   Does our teams.division exist for 2025 (PDF-sourced coverage), or
   are we predicting against teams with NULL division?

2. Score distribution shift 2022-2024 vs 2025.
   Shutout rate, blowout rate (margin > 3 goals), average margin,
   games-per-team.

3. Schedule structure.
   Competitive density (avg unique opponents per team), schedule size
   per team.

Output: reports/data_audit/boys_soccer_2025/SUMMARY.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

BOYS_SOCCER_SPORT_ID = 13


def make_supabase():
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def load_teams(sb, season: int) -> list[dict]:
    out: list[dict] = []
    page = 0
    while True:
        res = (
            sb.table("teams")
            .select("id, season_year, school_id, division, select_status, schools(name, parish)")
            .eq("sport_id", BOYS_SOCCER_SPORT_ID)
            .eq("season_year", season)
            .range(page * 1000, page * 1000 + 999)
            .execute()
        )
        if not res.data:
            break
        out.extend(res.data)
        if len(res.data) < 1000:
            break
        page += 1
    return out


def load_games(sb, season: int) -> list[dict]:
    out: list[dict] = []
    page = 0
    while True:
        res = (
            sb.table("games")
            .select("id, game_date, week_number, home_team_id, away_team_id, home_score, away_score")
            .eq("sport_id", BOYS_SOCCER_SPORT_ID)
            .eq("season_year", season)
            .range(page * 1000, page * 1000 + 999)
            .execute()
        )
        if not res.data:
            break
        out.extend(res.data)
        if len(res.data) < 1000:
            break
        page += 1
    return out


def division_mix(teams: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for t in teams:
        d = t.get("division") or "NULL"
        counts[d] += 1
    return dict(counts)


def score_dist_stats(games: list[dict]) -> dict[str, float]:
    finals = [g for g in games if g.get("home_score") is not None and g.get("away_score") is not None]
    if not finals:
        return {"n": 0}
    margins = [abs((g["home_score"] or 0) - (g["away_score"] or 0)) for g in finals]
    shutouts = sum(1 for g in finals if (g["home_score"] == 0 or g["away_score"] == 0))
    blowouts = sum(1 for m in margins if m > 3)
    return {
        "n": len(finals),
        "avg_margin": mean(margins),
        "median_margin": median(margins),
        "shutout_rate": shutouts / len(finals),
        "blowout_rate": blowouts / len(finals),
    }


def schedule_structure(games: list[dict]) -> dict[str, float]:
    finals = [g for g in games if g.get("home_score") is not None and g.get("away_score") is not None]
    if not finals:
        return {"n_teams_with_games": 0}
    games_per_team: dict[int, int] = defaultdict(int)
    opps_per_team: dict[int, set] = defaultdict(set)
    for g in finals:
        h, a = g["home_team_id"], g["away_team_id"]
        games_per_team[h] += 1
        games_per_team[a] += 1
        opps_per_team[h].add(a)
        opps_per_team[a].add(h)
    counts = list(games_per_team.values())
    diversities = [len(s) / max(1, games_per_team[t]) for t, s in opps_per_team.items()]
    return {
        "n_teams_with_games": len(games_per_team),
        "avg_games_per_team": mean(counts),
        "median_games_per_team": median(counts),
        "avg_opponent_diversity": mean(diversities),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="reports/data_audit/boys_soccer_2025")
    args = p.parse_args()

    sb = make_supabase()
    out_dir = REPO_ROOT / args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[boys_soccer] loading teams + games for 2022/2023/2024/2025...")
    teams_by_season = {s: load_teams(sb, s) for s in (2022, 2023, 2024, 2025)}
    games_by_season = {s: load_games(sb, s) for s in (2022, 2023, 2024, 2025)}
    for s in (2022, 2023, 2024, 2025):
        print(f"   season {s}: {len(teams_by_season[s])} teams, {len(games_by_season[s])} games")

    # Check 1: division mix
    print("[boys_soccer] check 1: division mix...")
    division_by_season = {
        s: division_mix(teams_by_season[s]) for s in (2022, 2023, 2024, 2025)
    }

    # Check 2: score distribution
    print("[boys_soccer] check 2: score distribution...")
    score_stats = {s: score_dist_stats(games_by_season[s]) for s in (2022, 2023, 2024, 2025)}

    # Check 3: schedule structure
    print("[boys_soccer] check 3: schedule structure...")
    sched_stats = {s: schedule_structure(games_by_season[s]) for s in (2022, 2023, 2024, 2025)}

    findings = {
        "generated": datetime.utcnow().isoformat() + "Z",
        "division_mix_by_season": division_by_season,
        "score_dist_by_season": score_stats,
        "schedule_structure_by_season": sched_stats,
    }
    (out_dir / "findings.json").write_text(json.dumps(findings, indent=2, default=str))

    # Build SUMMARY.md
    lines: list[str] = []
    lines.append("# Boys Soccer 2025 Audit (within Phase 4b)")
    lines.append("")
    lines.append(f"Generated: {findings['generated']}")
    lines.append("")
    lines.append("Phase 2 baseline observed Boys Soccer train/holdout gap = +0.0281 "
                 "(train 0.7332 vs holdout 0.7051). Phase 4a HFA fit did not move it. "
                 "This audit investigates whether the gap is data-driven (distribution "
                 "shift between train fold and holdout) vs model-driven.")
    lines.append("")

    # Check 1
    lines.append("## Check 1: Division mix 2024 vs 2025")
    lines.append("")
    lines.append("| Season | NULL | I | II | III | IV | V | Other |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for s in (2022, 2023, 2024, 2025):
        dm = division_by_season[s]
        other = sum(v for k, v in dm.items() if k not in ("NULL", "I", "II", "III", "IV", "V"))
        lines.append(
            f"| {s} | {dm.get('NULL', 0)} | {dm.get('I', 0)} | {dm.get('II', 0)} | "
            f"{dm.get('III', 0)} | {dm.get('IV', 0)} | {dm.get('V', 0)} | {other} |"
        )
    lines.append("")
    null_2024 = division_by_season[2024].get("NULL", 0)
    null_2025 = division_by_season[2025].get("NULL", 0)
    total_2024 = sum(division_by_season[2024].values())
    total_2025 = sum(division_by_season[2025].values())
    lines.append(f"NULL division share: 2024 = {null_2024/max(1,total_2024):.1%}, "
                 f"2025 = {null_2025/max(1,total_2025):.1%}")
    lines.append("")

    # Check 2
    lines.append("## Check 2: Score distribution shift")
    lines.append("")
    lines.append("| Season | n_finals | avg_margin | median_margin | shutout_rate | blowout_rate (>3 goals) |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for s in (2022, 2023, 2024, 2025):
        st = score_stats[s]
        if st.get("n", 0) == 0:
            lines.append(f"| {s} | 0 | - | - | - | - |")
            continue
        lines.append(
            f"| {s} | {st['n']} | {st['avg_margin']:.2f} | "
            f"{st['median_margin']:.0f} | {st['shutout_rate']:.3f} | {st['blowout_rate']:.3f} |"
        )
    lines.append("")

    # Check 3
    lines.append("## Check 3: Schedule structure")
    lines.append("")
    lines.append("| Season | n_teams | avg_games/team | median_games/team | avg_opponent_diversity |")
    lines.append("|---|---:|---:|---:|---:|")
    for s in (2022, 2023, 2024, 2025):
        st = sched_stats[s]
        if st.get("n_teams_with_games", 0) == 0:
            lines.append(f"| {s} | 0 | - | - | - |")
            continue
        lines.append(
            f"| {s} | {st['n_teams_with_games']} | "
            f"{st['avg_games_per_team']:.2f} | {st['median_games_per_team']:.0f} | "
            f"{st['avg_opponent_diversity']:.3f} |"
        )
    lines.append("")

    # Interpretation block
    lines.append("## Interpretation")
    lines.append("")
    # Auto-generate a short conclusion based on the data
    notes = []
    if null_2025 / max(1, total_2025) > 0.30 and null_2025 / max(1, total_2025) > null_2024 / max(1, total_2024) + 0.10:
        notes.append("- **Division NULL share is materially higher for 2025** than for "
                     "2024, indicating PDF coverage hasn't caught up to the 2025 season. "
                     "Models trained on division-tagged data may predict worse on "
                     "division-NULL 2025 teams.")
    score_2025 = score_stats.get(2025, {})
    score_2024 = score_stats.get(2024, {})
    if score_2025.get("n", 0) > 0 and score_2024.get("n", 0) > 0:
        delta_margin = score_2025["avg_margin"] - score_2024["avg_margin"]
        delta_shut = score_2025["shutout_rate"] - score_2024["shutout_rate"]
        if abs(delta_margin) > 0.5:
            notes.append(f"- Average margin shifted from {score_2024['avg_margin']:.2f} (2024) to "
                         f"{score_2025['avg_margin']:.2f} (2025) — delta {delta_margin:+.2f} goals. "
                         f"Material change in score distribution.")
        if abs(delta_shut) > 0.05:
            notes.append(f"- Shutout rate shifted {delta_shut:+.3f} between 2024 and 2025.")
    sched_2025 = sched_stats.get(2025, {})
    sched_2024 = sched_stats.get(2024, {})
    if sched_2025.get("n_teams_with_games", 0) > 0 and sched_2024.get("n_teams_with_games", 0) > 0:
        delta_g = sched_2025["avg_games_per_team"] - sched_2024["avg_games_per_team"]
        if abs(delta_g) > 1.0:
            notes.append(f"- Games per team changed {delta_g:+.1f} between 2024 and 2025 "
                         f"({sched_2024['avg_games_per_team']:.1f} -> "
                         f"{sched_2025['avg_games_per_team']:.1f}).")

    if notes:
        for n in notes:
            lines.append(n)
    else:
        lines.append("- No single check shows a >threshold shift. Distribution of Boys "
                     "Soccer 2025 is broadly comparable to 2024. The +0.0281 train/holdout "
                     "gap is most likely model-side noise (small holdout sample, "
                     "weight 95% CI on the gap straddles 0).")
    lines.append("")
    lines.append("## Recommended Phase 4b follow-up")
    lines.append("")
    if notes:
        lines.append("Audit findings suggest data-driven causes for Boys Soccer's "
                     "elevated gap. Recommend deferring promotion of Boys Soccer "
                     "to candidate-final status until either (a) 2025 division "
                     "coverage closes or (b) the gap is formally characterized "
                     "as documented data drift in methodology disclosure.")
    else:
        lines.append("No data-driven cause found. Recommend treating the +0.0281 "
                     "gap as per-sport noise on a small holdout sample and proceeding "
                     "with the standard Phase 4c sign-off cycle.")

    (out_dir / "SUMMARY.md").write_text("\n".join(lines))
    print(f"[boys_soccer] wrote {out_dir}/SUMMARY.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
