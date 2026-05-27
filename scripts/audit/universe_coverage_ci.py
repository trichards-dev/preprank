"""Universe-coverage CI gate.

Reese 2026-05-27 B1.2a requirement:
  - 2025 sport-season: engine universe must be ≥ 95% of LHSAA published
    count per sport (using LHSAA_2025_26_VERIFIED_TOTALS from the
    alignment loader).
  - 2021-2024 sport-seasons: engine universe must be ≥ 95% of actual
    game participants (reuses the B0 phantom_share methodology).
  - Fail loudly on any sport-season below threshold — exit code 1.

Run as part of CI on any change touching teams.sport_id or related
ingest. Standalone CLI for ad-hoc runs.

Output: reports/audits/universe_coverage_ci_<ts>.{md,json}, plus exit
status (0 = all sport-seasons pass; 1 = at least one below threshold).
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

from engine.data.lhsaa_alignment import LHSAA_2025_26_VERIFIED_TOTALS


COVERAGE_THRESHOLD = 0.95
"""≥95% per (sport, season) required to pass."""

SPORTS = list(LHSAA_2025_26_VERIFIED_TOTALS.keys())
HISTORICAL_SEASONS = [2021, 2022, 2023, 2024]
CURRENT_SEASON = 2025


def make_supabase():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def load_sport_id_map(sb) -> dict[str, int]:
    return {row["name"]: row["id"] for row in sb.table("sports").select("id, name").execute().data}


def engine_universe_size(sb, sport_id: int, season_year: int) -> int:
    """teams.sport_id × teams.season_year row count."""
    n, offset, page = 0, 0, 1000
    while True:
        res = (
            sb.table("teams")
            .select("id")
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


def actual_game_participants(sb, sport_id: int, season_year: int) -> int:
    """Distinct teams appearing in games for this sport-season,
    filtered to engine.validator.data.load_games conditions."""
    rows, offset, page = [], 0, 1000
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
    teams = set()
    for g in rows:
        if g.get("status") not in ("final", "forfeit"):
            continue
        if g.get("home_score") is None or g.get("away_score") is None:
            continue
        if g.get("is_out_of_state"):
            continue
        if g.get("home_team_id") is not None:
            teams.add(g["home_team_id"])
        if g.get("away_team_id") is not None:
            teams.add(g["away_team_id"])
    return len(teams)


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="python scripts/audit/universe_coverage_ci.py",
        description="Universe-coverage CI gate (Reese 2026-05-27 B1.2a)",
    )
    ap.add_argument("--output-dir", default="reports/audits")
    ap.add_argument("--threshold", type=float, default=COVERAGE_THRESHOLD)
    ap.add_argument("--fail-on-below-threshold", action="store_true", default=True)
    args = ap.parse_args()

    sb = make_supabase()
    sport_id_map = load_sport_id_map(sb)

    findings = {
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "threshold": args.threshold,
        "rows": [],
    }
    fails = []

    # 2025: engine universe vs LHSAA published
    print(f"\n=== 2025: engine universe vs LHSAA published (≥{args.threshold*100:.0f}%) ===\n")
    print(f"{'sport':<18} {'engine':>7} {'lhsaa':>6} {'coverage':>10} {'status':>8}")
    for sport, lhsaa_n in LHSAA_2025_26_VERIFIED_TOTALS.items():
        sid = sport_id_map.get(sport)
        if sid is None:
            continue
        engine_n = engine_universe_size(sb, sid, CURRENT_SEASON)
        coverage = engine_n / lhsaa_n if lhsaa_n > 0 else float("nan")
        passed = coverage >= args.threshold
        status = "PASS" if passed else "FAIL"
        findings["rows"].append({
            "season": CURRENT_SEASON, "sport": sport,
            "engine_universe": engine_n, "reference": lhsaa_n,
            "reference_label": "LHSAA published",
            "coverage": coverage, "passed": passed,
        })
        if not passed:
            fails.append({"season": CURRENT_SEASON, "sport": sport,
                          "engine": engine_n, "reference": lhsaa_n, "coverage": coverage})
        print(f"{sport:<18} {engine_n:>7} {lhsaa_n:>6} {coverage*100:>9.1f}% {status:>8}")

    # Historical: engine universe vs actual game participants
    print(f"\n=== Historical (2021-2024): engine vs actual game participants (≥{args.threshold*100:.0f}%) ===\n")
    print(f"{'season':<7} {'sport':<18} {'engine':>7} {'actual':>7} {'coverage':>10} {'status':>8}")
    for season in HISTORICAL_SEASONS:
        for sport in SPORTS:
            sid = sport_id_map.get(sport)
            if sid is None:
                continue
            engine_n = engine_universe_size(sb, sid, season)
            actual_n = actual_game_participants(sb, sid, season)
            # If both 0, skip (sport may not have data for that season)
            if engine_n == 0 and actual_n == 0:
                continue
            # Reference is the max of engine_universe and actual_participants —
            # the engine should contain at least every team that played, so we
            # measure how well engine_universe covers actual_participants.
            if actual_n == 0:
                # No games for this sport-season: skip
                continue
            coverage = min(engine_n, actual_n) / actual_n
            passed = coverage >= args.threshold
            status = "PASS" if passed else "FAIL"
            findings["rows"].append({
                "season": season, "sport": sport,
                "engine_universe": engine_n, "reference": actual_n,
                "reference_label": "actual game participants",
                "coverage": coverage, "passed": passed,
            })
            if not passed:
                fails.append({"season": season, "sport": sport,
                              "engine": engine_n, "reference": actual_n, "coverage": coverage})
            print(f"{season:<7} {sport:<18} {engine_n:>7} {actual_n:>7} {coverage*100:>9.1f}% {status:>8}")

    findings["fails"] = fails
    findings["n_fail"] = len(fails)
    findings["n_pass"] = sum(1 for r in findings["rows"] if r["passed"])
    findings["n_total"] = len(findings["rows"])

    # Write artifacts
    out_dir = REPO_ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y-%m-%d-%H%M%S")
    (out_dir / f"universe_coverage_ci_{ts}.json").write_text(
        json.dumps(findings, indent=2, default=str)
    )

    # Markdown
    lines = []
    lines.append(f"# Universe-coverage CI — {findings['generated_utc']}")
    lines.append("")
    lines.append(f"Threshold: {args.threshold*100:.0f}%")
    lines.append(f"Pass: {findings['n_pass']} / {findings['n_total']}")
    lines.append(f"Fail: {findings['n_fail']}")
    lines.append("")
    if fails:
        lines.append("## Failing sport-seasons")
        lines.append("")
        lines.append("| Season | Sport | Engine | Reference | Coverage |")
        lines.append("|---|---|---:|---:|---:|")
        for f in fails:
            lines.append(f"| {f['season']} | {f['sport']} | {f['engine']} | {f['reference']} | {f['coverage']*100:.1f}% |")
        lines.append("")
        lines.append(f"**CI GATE: FAIL.** {len(fails)} sport-seasons below {args.threshold*100:.0f}% coverage.")
    else:
        lines.append(f"**CI GATE: PASS.** All sport-seasons at or above {args.threshold*100:.0f}% coverage.")
    (out_dir / f"universe_coverage_ci_{ts}.md").write_text("\n".join(lines))

    print()
    print(f"Summary: {findings['n_pass']} pass, {findings['n_fail']} fail / {findings['n_total']} sport-seasons")
    print(f"Artifacts: reports/audits/universe_coverage_ci_{ts}.{{md,json}}")

    if fails and args.fail_on_below_threshold:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
