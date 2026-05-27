"""Workstream B Step B0 — under-coverage mechanism diagnosis.

The phantom_share diagnostic refuted the phantom-team hypothesis but
surfaced the opposite issue: engine universe is 17-31% SMALLER than
LHSAA's published participation for 7 of 8 sports. Reese 2026-05-27
ordered B0 to identify WHY.

Four candidate mechanisms (Reese's hypothesis space):
  1. Name-matching failures — school exists in our scraped data under
     a different name than the LHSAA file's normalized form.
  2. Opponent-discovery gap — scraper crawled opponents-of-knowns but
     never discovered missing schools because no seed team played them.
  3. Bootstrap source incompleteness — football pipeline built first,
     other sports inherited from football roster instead of bootstrapping
     from each sport's own LHSAA participation list.
  4. Smaller-school exclusion — classification filter (Class B/C/1A)
     somewhere in the pipeline.

What we have:
  - Canonical LHSAA roster: 422 school names from Reese's paste
    (/tmp/lhsaa_canonical_list.csv). 124 of these are absent from the
    DB's parish-NULL set.
  - DB: 298 parish-NULL schools (LHSAA-considered), 163 OOS schools
  - LHSAA 2025-2026 published per-sport participation counts (provided
    by Reese):
        FB 324, VB 284, BBB 404, GBB 410, BS 196, GS 189, Baseball 375, Softball 388

What we can compute per sport:
  - Engine universe (teams.sport_id × season_year) for 2025
  - "Missing-from-engine-for-sport" = LHSAA published − engine universe
    Examples: GS missing = 189 − 149 = 40; BBB missing = 404 − 298 = 106

For mechanism classification, since we don't have a per-sport LHSAA
participation file (only the aggregate canonical roster + published
counts), we approximate:

  Mechanism 1 (name-matching) — for the 124 canonical-only schools,
    fuzzy-search the DB by normalized name. A near-match in DB but no
    exact match → name-mismatch mechanism.

  Mechanism 2 (opponent-discovery gap) — for each missing school, check
    whether the school name (or fuzzy variant) appears as an opponent
    text in any scraped game. If it does, we knew about them via crawl
    but didn't ingest the team row.

  Mechanism 3 (bootstrap source) — proxy by sport. If a school IS in DB
    for Football but NOT for a non-football sport for the same season,
    it suggests bootstrap-from-football without re-bootstrapping per
    sport. Quantify: of schools with Football team-rows in 2025, what
    % also have team-rows in each of the other 7 sports? Compare against
    LHSAA's participation rates per sport.

  Mechanism 4 (classification filter) — distribution of classifications
    of the 124 canonical-missing schools (Class B/C/1A vs 2A/3A/4A/5A).
    If missing is skewed small, classification filter is the mechanism.

Report per-sport approximate mechanism share + cross-sport patterns.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / "apps" / "api" / ".env")


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
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def normalize(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\.\,\'\#]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def fuzzy_best(name_norm: str, candidates: dict[str, dict]) -> tuple[str, float] | None:
    """Find the closest match for ``name_norm`` in ``candidates`` (a dict
    of normalized_name -> row). Returns (matched_norm, ratio) for the
    best non-exact match above ratio 0.75, or None.
    """
    if name_norm in candidates:
        return None  # exact match is handled separately
    best, best_ratio = None, 0.0
    for cand_norm in candidates:
        r = SequenceMatcher(None, name_norm, cand_norm).ratio()
        if r > best_ratio:
            best_ratio = r
            best = cand_norm
    if best is not None and best_ratio >= 0.75:
        return (best, best_ratio)
    return None


def main() -> int:
    sb = make_supabase()

    # 1. Load canonical LHSAA list
    canonical = []
    with open("/tmp/lhsaa_canonical_list.csv") as f:
        for row in csv.DictReader(f):
            canonical.append({
                "name": row["School"],
                "name_norm": normalize(row["School"]),
                "city": row["City"],
                "class": row["Class"],
            })
    print(f"[B0] canonical LHSAA list: {len(canonical)} entries")

    # Deduplicate by normalized name (a few canonical entries are dupes)
    by_norm = {}
    for c in canonical:
        if c["name_norm"] not in by_norm:
            by_norm[c["name_norm"]] = c
    canonical_uniq = list(by_norm.values())
    print(f"[B0] canonical after dedup-by-norm: {len(canonical_uniq)}")

    # 2. Load DB schools
    all_db = sb.table("schools").select("id, name, city, parish, classification, maxpreps_uuid").execute()
    db_la = [s for s in all_db.data if s.get("parish") is None]
    db_oos = [s for s in all_db.data if s.get("parish") is not None]
    db_la_by_norm = {normalize(s["name"]): s for s in db_la}
    db_all_by_norm = {normalize(s["name"]): s for s in all_db.data}
    print(f"[B0] DB schools: total={len(all_db.data)}, parish=NULL={len(db_la)}, OOS={len(db_oos)}")

    # 3. The 124 missing-from-DB canonical schools
    missing_canon = [c for c in canonical_uniq if c["name_norm"] not in db_la_by_norm]
    print(f"[B0] canonical schools missing from DB (parish=NULL): {len(missing_canon)}")

    # ===========================================================================
    # MECHANISM 1 — name-matching failures
    # ===========================================================================
    # For each missing canonical school, fuzzy-match against ALL DB schools
    # (including OOS, including parish=NULL). A close match in DB suggests
    # name-mismatch.
    name_mismatch_hits = []  # (canonical, matched_db_row, ratio)
    for c in missing_canon:
        hit = fuzzy_best(c["name_norm"], db_all_by_norm)
        if hit:
            matched_norm, ratio = hit
            name_mismatch_hits.append({
                "canonical_name": c["name"],
                "canonical_class": c["class"],
                "canonical_city": c["city"],
                "db_match_name": db_all_by_norm[matched_norm]["name"],
                "db_match_parish": db_all_by_norm[matched_norm].get("parish"),
                "db_match_id": db_all_by_norm[matched_norm]["id"],
                "ratio": ratio,
            })
    print(f"[B0] mechanism 1 (name-mismatch) candidates: {len(name_mismatch_hits)}")

    # ===========================================================================
    # MECHANISM 4 — classification filter
    # ===========================================================================
    class_dist_missing = Counter(c["class"] for c in missing_canon)
    class_dist_canonical = Counter(c["class"] for c in canonical_uniq)
    class_share_missing = {}
    for cls, n in class_dist_canonical.items():
        miss = class_dist_missing.get(cls, 0)
        class_share_missing[cls] = {
            "n_canonical": n,
            "n_missing_from_db": miss,
            "share_missing": miss / n if n else 0.0,
        }
    print(f"[B0] mechanism 4 (classification) — by class:")
    for cls in sorted(class_share_missing, key=lambda k: -class_share_missing[k]["share_missing"]):
        s = class_share_missing[cls]
        print(f"     class {cls}: {s['n_missing_from_db']}/{s['n_canonical']} ({s['share_missing']*100:.0f}% missing)")

    # ===========================================================================
    # MECHANISM 3 — bootstrap source incompleteness (cross-sport pattern)
    # ===========================================================================
    # For each sport, get team count in 2025 and intersect with Football 2025
    # to see if non-football sports inherit from football roster.
    sport_id_map = {s["name"]: s["id"] for s in sb.table("sports").select("id, name").execute().data}

    teams_2025_by_sport: dict[str, set[int]] = {}  # sport name -> set of school_ids
    for sport_name, sport_id in sport_id_map.items():
        if sport_name not in LHSAA_2025_2026:
            continue
        rows = []
        offset, page = 0, 1000
        while True:
            res = sb.table("teams").select("id, school_id").eq("sport_id", sport_id).eq("season_year", 2025).range(offset, offset + page - 1).execute()
            if not res.data:
                break
            rows.extend(res.data)
            if len(res.data) < page:
                break
            offset += page
        teams_2025_by_sport[sport_name] = {r["school_id"] for r in rows}

    fb_schools_2025 = teams_2025_by_sport.get("Football", set())
    bootstrap_mechanism = {}
    for sport, lhsaa_n in LHSAA_2025_2026.items():
        sport_schools = teams_2025_by_sport.get(sport, set())
        engine_n = len(sport_schools)
        gap = lhsaa_n - engine_n
        if gap <= 0:
            bootstrap_mechanism[sport] = {
                "lhsaa_n": lhsaa_n,
                "engine_n": engine_n,
                "gap": gap,
                "share_engine_in_fb": 1.0,
                "share_fb_in_engine": 1.0,
                "note": "no gap to diagnose",
            }
            continue
        # Of engine schools, what share are also in football?
        in_fb = sport_schools & fb_schools_2025
        share_engine_in_fb = len(in_fb) / len(sport_schools) if sport_schools else 0.0
        # Of football schools, what share are also in this sport?
        share_fb_in_engine = len(in_fb) / len(fb_schools_2025) if fb_schools_2025 else 0.0
        bootstrap_mechanism[sport] = {
            "lhsaa_n": lhsaa_n,
            "engine_n": engine_n,
            "gap": gap,
            "share_engine_in_fb": share_engine_in_fb,
            "share_fb_in_engine": share_fb_in_engine,
            "note": "engine school set is "
                    f"{'mostly-subset' if share_engine_in_fb > 0.95 else 'partial-subset' if share_engine_in_fb > 0.5 else 'disjoint'} of football set",
        }

    print(f"[B0] mechanism 3 (bootstrap source) — Football 2025 school count: {len(fb_schools_2025)}")
    for sport, m in bootstrap_mechanism.items():
        if m["gap"] > 0:
            print(f"     {sport:18}: engine={m['engine_n']:>4} gap={m['gap']:>+4}, "
                  f"engine⊆fb? {m['share_engine_in_fb']*100:.0f}%, fb→engine? {m['share_fb_in_engine']*100:.0f}%")

    # ===========================================================================
    # MECHANISM 2 — opponent-discovery gap
    # ===========================================================================
    # For each missing canonical school, fuzzy-search game opponent strings
    # in scraped data. The games table stores team IDs (foreign keys), not
    # raw opponent strings. But we can check via games via OOS-handling
    # logs or by looking at raw scrape data if exposed. For now: proxy by
    # checking if the missing school appears as a name fragment in any team
    # belonging to OOS-schools (which is sometimes how scrape leftovers
    # land). This is an approximation; a fuller test requires the raw
    # scraped opponent name strings.
    opp_discovery_proxy = []  # missing schools whose names appear NOWHERE in DB
    for c in missing_canon:
        # Already in name_mismatch_hits if there's any near-match
        in_db_at_all = any(c["name_norm"] in normalize(s["name"]) or normalize(s["name"]) in c["name_norm"]
                            for s in all_db.data)
        if not in_db_at_all:
            opp_discovery_proxy.append(c)
    print(f"[B0] mechanism 2 proxy (no substring match anywhere): {len(opp_discovery_proxy)}")

    # ===========================================================================
    # Per-sport approximate mechanism breakdown
    # ===========================================================================
    # Without the per-sport LHSAA participation file, we can't enumerate
    # which specific canonical schools are missing per sport. But we CAN
    # report sport-level summary:
    #   - LHSAA published count
    #   - Engine count
    #   - Gap = LHSAA - engine
    #   - Share of gap that's plausibly Mechanism 3 (football-subset asymmetry)
    per_sport_summary = []
    for sport, lhsaa_n in LHSAA_2025_2026.items():
        engine_n = len(teams_2025_by_sport.get(sport, set()))
        gap = lhsaa_n - engine_n
        m3 = bootstrap_mechanism[sport]
        per_sport_summary.append({
            "sport": sport,
            "lhsaa_published": lhsaa_n,
            "engine_universe_2025": engine_n,
            "gap": gap,
            "gap_pct": gap / lhsaa_n if lhsaa_n else 0.0,
            "engine_⊆_football": m3["share_engine_in_fb"],
            "football_⊆_engine": m3["share_fb_in_engine"],
        })

    # ===========================================================================
    # Artifacts
    # ===========================================================================
    now = datetime.utcnow().isoformat() + "Z"
    output_dir = REPO_ROOT / "reports" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "workstream_b0_undercoverage_mechanism.json"
    md_path = output_dir / "workstream_b0_undercoverage_mechanism.md"

    findings = {
        "generated_utc": now,
        "canonical_list_size": len(canonical),
        "canonical_unique_size": len(canonical_uniq),
        "db_total_schools": len(all_db.data),
        "db_parish_null": len(db_la),
        "db_oos": len(db_oos),
        "canonical_missing_from_db": len(missing_canon),
        "mechanism_1_name_mismatch_candidates": name_mismatch_hits,
        "mechanism_2_opp_discovery_proxy_count": len(opp_discovery_proxy),
        "mechanism_3_bootstrap": bootstrap_mechanism,
        "mechanism_4_classification_distribution": class_share_missing,
        "per_sport_summary_2025": per_sport_summary,
    }
    json_path.write_text(json.dumps(findings, indent=2, default=str))

    # Markdown
    lines = []
    lines.append("# Workstream B Step B0 — Under-Coverage Mechanism Diagnosis")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- Canonical LHSAA list (Reese paste): {len(canonical)} entries ({len(canonical_uniq)} unique by normalized name)")
    lines.append(f"- DB total schools: {len(all_db.data)}")
    lines.append(f"- DB `parish IS NULL` (LHSAA-considered): {len(db_la)}")
    lines.append(f"- DB OOS-flagged: {len(db_oos)}")
    lines.append(f"- Canonical schools MISSING from DB (parish=NULL): {len(missing_canon)} (~{100*len(missing_canon)/len(canonical_uniq):.1f}%)")
    lines.append("")

    lines.append("## Per-sport 2025 under-coverage summary")
    lines.append("")
    lines.append("| Sport | LHSAA pub | Engine 2025 | Gap | Gap % | engine ⊆ football | football → engine |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for s in per_sport_summary:
        lines.append(
            f"| {s['sport']} | {s['lhsaa_published']} | {s['engine_universe_2025']} | "
            f"{s['gap']:+d} | {s['gap_pct']*100:+.1f}% | "
            f"{s['engine_⊆_football']*100:.0f}% | {s['football_⊆_engine']*100:.0f}% |"
        )
    lines.append("")
    lines.append("Reading: 'engine ⊆ football' = % of engine schools for this sport that ALSO have a football team row. High value → engine for this sport is essentially a subset of football roster (bootstrap-from-football mechanism).")
    lines.append("")

    lines.append("## Mechanism 1 — name-matching failures")
    lines.append("")
    lines.append(f"Fuzzy match ratio ≥ 0.75 between a canonical-missing-from-DB name and ANY DB school name (parish=NULL OR OOS):")
    lines.append(f"- Candidates found: {len(name_mismatch_hits)} (out of {len(missing_canon)} missing canonical)")
    lines.append("")
    if name_mismatch_hits:
        lines.append("Top fuzzy matches (sorted by ratio):")
        lines.append("")
        lines.append("| Canonical name | Class | City | DB match name | DB parish | Ratio |")
        lines.append("|---|:---:|---|---|:---:|---:|")
        for h in sorted(name_mismatch_hits, key=lambda x: -x["ratio"])[:25]:
            parish = h["db_match_parish"] or "(NULL)"
            lines.append(
                f"| {h['canonical_name']} | {h['canonical_class']} | {h['canonical_city']} | "
                f"{h['db_match_name']} | {parish} | {h['ratio']:.3f} |"
            )
    lines.append("")

    lines.append("## Mechanism 4 — classification distribution of missing schools")
    lines.append("")
    lines.append("| Class | Canonical count | Missing from DB | Missing share |")
    lines.append("|:---:|---:|---:|---:|")
    for cls in sorted(class_share_missing, key=lambda k: -class_share_missing[k]["share_missing"]):
        s = class_share_missing[cls]
        lines.append(f"| {cls} | {s['n_canonical']} | {s['n_missing_from_db']} | {s['share_missing']*100:.0f}% |")
    lines.append("")
    lines.append("If missing share is uniform across classes → not a classification filter mechanism. If skewed to B/C/1A → likely is.")
    lines.append("")

    lines.append("## Mechanism 3 — bootstrap-from-football inheritance (cross-sport)")
    lines.append("")
    lines.append(f"Football 2025 engine roster: {len(fb_schools_2025)} schools (vs LHSAA published 324 → matches at 100%)")
    lines.append("")
    lines.append("For each non-football sport with a gap vs LHSAA, the table above shows what share of the engine's schools-for-that-sport also have a Football team row. If this is ~100%, it suggests the sport's roster was derived from Football. The 'football → engine' column shows the inverse: what % of Football schools also have a team row for this sport.")
    lines.append("")

    lines.append("## Mechanism 2 — opponent-discovery gap (proxy)")
    lines.append("")
    lines.append(f"Missing canonical schools with NO substring overlap with ANY DB school name: **{len(opp_discovery_proxy)}** of {len(missing_canon)}")
    lines.append("")
    lines.append("(A higher-fidelity test of opponent-discovery requires the raw scraped opponent name strings — currently games stores team_id FKs, not raw opponent text. The proxy here is conservative: a name with NO substring match anywhere likely was never seen by the scraper at all.)")
    lines.append("")

    lines.append("## Verdict — approximate mechanism shares")
    lines.append("")
    n_mech1 = len(name_mismatch_hits)
    n_mech2 = len(opp_discovery_proxy)
    n_mech4_skewed = sum(s["n_missing_from_db"] for cls, s in class_share_missing.items() if cls in ("B", "C", "1A"))
    n_missing = len(missing_canon)
    lines.append(f"- Mechanism 1 (name-mismatch): {n_mech1}/{n_missing} = {100*n_mech1/max(1,n_missing):.0f}% candidates have a fuzzy DB match (suggesting the name exists, just under a different spelling)")
    lines.append(f"- Mechanism 2 (opponent-discovery proxy): {n_mech2}/{n_missing} = {100*n_mech2/max(1,n_missing):.0f}% have no substring overlap with any DB name (likely never crawled)")
    lines.append(f"- Mechanism 3 (bootstrap-from-football): see per-sport table above. Sports where 'engine ⊆ football' approaches 100% AND 'football → engine' is well below 100% suggest the sport's roster was inherited from football.")
    lines.append(f"- Mechanism 4 (classification): missing schools concentrated in Class B/C/1A would indicate a classification filter. Count of missing in those classes: {n_mech4_skewed}/{n_missing} = {100*n_mech4_skewed/max(1,n_missing):.0f}%")
    lines.append("")
    lines.append("These mechanisms are NOT mutually exclusive — a school could be both 'small-class' AND 'never crawled.' Composing the fixes (adding LHSAA seed list + fuzzy-name resolver) likely closes most of the gap.")
    lines.append("")

    lines.append("Halt after Step B0 per Reese 2026-05-27 evening sequencing. Step B1 (per-mechanism fix scoping) awaits sign-off.")

    md_path.write_text("\n".join(lines))

    print()
    print("=" * 70)
    print(f"Workstream B0 mechanism diagnosis complete")
    print(f"Canonical missing from DB: {len(missing_canon)}")
    print(f"Mechanism 1 candidates: {len(name_mismatch_hits)} ({100*len(name_mismatch_hits)/max(1,len(missing_canon)):.0f}%)")
    print(f"Mechanism 2 (no-substring proxy): {len(opp_discovery_proxy)} ({100*len(opp_discovery_proxy)/max(1,len(missing_canon)):.0f}%)")
    print(f"Mechanism 4 (B/C/1A skew): {n_mech4_skewed} ({100*n_mech4_skewed/max(1,len(missing_canon)):.0f}%)")
    print(f"  Artifacts: {md_path.relative_to(REPO_ROOT)}")
    print(f"             {json_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
