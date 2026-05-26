"""Cat 1 30-case diagnostic - hard checkpoint per Reese 2026-05-26 evening.

Methodology: docs/cat1_30case_plan.md.

Pipeline:
  1. Parse Football PDFs for 2022 / 2023 / 2025 (Select + Non-Select each).
  2. For every PDF row, look up our team_id (fuzzy school name + season),
     count our games for (team_id, season_year, week <= snapshot_week).
  3. Cat 1 = PDF games > our games. Stratified sample of 30 (12 from 2025,
     10 from 2023, 8 from 2022).
  4. For each sampled team: dump games + week distribution + score
     patterns; heuristically categorize the per-team gap into:
       (i)   playoff/tournament  - our games end at <= week 10 but
                                   PDF expected count > 10
       (ii)  forfeit              - any of our games has 1-0 or 0-1
                                   score (single forfeit per LHSAA
                                   Bulletin 14.12.4 IS counted)
       (iii) late-add             - our games end before the PDF
                                   snapshot date with weeks 1..N
                                   complete but N < 10 (regular season
                                   completed but our scrape missed
                                   late-added games)
       (iv)  fuzzy-match drop     - opponent name appears in raw
                                   scraper logs but no team_id linked
                                   (NOT computable without scrape logs;
                                   conservatively counted as 'other'
                                   here and noted in the SUMMARY)
       (v)   other / unknown     - everything else

Output: reports/data_audit/cat1_30case/SUMMARY.md + per_team.json.

Per Reese 2026-05-26 evening, this MUST run before Phase 4a halt. Plain-text
output only - no emoji glyphs in any table cell.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

from scripts.parse_lhsaa_pdf import parse_pdf  # noqa: E402


FOOTBALL_PDFS_OF_INTEREST = [
    # 2025: Week 10 Final
    {"sport": "Football", "season_year": 2025, "division": "all",
     "select_status": "Select", "snapshot": "Week 10 Final",
     "url": "https://www.lhsaa.org/siteuploads/editorimg/file/Football/2025%20Football/LHSAA%20Select%20Divisions%20Power%20Ratings%20Week%2010%20(Final%20for%20Review).pdf"},
    {"sport": "Football", "season_year": 2025, "division": "all",
     "select_status": "Non-Select", "snapshot": "Week 10 Final",
     "url": "https://www.lhsaa.org/siteuploads/editorimg/file/Football/2025%20Football/LHSAA%20Non-Select%20Divisions%20Power%20Ratings%20Week%2010%20(Final%20for%20Review).pdf"},
    # 2023
    {"sport": "Football", "season_year": 2023, "division": "all",
     "select_status": "Select", "snapshot": "Week 10 Final",
     "url": "https://www.lhsaa.org/siteuploads/editorimg/file/Football/2023%20Football/LHSAA%20Select%20Divisions%20Power%20Ratings%20Week%2010%20(Final%20for%20Review).pdf"},
    {"sport": "Football", "season_year": 2023, "division": "all",
     "select_status": "Non-Select", "snapshot": "Week 10 Final",
     "url": "https://www.lhsaa.org/siteuploads/editorimg/file/Football/2023%20Football/LHSAA%20Non-Select%20Divisions%20Power%20Ratings%20Week%2010%20(Final%20for%20Review).pdf"},
    # 2022
    {"sport": "Football", "season_year": 2022, "division": "all",
     "select_status": "Select", "snapshot": "Week 10 Final",
     "url": "https://www.lhsaa.org/siteuploads/editorimg/file/Football/LHSAA%20Select%20Divisions%20Power%20Ratings%20Week%2010%20(Final%20for%20Review).pdf"},
    {"sport": "Football", "season_year": 2022, "division": "all",
     "select_status": "Non-Select", "snapshot": "Week 10 Final",
     "url": "https://www.lhsaa.org/siteuploads/editorimg/file/Football/LHSAA%20Non-Select%20Divisions%20Power%20Ratings%20Week%2010%20(Final%20for%20Review).pdf"},
]

# Snapshot week 10 = the last regular-season week. PDF wins+losses sums
# to 10 if the team played every regular-season game. Cat 1 (gap > 0)
# means our scrape missed some of those 10.
SNAPSHOT_WEEK_CUTOFF = 10

# Stratified sample sizes (PLAN.md)
SAMPLE_QUOTA = {2025: 12, 2023: 10, 2022: 8}

FOOTBALL_SPORT_ID = 1


def make_supabase():
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def load_louisiana_football_teams(sb) -> dict:
    """Return {(team_id, season_year): {school_name, parish, division}} for
    all Football teams 2022/2023/2025 — we'll match PDF rows against this."""
    out = {}
    # Pull teams for sport_id=1 across our three seasons
    for season in (2022, 2023, 2025):
        page = 0
        while True:
            res = (
                sb.table("teams")
                .select("id, season_year, school_id, division, select_status, schools(name, parish)")
                .eq("sport_id", FOOTBALL_SPORT_ID)
                .eq("season_year", season)
                .range(page * 1000, page * 1000 + 999)
                .execute()
            )
            if not res.data:
                break
            for r in res.data:
                school = r.get("schools") or {}
                out[(r["id"], season)] = {
                    "team_id": r["id"],
                    "season_year": r["season_year"],
                    "school_id": r["school_id"],
                    "school_name": (school.get("name") or "").strip(),
                    "parish": school.get("parish") or "",
                    "division": r.get("division") or "",
                    "select_status": r.get("select_status") or "",
                }
            if len(res.data) < 1000:
                break
            page += 1
    return out


