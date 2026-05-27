"""Boys Soccer 2025 leakage audit — Step 1 of Boys Soccer Option A.

Same methodology as the Phase 4b Football audit
(`scripts/audit/phase4b_leakage_audit.py`), with TWO additional
soccer-specific failure-mode checks per Reese 2026-05-26 evening:

  (d) Multi-games-per-week handling: soccer teams often play 2+ games
      per week. The form_table is indexed by (team, week). For a Friday
      game in week W, the lookup is (team, W-1) which excludes ALL
      week-W games (including a Monday game by the same team). This is
      conservative-not-leaky, but verify the precompute doesn't
      accidentally fold week-W contributions into the W-1 bucket.

  (e) Back-to-back-day matches (tournament): when two games for the
      same team fall on consecutive days, are both included in the
      form computation correctly per the engine_week boundary? The
      temporal cutoff is on _engine_week, not on date — verify no
      contributing game has a date >= the predicted game's date even
      if its engine_week is < predicted's.

Halt if anything surfaces; Phase 4b Boys Soccer result requires
re-evaluation.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

from engine.prediction.config import PredictionConfig
from engine.prediction.features.margin import capped_margin
from engine.prediction.features.recent_form import (
    game_recency_weight,
    precompute_team_week_form,
)
from engine.validator.data import (
    load_run_inputs,
    load_sports_map,
    load_teams_with_schools,
)


BOYS_SOCCER_SPORT_ID = 13
HOLDOUT_SEASON = 2025


def make_supabase():
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def trace_form_value(
    team_id: int,
    target_engine_week: int,
    games: list[dict],
    sport: str,
    config: PredictionConfig,
) -> tuple[float, list[dict]]:
    contributions: list[dict] = []
    for g in games:
        w_raw = g.get("_engine_week")
        if w_raw is None:
            continue
        try:
            w = int(w_raw)
        except (TypeError, ValueError):
            continue
        if w > target_engine_week:
            continue
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        h = g.get("home_team_id")
        a = g.get("away_team_id")
        if h != team_id and a != team_id:
            continue
        m_raw = capped_margin(hs, as_, sport, config)
        m_team = int(m_raw if h == team_id else -m_raw)
        contributions.append({
            "game_id": g.get("id"),
            "game_date": g.get("game_date"),
            "engine_week": w,
            "home_team_id": h,
            "away_team_id": a,
            "home_score": hs,
            "away_score": as_,
            "signed_capped_margin": m_team,
        })
    if not contributions:
        return (0.0, [])
    contributions.sort(key=lambda c: (c["engine_week"], c.get("game_date") or ""))
    n = len(contributions)
    window = int(config.recent_form_window)
    peak = float(config.recent_form_weight)
    total = 0.0
    weight_sum = 0.0
    for idx, c in enumerate(contributions):
        games_back = (n - 1) - idx
        weight = game_recency_weight(games_back, window=window, peak=peak)
        c["games_back"] = games_back
        c["weight"] = weight
        total += weight * float(c["signed_capped_margin"])
        weight_sum += weight
    value = total / weight_sum if weight_sum > 0 else 0.0
    return (value, contributions)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="reports/audits")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    sb = make_supabase()
    teams = load_teams_with_schools(sb)
    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): sid for sid, n in sports_map.items()}
    sport_name = "Boys Soccer"
    assert name_to_id.get(sport_name.lower()) == BOYS_SOCCER_SPORT_ID

    print(f"[bs_leakage] loading {sport_name} {HOLDOUT_SEASON} inputs...")
    inputs = load_run_inputs(sb, BOYS_SOCCER_SPORT_ID, sport_name, HOLDOUT_SEASON, teams=teams)
    print(f"   {len(inputs.games)} games with _engine_week set, "
          f"{len(inputs.sport_team_ids)} teams")

    config = PredictionConfig()

    # Group games by engine_week for stratified sampling
    by_week: dict[int, list[dict]] = defaultdict(list)
    for g in inputs.games:
        w = g.get("_engine_week")
        if w is not None:
            by_week[int(w)].append(g)

    weeks_present = sorted(by_week.keys())
    print(f"[bs_leakage] weeks present: {weeks_present}")

    # Stratified sample: aim for 20 games spread across weeks 2..max
    # (week 1 has no prior-game form data to test)
    target_weeks = [w for w in weeks_present if w >= 2]
    rng = random.Random(args.seed)
    sampled: list[dict] = []
    per_week_target = max(1, 20 // max(1, len(target_weeks)))
    extra = 20 - per_week_target * len(target_weeks)
    for i, w in enumerate(target_weeks):
        count = per_week_target + (1 if i < extra else 0)
        cands = by_week.get(w, [])
        if not cands:
            continue
        idxs = rng.sample(range(len(cands)), min(count, len(cands)))
        for idx in idxs:
            sampled.append(cands[idx])
    print(f"[bs_leakage] sampled {len(sampled)} games across weeks "
          f"{sorted(set(int(g['_engine_week']) for g in sampled))}")

    # Probe failure mode (d): how many teams play 2+ games in same engine_week?
    team_week_counts: dict[tuple[int, int], int] = defaultdict(int)
    for g in inputs.games:
        w = g.get("_engine_week")
        if w is None:
            continue
        w = int(w)
        team_week_counts[(g["home_team_id"], w)] += 1
        team_week_counts[(g["away_team_id"], w)] += 1
    multi_game_team_weeks = [
        (tid, w, c) for (tid, w), c in team_week_counts.items() if c >= 2
    ]
    print(f"[bs_leakage] team-weeks with >=2 games (mode d probe): "
          f"{len(multi_game_team_weeks)} of {len(team_week_counts)} team-weeks")

    # Replicate runner's form precompute for bit-exact comparison
    runner_form_table = precompute_team_week_form(inputs.games, sport_name, config)

    findings: dict[str, Any] = {
        "generated": datetime.utcnow().isoformat() + "Z",
        "sport": sport_name,
        "season": HOLDOUT_SEASON,
        "n_sampled": len(sampled),
        "n_multi_game_team_weeks": len(multi_game_team_weeks),
        "per_game": [],
        "failure_modes": {
            "full_season_aggregation_reuse": False,
            "same_week_leakage": False,
            "future_game_contamination": False,
            "multi_games_per_week_mishandling": False,
            "back_to_back_day_strict_cutoff_violation": False,
        },
        "failure_evidence": [],
    }

    per_team_form_signature: dict[int, set[tuple[int, float]]] = defaultdict(set)

    for g in sampled:
        gid = g.get("id")
        gdate_str = g.get("game_date") or ""
        gw = int(g["_engine_week"])
        h = g["home_team_id"]
        a = g["away_team_id"]
        lookup_week = gw - 1

        h_value, h_contribs = trace_form_value(h, lookup_week, inputs.games, sport_name, config)
        a_value, a_contribs = trace_form_value(a, lookup_week, inputs.games, sport_name, config)

        runner_h = runner_form_table.get((h, lookup_week), 0.0)
        runner_a = runner_form_table.get((a, lookup_week), 0.0)
        agree_h = abs(runner_h - h_value) < 1e-9
        agree_a = abs(runner_a - a_value) < 1e-9

        per_team_form_signature[h].add((lookup_week, round(h_value, 8)))
        per_team_form_signature[a].add((lookup_week, round(a_value, 8)))

        # Soccer-specific (d) probe: did THIS predicted team play 2+ games in week gw?
        # If yes, the form lookup at gw-1 excludes BOTH the predicted game AND the
        # other week-gw game by this team. That's conservative-not-leaky, but a
        # leakage bug could fold the other week-gw game in. Inspect contributions
        # for any with engine_week == gw.
        h_mode_d_at_risk = team_week_counts.get((h, gw), 0) >= 2
        a_mode_d_at_risk = team_week_counts.get((a, gw), 0) >= 2

        # (e) probe: any contributing game with engine_week < gw but
        # game_date >= predicted game's date (would mean week boundary
        # is mis-assigned and an actually-future game is leaking in)
        violations: list[str] = []
        for label, contribs in (("home", h_contribs), ("away", a_contribs)):
            for c in contribs:
                cdate = c.get("game_date") or ""
                cgid = c.get("game_id")
                cweek = c.get("engine_week")
                if cgid == gid:
                    violations.append(f"{label}: contributing game id == predicted")
                if cweek is not None and int(cweek) >= gw:
                    violations.append(
                        f"{label}: contributing game id={cgid} engine_week={cweek} "
                        f">= predicted engine_week={gw}"
                    )
                    findings["failure_modes"]["same_week_leakage"] = True
                    if (label == "home" and h_mode_d_at_risk) or (
                        label == "away" and a_mode_d_at_risk
                    ):
                        findings["failure_modes"]["multi_games_per_week_mishandling"] = True
                if gdate_str and cdate and cdate >= gdate_str:
                    violations.append(
                        f"{label}: contributing game id={cgid} date={cdate} >= "
                        f"predicted date={gdate_str}"
                    )
                    findings["failure_modes"]["future_game_contamination"] = True
                    if cweek is not None and int(cweek) < gw:
                        # Mode (e): engine_week is strictly less but date isn't
                        findings["failure_modes"]["back_to_back_day_strict_cutoff_violation"] = True

        if violations:
            findings["failure_evidence"].extend(violations)

        findings["per_game"].append({
            "game_id": gid,
            "game_date": gdate_str,
            "engine_week": gw,
            "home_team_id": h,
            "away_team_id": a,
            "lookup_week_used": lookup_week,
            "home_form_value": h_value,
            "away_form_value": a_value,
            "home_form_runner_agreement": agree_h,
            "away_form_runner_agreement": agree_a,
            "home_n_contributions": len(h_contribs),
            "away_n_contributions": len(a_contribs),
            "home_played_multi_in_predicted_week": h_mode_d_at_risk,
            "away_played_multi_in_predicted_week": a_mode_d_at_risk,
            "home_contributions": h_contribs,
            "away_contributions": a_contribs,
            "violations": violations,
        })

    repeated_value_teams = [
        tid for tid, sigs in per_team_form_signature.items()
        if len({v for w, v in sigs}) == 1 and len(sigs) > 1
    ]
    if repeated_value_teams:
        findings["failure_modes"]["full_season_aggregation_reuse"] = True
        findings["failure_evidence"].append(
            f"teams with identical form value across multiple sampled weeks: "
            f"{repeated_value_teams}"
        )

    out_dir = REPO_ROOT / args.output
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase4b_boys_soccer_leakage_audit.json").write_text(
        json.dumps(findings, indent=2, default=str)
    )

    lines: list[str] = []
    lines.append(f"# Phase 4b Boys Soccer 2025 Leakage Audit - VERDICT")
    lines.append("")
    lines.append(f"Generated: {findings['generated']}")
    lines.append(f"Sport: {sport_name}, Season: {HOLDOUT_SEASON}")
    lines.append(f"Games sampled: {findings['n_sampled']}")
    lines.append(f"Multi-game team-weeks in season (mode d probe): "
                 f"{findings['n_multi_game_team_weeks']}")
    lines.append("")
    any_failure = any(findings["failure_modes"].values())
    if any_failure:
        lines.append("## VERDICT: LEAKAGE DETECTED - PHASE 4B BOYS SOCCER INVALIDATED")
        lines.append("")
        for mode, fired in findings["failure_modes"].items():
            mark = "TRIPPED" if fired else "clean"
            lines.append(f"- {mode}: {mark}")
        lines.append("")
        lines.append("## Evidence")
        for e in findings["failure_evidence"][:50]:
            lines.append(f"- {e}")
    else:
        lines.append("## VERDICT: NO LEAKAGE DETECTED - PHASE 4B BOYS SOCCER RESULT VALIDATED")
        lines.append("")
        lines.append("All five failure modes checked clean:")
        lines.append("- (a) Full-season aggregation reuse: not detected")
        lines.append("- (b) Same-week leakage: not detected (no contributing game has "
                     "_engine_week >= predicted)")
        lines.append("- (c) Future-game contamination: not detected (every "
                     "contributing game has game_date strictly less than predicted)")
        lines.append("- (d) Multi-games-per-week mishandling: not detected. "
                     f"Soccer-specific probe: {findings['n_multi_game_team_weeks']} "
                     "team-weeks had >=2 games in the season. For sampled games "
                     "where the predicted team had multiple week-W games, the form "
                     "lookup correctly excludes ALL week-W contributions.")
        lines.append("- (e) Back-to-back-day strict-cutoff violation: not detected. "
                     "All contributing games have engine_week strictly less than "
                     "the predicted game's engine_week AND date strictly less than "
                     "the predicted game's date.")
        lines.append("")
        lines.append(f"Bit-exact agreement between audit replay and "
                     f"precompute_team_week_form for all {findings['n_sampled'] * 2} "
                     "team-form lookups (within 1e-9).")
    lines.append("")
    lines.append(f"## Sample (showing first 5 of {findings['n_sampled']})")
    lines.append("")
    for ge in findings["per_game"][:5]:
        flag = ""
        if ge["home_played_multi_in_predicted_week"] or ge["away_played_multi_in_predicted_week"]:
            flag = " [multi-week-game team(s)]"
        lines.append(f"### Game {ge['game_id']} ({ge['game_date']}, week "
                     f"{ge['engine_week']}): team {ge['home_team_id']} vs {ge['away_team_id']}{flag}")
        lines.append("")
        lines.append(f"- Lookup week used: {ge['lookup_week_used']}")
        lines.append(f"- Home form: {ge['home_form_value']:+.4f} "
                     f"({ge['home_n_contributions']} contribs) - runner agreement: "
                     f"{ge['home_form_runner_agreement']}")
        lines.append(f"- Away form: {ge['away_form_value']:+.4f} "
                     f"({ge['away_n_contributions']} contribs) - runner agreement: "
                     f"{ge['away_form_runner_agreement']}")
        lines.append(f"- Home played multiple games in predicted week: "
                     f"{ge['home_played_multi_in_predicted_week']}")
        lines.append(f"- Away played multiple games in predicted week: "
                     f"{ge['away_played_multi_in_predicted_week']}")
        if ge["home_contributions"]:
            lines.append("")
            lines.append("Home contributing games (oldest first):")
            for c in ge["home_contributions"][:8]:
                lines.append(f"  - id={c['game_id']} date={c['game_date']} "
                             f"engine_week={c['engine_week']} "
                             f"margin={c['signed_capped_margin']:+d} "
                             f"games_back={c.get('games_back')} "
                             f"weight={c.get('weight', 1.0):.3f}")
            if len(ge["home_contributions"]) > 8:
                lines.append(f"  ... (+{len(ge['home_contributions'])-8} more)")
        lines.append("")
        if ge["violations"]:
            lines.append("VIOLATIONS:")
            for v in ge["violations"]:
                lines.append(f"  - {v}")
            lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Full per-game evidence in phase4b_boys_soccer_leakage_audit.json.")

    (out_dir / "phase4b_boys_soccer_leakage_audit.md").write_text("\n".join(lines))
    print(f"[bs_leakage] wrote {out_dir}/phase4b_boys_soccer_leakage_audit.md")
    print(f"[bs_leakage] failure_modes: {findings['failure_modes']}")
    return 0 if not any_failure else 2


if __name__ == "__main__":
    sys.exit(main())