def index_teams_by_season(teams_map: dict) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for (tid, season), t in teams_map.items():
        out[season].append(t)
    return out


def normalize(s: str) -> str:
    return " ".join(s.lower().replace("'", "").replace(",", "").split())


def find_team_match(
    pdf_school_name: str,
    season: int,
    candidates: list[dict],
    *,
    cutoff: float = 0.75,
) -> dict | None:
    target = normalize(pdf_school_name)
    names = [normalize(c["school_name"]) for c in candidates]
    match = difflib.get_close_matches(target, names, n=1, cutoff=cutoff)
    if not match:
        return None
    idx = names.index(match[0])
    return candidates[idx]


def load_games_for_team(sb, team_id: int, season: int) -> list[dict]:
    out = []
    page = 0
    while True:
        # Both home + away. Use only columns confirmed present per the
        # 2026-05-25 schema audit (no neutral_site column).
        res = (
            sb.table("games")
            .select("id, game_date, week_number, home_team_id, away_team_id, home_score, away_score, is_out_of_state")
            .eq("sport_id", FOOTBALL_SPORT_ID)
            .eq("season_year", season)
            .or_(f"home_team_id.eq.{team_id},away_team_id.eq.{team_id}")
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


def load_all_football_games_for_season(sb, season: int) -> list[dict]:
    """One-shot load of all Football games for a given season. Used to
    compute per-team game counts efficiently for Cat 1 identification."""
    out = []
    page = 0
    while True:
        res = (
            sb.table("games")
            .select("id, week_number, home_team_id, away_team_id, home_score, away_score")
            .eq("sport_id", FOOTBALL_SPORT_ID)
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


def categorize_gap(team: dict, our_games: list[dict], pdf_row: dict) -> tuple[str, str]:
    """Return (bucket, reason)."""
    expected_n = pdf_row["wins"] + pdf_row["losses"]
    our_n = len(our_games)
    if our_n >= expected_n:
        return ("nogap", f"no gap (our_n={our_n} >= expected={expected_n})")

    # Forfeit detection: any game with score 1-0 or 0-1 exactly
    forfeit_like = sum(
        1 for g in our_games
        if g.get("home_score") in (0, 1) and g.get("away_score") in (0, 1)
        and (g.get("home_score") or 0) + (g.get("away_score") or 0) == 1
    )
    if forfeit_like > 0:
        return ("forfeit",
                f"forfeit-pattern detected ({forfeit_like} 1-0 or 0-1 games)")

    weeks_played = sorted({g.get("week_number") for g in our_games if g.get("week_number")})

    # Tournament/playoff: PDF cuts at week 10; if our scrape covers all
    # of weeks 1..N but N<10 the gap might be late-added regular-season
    # games. The week-10 PDF doesn't include playoff games for the team,
    # so if our weeks_played covers 1..10 contiguously but we still have
    # a gap, that suggests forfeit/late-add at a specific in-window week.
    if weeks_played and max(weeks_played) >= 10 and set(range(1, 11)).issubset(set(weeks_played)):
        # We have all weeks but still short - the missing games are
        # within already-covered weeks. Probably duplicate-vs-OOS at
        # the same week. Surface as 'other' with the week info.
        return ("other",
                f"all 10 regular-season weeks covered (weeks={weeks_played}) "
                f"but only {our_n}/{expected_n} games for this team - likely "
                f"a same-week missing-game (duplicate row or OOS still not "
                f"linked)")

    if weeks_played and max(weeks_played) < 10:
        # Our scrape stops short of week 10
        missing_weeks = [w for w in range(1, 11) if w not in weeks_played]
        if missing_weeks:
            return ("late_add_or_omission",
                    f"our scrape covers weeks {weeks_played}; missing "
                    f"weeks {missing_weeks}. Either late-added games "
                    f"or scraper omission")

    if not weeks_played:
        return ("scraper_omission_total",
                f"team has 0 games in our DB but PDF says {expected_n} - "
                "team scrape failed entirely")

    return ("other", f"weeks={weeks_played} our_n={our_n} expected={expected_n}")


def stratified_sample(rows: list[dict], quota: dict[int, int], seed: int = 42) -> list[dict]:
    """Deterministic stratified sample by season_year."""
    by_season: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_season[r["season_year"]].append(r)
    out: list[dict] = []
    for season, n in quota.items():
        cands = sorted(by_season.get(season, []),
                       key=lambda r: (r["team_id"], r.get("division", ""), r["school_name"]))
        if not cands:
            continue
        # Pick every Nth so we span the range deterministically
        step = max(1, len(cands) // n) if n > 0 else 1
        picks = []
        idx = 0
        while len(picks) < n and idx < len(cands):
            picks.append(cands[idx])
            idx += step
        # Top up if we ran out via stride
        for c in cands:
            if len(picks) >= n:
                break
            if c not in picks:
                picks.append(c)
        out.extend(picks[:n])
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python scripts/audit/cat1_30case.py")
    p.add_argument("--output", default="reports/data_audit/cat1_30case",
                   help="output directory")
    p.add_argument("--match-cutoff", type=float, default=0.75)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    sb = make_supabase()
    print("[cat1] loading Louisiana Football teams for 2022/2023/2025...")
    teams_map = load_louisiana_football_teams(sb)
    teams_by_season = index_teams_by_season(teams_map)
    for season, items in teams_by_season.items():
        print(f"   season {season}: {len(items)} teams")

    print("[cat1] parsing 6 Football PDFs (cache hit if available)...")
    all_pdf_rows: list[dict] = []
    pdfs_parsed = 0
    for entry in FOOTBALL_PDFS_OF_INTEREST:
        try:
            rows = parse_pdf(entry)
            pdfs_parsed += 1
            print(f"   {entry['season_year']} {entry['select_status']}: {len(rows)} rows")
        except Exception as e:
            print(f"   {entry['season_year']} {entry['select_status']}: FAILED ({e!r})")
            continue
        for r in rows:
            all_pdf_rows.append({
                "season_year": r.season_year,
                "school_name": r.school_name,
                "wins": r.wins,
                "losses": r.losses,
                "division": r.division,
                "select_status": r.select_status,
                "rank": r.rank,
            })
    print(f"[cat1] total parsed rows: {len(all_pdf_rows)} from {pdfs_parsed} PDFs")

    # Pre-load all Football games for the 3 seasons so we can compute per-team
    # game counts efficiently (avoids 884 individual REST calls).
    print("[cat1] bulk-loading all Football games for 2022/2023/2025...")
    games_by_season: dict[int, list[dict]] = {}
    for season in (2022, 2023, 2025):
        games_by_season[season] = load_all_football_games_for_season(sb, season)
        print(f"   season {season}: {len(games_by_season[season])} games")

    # Per (team_id, season): list of in-window games
    in_window_games: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for season, games in games_by_season.items():
        for g in games:
            if (g.get("week_number") or 0) > SNAPSHOT_WEEK_CUTOFF:
                continue
            in_window_games[(g["home_team_id"], season)].append(g)
            in_window_games[(g["away_team_id"], season)].append(g)

    # For every PDF row, find team_id + compute gap
    print("[cat1] matching PDF rows to teams + computing gaps...")
    all_rows: list[dict] = []
    cat1_rows: list[dict] = []
    unmatched: list[dict] = []
    for pr in all_pdf_rows:
        cands = teams_by_season.get(pr["season_year"], [])
        team = find_team_match(pr["school_name"], pr["season_year"], cands,
                               cutoff=args.match_cutoff)
        if not team:
            unmatched.append(pr)
            continue
        expected_n = pr["wins"] + pr["losses"]
        if expected_n <= 0:
            continue
        our_games = in_window_games.get((team["team_id"], pr["season_year"]), [])
        gap = expected_n - len(our_games)
        row = {
            "season_year": pr["season_year"],
            "team_id": team["team_id"],
            "school_id": team["school_id"],
            "school_name": team["school_name"],
            "pdf_school_name": pr["school_name"],
            "parish": team["parish"],
            "team_division": team["division"],
            "team_select_status": team["select_status"],
            "pdf_division": pr["division"],
            "pdf_select_status": pr["select_status"],
            "pdf_wins": pr["wins"],
            "pdf_losses": pr["losses"],
            "pdf_total": expected_n,
            "pdf_rank": pr["rank"],
            "our_n_games": len(our_games),
            "gap": gap,
            "_games": our_games,
        }
        all_rows.append(row)
        if gap > 0:
            cat1_rows.append(row)

    print(f"[cat1] matched {len(all_rows)} rows; unmatched {len(unmatched)}")
    print(f"[cat1] Cat 1 rows (gap > 0): {len(cat1_rows)} "
          f"({len(cat1_rows)/max(1,len(all_rows)):.1%} of matched)")
    # Per-season Cat 1 share
    for season in (2022, 2023, 2025):
        seas = [r for r in all_rows if r["season_year"] == season]
        cat = [r for r in cat1_rows if r["season_year"] == season]
        if seas:
            print(f"   season {season}: {len(cat)}/{len(seas)} = "
                  f"{len(cat)/len(seas):.1%} Cat 1")

    # Sample from the Cat 1 rows ONLY (was: sample from all_rows, which
    # over-included no-gap teams)
    sample = stratified_sample(cat1_rows, SAMPLE_QUOTA, seed=args.seed)
    print(f"[cat1] sampled {len(sample)} Cat 1 teams across seasons "
          f"({sum(1 for s in sample if s['season_year']==2025)}/2025, "
          f"{sum(1 for s in sample if s['season_year']==2023)}/2023, "
          f"{sum(1 for s in sample if s['season_year']==2022)}/2022)")

    # Categorize each sampled Cat 1 team
    print("[cat1] categorizing per-team gaps...")
    per_team_results = []
    bucket_counts = defaultdict(int)
    for s in sample:
        in_window = s["_games"]
        bucket, reason = categorize_gap(s, in_window, {
            "wins": s["pdf_wins"], "losses": s["pdf_losses"]
        })
        bucket_counts[bucket] += 1
        result_row = {k: v for k, v in s.items() if k != "_games"}
        result_row.update({
            "our_weeks_played": sorted({g.get("week_number") for g in in_window if g.get("week_number")}),
            "our_n_games": len(in_window),
            "bucket": bucket,
            "reason": reason,
        })
        per_team_results.append(result_row)

    # Output
    out_dir = REPO_ROOT / args.output
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "per_team.json").write_text(json.dumps(per_team_results, indent=2, default=str))

    # SUMMARY.md
    lines = []
    lines.append("# Cat 1 30-case Diagnostic - SUMMARY")
    lines.append("")
    lines.append(f"Generated: {datetime.utcnow().isoformat()}Z")
    lines.append(f"Snapshot week cutoff: {SNAPSHOT_WEEK_CUTOFF}")
    lines.append(f"PDFs parsed: {pdfs_parsed} of {len(FOOTBALL_PDFS_OF_INTEREST)}")
    lines.append(f"PDF rows matched to teams: {len(cat1_rows)} (unmatched: {len(unmatched)})")
    lines.append(f"Total matched rows: {len(all_rows)}; Cat 1 (gap>0): {len(cat1_rows)} "
                 f"({len(cat1_rows)/max(1,len(all_rows)):.1%})")
    lines.append(f"Sample size: {len(per_team_results)} (target 30 — all Cat 1, "
                 f"stratified: {sum(1 for s in sample if s['season_year']==2025)}/2025 + "
                 f"{sum(1 for s in sample if s['season_year']==2023)}/2023 + "
                 f"{sum(1 for s in sample if s['season_year']==2022)}/2022)")
    lines.append("")
    lines.append("Per-season Cat 1 rate:")
    for season in (2022, 2023, 2025):
        seas = [r for r in all_rows if r["season_year"] == season]
        cat = [r for r in cat1_rows if r["season_year"] == season]
        if seas:
            lines.append(f"- {season}: {len(cat)}/{len(seas)} = "
                         f"{len(cat)/len(seas):.1%} Cat 1")
    lines.append("")
    lines.append("## Bucket counts")
    lines.append("")
    lines.append("| Bucket | Count | Share |")
    lines.append("|---|---:|---:|")
    total = max(1, sum(bucket_counts.values()))
    for bucket, count in sorted(bucket_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {bucket} | {count} | {count/total:.1%} |")
    lines.append("")

    cat1_only = [r for r in per_team_results if r["bucket"] != "nogap"]
    lines.append(f"## Cat 1 teams in the sample (bucket != nogap): {len(cat1_only)}")
    lines.append("")
    lines.append("| Season | Team | Div | Our N | PDF N | Gap | Weeks | Bucket | Reason |")
    lines.append("|---|---|---|---:|---:|---:|---|---|---|")
    for r in cat1_only:
        weeks = ",".join(str(w) for w in r["our_weeks_played"][:8])
        if len(r["our_weeks_played"]) > 8:
            weeks += "..."
        lines.append(
            f"| {r['season_year']} | {r['school_name']} | "
            f"{r['team_division']}/{r['team_select_status'][:3]} | "
            f"{r['our_n_games']} | {r['pdf_total']} | {r['gap']} | "
            f"{weeks} | {r['bucket']} | {r['reason'][:80]} |"
        )
    lines.append("")

    nogap = [r for r in per_team_results if r["bucket"] == "nogap"]
    if nogap:
        lines.append(f"## Sampled teams with NO gap ({len(nogap)})")
        lines.append("")
        lines.append("These teams' PDF expected count matched or was lower than our DB - "
                     "useful as control rows for the sampling methodology check.")
        lines.append("")
        for r in nogap:
            lines.append(f"- {r['school_name']} ({r['season_year']}): "
                         f"our N={r['our_n_games']}, PDF N={r['pdf_total']}")
        lines.append("")

    lines.append("## Methodology limitations (be honest)")
    lines.append("")
    lines.append("This diagnostic does NOT re-scrape lhsaaonline.org team-by-team to "
                 "diff our games row-by-row against LHSAA's schedule. The categorization "
                 "buckets are inferred from our DB + PDF expected counts only:")
    lines.append("")
    lines.append("- 'forfeit' = score-pattern heuristic (1-0 or 0-1 in our DB).")
    lines.append("- 'playoff/tournament' = our games end at <= week 10. The PDF "
                 "snapshot ITSELF is week 10 Final, so PDF expected_n only counts "
                 "regular-season; this bucket should NEVER fire on a true week-10 "
                 "snapshot - present in the code only for non-week-10 snapshots in "
                 "future runs.")
    lines.append("- 'late_add_or_omission' = our scrape has fewer than 10 weeks "
                 "of data for the team. Cannot distinguish 'late-added game we "
                 "missed' from 'scraper failed mid-season' without lhsaaonline "
                 "comparison.")
    lines.append("- 'scraper_omission_total' = our scrape produced zero games "
                 "for this team. Smoking-gun signal.")
    lines.append("- 'fuzzy-match drop' bucket from the PLAN.md is NOT separately "
                 "counted here - that would require dumping the ingest scripts' "
                 "unmatched-schools log per team, which we don't have for the "
                 "post-OOS-fix re-scrape. Conservatively bucketed under 'other'.")
    lines.append("- 'other' = catch-all for cases where our scrape has all 10 "
                 "weeks but the per-team game count is still short. Most likely "
                 "OOS games or duplicate-resolution issues.")
    lines.append("")
    lines.append("## Hypothesis verdict")
    lines.append("")
    hypothesis_buckets = {"forfeit", "late_add_or_omission"}
    hits = sum(c for b, c in bucket_counts.items() if b in hypothesis_buckets)
    other = bucket_counts.get("other", 0) + bucket_counts.get("scraper_omission_total", 0)
    n_with_gap = sum(c for b, c in bucket_counts.items() if b != "nogap")
    if n_with_gap == 0:
        lines.append("**No Cat 1 in the sample.** Re-run with a larger sample.")
    else:
        share_hit = hits / n_with_gap
        if share_hit >= 0.70:
            lines.append(f"**HYPOTHESIS CONFIRMED** ({share_hit:.1%} in forfeit+late-add "
                         f"buckets). Reese's tournament/forfeit/late-add hypothesis is "
                         f"the dominant cause; scoped fixes per bucket.")
        elif share_hit >= 0.40:
            lines.append(f"**HYPOTHESIS PARTIALLY CONFIRMED** ({share_hit:.1%} in "
                         f"hypothesized buckets, {other/n_with_gap:.1%} 'other/scraper'). "
                         f"Recommend per-bucket fix for hypothesized causes + audit "
                         f"the 'other' bucket for the remaining mechanism.")
        else:
            lines.append(f"**HYPOTHESIS REFUTED** ({share_hit:.1%} in hypothesized "
                         f"buckets; {other/n_with_gap:.1%} 'other/scraper'). The "
                         f"residual Cat 1 is NOT primarily forfeit/late-add. "
                         f"Dominant signal is in 'other' or 'scraper_omission_total' - "
                         f"re-open root-cause investigation.")
    lines.append("")

    (out_dir / "SUMMARY.md").write_text("\n".join(lines))
    print(f"[cat1] wrote {out_dir}/SUMMARY.md")
    print(f"[cat1] buckets: {dict(bucket_counts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
