"""Check 0.7 — cross-source via LHSAA published Power-Rating PDFs.

Rewritten 2026-05-25 (per Reese's review). Adds:
  * Division + select_status filtering (PDF row's metadata must match our
    team's metadata before W/L counts are compared — fixes the
    Northlake-Div-IV-vs-Div-III-Select false-positive matches).
  * Snapshot interpretation upgrade: "Week N Final" and "Week N" snapshot
    strings now produce a week_cutoff that filters our games to
    week_number ≤ N. Date-bearing snapshots ("M/D/YYYY") continue to filter
    by game_date.
  * Cat 1/2/3 breakdown per spec:
        Cat 1 = games LHSAA shows but we don't  (inferred lower bound only)
        Cat 2 = games we have but LHSAA doesn't (inferred lower bound only)
        Cat 3 = games where both sides show the same total but disagree on
                the winner — directly observable from W/L counts (bright-line
                ingest-bug test).
  * Cat 3 inferability limit (documented inline): LHSAA PDFs only carry
    W/L totals, not game-by-game lists. From W/L alone, Cat 3 is only
    DEFINITELY detectable when N_pdf == N_ours but W != W. Other deltas
    are ambiguous between Cat 1/2 and Cat 3.

If a sport-season has no parsable PDF in the index, status='info' with
note "not cross-source-verified" — per the v2 plan, we accept uneven
coverage rather than build manual spot-check labor.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from scripts.audit.checks import CheckResult


# Cross-source decision thresholds (per-team rates). Per Reese's
# 2026-05-25 methodology review, ALL THREE categories gate the check
# (status = worst-of). Cat 1/Cat 2 thresholds added because the prior
# "Cat 3 only" semantics hid significant coverage gaps (e.g. Football 2023
# spot-check found 6/20 sampled teams missing games not flagged by Cat 3).
#
# Per-team rate = (teams in that category) / (teams compared).
CAT1_PASS_CEILING = 0.05    # ≤5%  — we're missing ≤5% of teams' games
CAT1_WARN_CEILING = 0.10    # ≤10% warn band
CAT2_PASS_CEILING = 0.10    # ≤10% — we have extras (legitimate: jamborees etc.)
CAT2_WARN_CEILING = 0.20    # ≤20% warn band (more permissive than Cat 1)
CAT3_PASS_CEILING = 0.02    # ≤2%  — winner disagreements; ingest bug bright line
CAT3_WARN_CEILING = 0.05    # ≤5%  warn band

# Legacy aliases (still referenced from older callers; safe to remove next pass)
PASS_RATE_CEILING = CAT3_PASS_CEILING
WARN_RATE_CEILING = CAT3_WARN_CEILING

# Off-by-1 in W or L counts is forgiven for *display* purposes (snapshot
# timing fuzz, forfeit bookkeeping). Cat 3 by construction requires N_pdf
# == N_ours, so timing fuzz doesn't apply — but we still surface
# off-by-one anomalies for inspection.
OFF_BY_ONE_TOLERANCE = 1


SPORT_NAME_TO_ID: dict[str, int] = {
    "football": 1,
    "volleyball": 2,
    "boys basketball": 5,
    "girls basketball": 6,
    "baseball": 11,
    "softball": 12,
    "boys soccer": 13,
    "girls soccer": 14,
}

_WEEK_RE = re.compile(r"\bWeek\s+(\d{1,2})\b", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _normalize(name: str) -> str:
    return name.lower().strip()


def _load_index() -> list[dict]:
    p = Path(__file__).resolve().parents[2] / "scripts" / "lhsaa_pdf_index.json"
    with open(p) as f:
        return json.load(f)["pdfs"]


def parse_snapshot(snapshot: str | None) -> tuple[date | None, int | None]:
    """Returns (snapshot_date, week_cutoff). Either or both may be None.

    Examples:
      "Week 10 Final" → (None, 10)
      "Week 8"        → (None, 8)
      "10/30/2023 Final" → (date(2023,10,30), None)
      "2/9/2024"      → (date(2024,2,9), None)
      "Final"         → (None, None)
    """
    if not snapshot:
        return None, None
    snapshot_date = None
    week_cutoff = None
    m = _DATE_RE.search(snapshot)
    if m:
        try:
            snapshot_date = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    m = _WEEK_RE.search(snapshot)
    if m:
        try:
            week_cutoff = int(m.group(1))
        except ValueError:
            pass
    return snapshot_date, week_cutoff


def _wl_as_of(
    games_for_team: list[dict],
    snapshot: date | None,
    week_cutoff: int | None,
) -> tuple[int, int, int]:
    """Wins/losses/total-games for one team, applying the snapshot filter.

    Filter precedence: (snapshot_date AND game_date applied if both present)
    AND (week_cutoff AND week_number applied if both present). A game must
    pass ALL active filters to count.

    is_out_of_state handling (2026-05-25): NOT filtered. LHSAA's PDF W/L
    columns INCLUDE out-of-state games (per docs/lhsaa_power_rating_rules.md
    and the U1 Update Tool); our comparison must include them to stay
    symmetric. Other audit checks (0.1, 0.2, 0.3, 0.4, 0.5) DO filter OOS
    via `_is_final_with_scores` in checks.py — that's intentional for
    intra-league sanity checks but would create false Cat 1 gaps here.

    Ties are excluded from W and L (LHSAA PDF W/L columns exclude them too).
    """
    w = l = total = 0
    for g in games_for_team:
        if g.get("status") not in ("final", "forfeit"):
            continue
        if g.get("home_score") is None or g.get("away_score") is None:
            continue
        # Snapshot-date filter
        if snapshot is not None:
            gd = g.get("game_date")
            if gd:
                try:
                    gd_date = datetime.fromisoformat(gd[:10]).date()
                    if gd_date > snapshot:
                        continue
                except (ValueError, TypeError):
                    pass
        # Week-cutoff filter (only meaningful for sports with stored week_number,
        # primarily football).
        if week_cutoff is not None:
            wn = g.get("week_number")
            if wn is not None:
                try:
                    if int(wn) > week_cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
        total += 1
        if g["_is_home"]:
            if g["home_score"] > g["away_score"]:
                w += 1
            elif g["home_score"] < g["away_score"]:
                l += 1
        else:
            if g["away_score"] > g["home_score"]:
                w += 1
            elif g["away_score"] < g["home_score"]:
                l += 1
    return w, l, total


def _index_games_by_team(games: list[dict]) -> dict[int, list[dict]]:
    by_team: dict[int, list[dict]] = defaultdict(list)
    for g in games:
        if g.get("home_team_id"):
            by_team[g["home_team_id"]].append({**g, "_is_home": True})
        if g.get("away_team_id"):
            by_team[g["away_team_id"]].append({**g, "_is_home": False})
    return by_team


def _match_school(query: str, schools_by_name: dict[str, int], threshold: float = 0.75) -> int | None:
    from difflib import SequenceMatcher
    q = _normalize(query)
    for name, sid in schools_by_name.items():
        if _normalize(name) == q:
            return sid
    best_score, best_id = 0.0, None
    for name, sid in schools_by_name.items():
        score = SequenceMatcher(None, q, _normalize(name)).ratio()
        if score > best_score and score >= threshold:
            best_score, best_id = score, sid
    return best_id


def _div_and_select_match(
    pdf_row_div: str | None,
    pdf_row_select: str | None,
    entry_div: str | None,
    entry_select: str | None,
    our_team_div: str | None,
    our_team_select: str | None,
) -> bool:
    """All three must be consistent: the entry's intended scope, the parsed
    row's claimed division+select, and our team's division+select.

    Normalization: divisions can be Roman ("I"..."V") or class-numeric
    ("5A"..."1A", "B", "C"). We compare strings case-insensitively after
    stripping whitespace; mismatched encodings count as no-match (the
    caller should normalize beforehand if needed).
    """
    def _norm(s: str | None) -> str:
        return (s or "").strip().lower()

    # Entry's intended division — only enforce when not "all"
    if _norm(entry_div) not in ("", "all"):
        if _norm(pdf_row_div) != _norm(entry_div):
            return False
        if _norm(our_team_div) != _norm(entry_div):
            return False
    # Entry's intended select — only enforce when set
    if _norm(entry_select):
        if _norm(pdf_row_select) and _norm(pdf_row_select) != _norm(entry_select):
            return False
        if _norm(our_team_select) and _norm(our_team_select) != _norm(entry_select):
            return False
    return True


def _categorize(pdf_w: int, pdf_l: int, ours_w: int, ours_l: int) -> dict[str, int]:
    """Cat 1/2/3 inference from W/L totals only.

    Cat 3 (winner disagreement) is DEFINITELY observable only when totals
    match exactly. With unmatched totals, a winner disagreement is masked
    by the scope difference. We report:
      cat3_definite   — guaranteed Cat 3 count when N_pdf == N_ours
      cat1_lower_bound — min games LHSAA shows that we don't (if N_pdf > N_ours)
      cat2_lower_bound — min games we have that LHSAA doesn't (if N_ours > N_pdf)
      net_total_delta  — (N_ours − N_pdf) raw integer
    """
    n_pdf = pdf_w + pdf_l
    n_ours = ours_w + ours_l
    out = {
        "n_pdf": n_pdf,
        "n_ours": n_ours,
        "net_total_delta": n_ours - n_pdf,
        "cat1_lower_bound": max(0, n_pdf - n_ours),
        "cat2_lower_bound": max(0, n_ours - n_pdf),
        "cat3_definite": 0,
    }
    if n_pdf == n_ours and n_pdf > 0:
        # Pure Cat 3 case: same total, different splits → guaranteed winner
        # disagreement on |Δw| games (and same on |Δl| by symmetry).
        out["cat3_definite"] = abs(ours_w - pdf_w)
    return out


def check_0_7_cross_source(
    sport_id: int,
    sport_name: str,
    season_year: int,
    games: list[dict],
    teams_for_sport_season: dict[int, dict],
    schools_by_name: dict[str, int],
    pdf_index: list[dict] | None = None,
) -> CheckResult:
    """One CheckResult per (sport, season).

    Aggregates per-PDF Cat 1/2/3 breakdowns. Gating threshold is the Cat 3
    definite-mismatch rate (n_cat3_teams / n_compared_teams).
    """
    # Import here so unit tests can swap a stub via monkeypatch without
    # pulling in pdfplumber/httpx at module import time.
    from scripts.parse_lhsaa_pdf import parse_pdf

    if pdf_index is None:
        pdf_index = _load_index()

    entries = [
        e
        for e in pdf_index
        if _normalize(e.get("sport", "")) == _normalize(sport_name)
        and int(e.get("season_year", 0)) == season_year
    ]
    if not entries:
        return CheckResult(
            check_name="0.7_cross_source",
            status="info",
            sport_id=sport_id,
            sport_name=sport_name,
            season_year=season_year,
            metrics={"n_pdfs": 0, "note": "not cross-source-verified (no LHSAA PDF in index)"},
            thresholds={
                "pass_rate_ceiling_cat3": PASS_RATE_CEILING,
                "warn_rate_ceiling_cat3": WARN_RATE_CEILING,
            },
        )

    school_to_team: dict[int, int] = {
        t.get("school_id"): tid
        for tid, t in teams_for_sport_season.items()
        if t.get("school_id") is not None
    }
    games_by_team = _index_games_by_team(games)

    # Aggregate counters
    n_pdfs_parsed = 0
    n_pdfs_skipped_parse = 0
    n_rows_total = 0
    n_rows_no_school_match = 0
    n_rows_no_team = 0
    n_rows_div_select_filtered = 0
    n_rows_compared = 0
    n_exact = 0
    n_off_by_one_forgiven = 0
    n_cat1_teams = 0   # teams with cat1_lower_bound > 0 (we're missing games)
    n_cat2_teams = 0   # teams with cat2_lower_bound > 0 (we have extras)
    n_cat3_teams = 0   # teams with cat3_definite > 0 (winner disagreements)
    sum_cat3_definite = 0
    sum_cat1_lower = 0
    sum_cat2_lower = 0
    anomalies: list[dict] = []

    for entry in entries:
        try:
            rows = parse_pdf(entry)
        except Exception as exc:
            n_pdfs_skipped_parse += 1
            anomalies.append({"type": "pdf_parse_error", "url": entry.get("url"), "error": str(exc)[:200]})
            continue
        if not rows:
            n_pdfs_skipped_parse += 1
            anomalies.append({"type": "pdf_no_rows", "url": entry.get("url")})
            continue
        n_pdfs_parsed += 1

        snapshot_date, week_cutoff = parse_snapshot(entry.get("snapshot"))
        entry_div = entry.get("division")
        entry_select = entry.get("select_status")

        for r in rows:
            n_rows_total += 1
            school_id = _match_school(r.school_name, schools_by_name)
            if school_id is None:
                n_rows_no_school_match += 1
                continue
            team_id = school_to_team.get(school_id)
            if team_id is None:
                n_rows_no_team += 1
                continue

            our_team = teams_for_sport_season.get(team_id, {})
            if not _div_and_select_match(
                r.division, r.select_status,
                entry_div, entry_select,
                our_team.get("division"), our_team.get("select_status"),
            ):
                n_rows_div_select_filtered += 1
                continue

            ours_w, ours_l, ours_n = _wl_as_of(
                games_by_team.get(team_id, []), snapshot_date, week_cutoff
            )
            n_rows_compared += 1
            cat = _categorize(r.wins, r.losses, ours_w, ours_l)
            sum_cat1_lower += cat["cat1_lower_bound"]
            sum_cat2_lower += cat["cat2_lower_bound"]
            sum_cat3_definite += cat["cat3_definite"]

            wdiff = abs(ours_w - r.wins)
            ldiff = abs(ours_l - r.losses)
            if wdiff == 0 and ldiff == 0:
                n_exact += 1
            elif cat["cat3_definite"] == 0 and wdiff <= OFF_BY_ONE_TOLERANCE and ldiff <= OFF_BY_ONE_TOLERANCE:
                n_off_by_one_forgiven += 1

            if cat["cat1_lower_bound"] > 0:
                n_cat1_teams += 1
            if cat["cat2_lower_bound"] > 0:
                n_cat2_teams += 1
            if cat["cat3_definite"] > 0:
                n_cat3_teams += 1

            # Surface anomalies: any team with Cat 3 OR any team with a
            # meaningful coverage gap (Cat 1 ≥ 1 game OR Cat 2 ≥ 2 games).
            # Capped at 200 entries to keep the JSON manageable.
            should_surface = (
                cat["cat3_definite"] > 0
                or cat["cat1_lower_bound"] >= 1
                or cat["cat2_lower_bound"] >= 2
            )
            if len(anomalies) < 200 and should_surface:
                anomaly_type = (
                    "cat3_definite" if cat["cat3_definite"] > 0
                    else "cat1_missing_games" if cat["cat1_lower_bound"] > cat["cat2_lower_bound"]
                    else "cat2_extra_games"
                )
                anomalies.append(
                    {
                        "type": anomaly_type,
                        "school_name": r.school_name,
                        "team_id": team_id,
                        "pdf_snapshot": r.snapshot_date.isoformat() if r.snapshot_date else None,
                        "snapshot_week_cutoff": week_cutoff,
                        "pdf_wins": r.wins,
                        "pdf_losses": r.losses,
                        "our_wins": ours_w,
                        "our_losses": ours_l,
                        "our_total_after_filter": ours_n,
                        "cat1_lower_bound": cat["cat1_lower_bound"],
                        "cat2_lower_bound": cat["cat2_lower_bound"],
                        "cat3_definite": cat["cat3_definite"],
                        "net_total_delta": cat["net_total_delta"],
                        "entry_division": entry_div,
                        "entry_select": entry_select,
                        "pdf_url": entry.get("url"),
                    }
                )

    # Per-team rates (Cat 1, 2, 3 each gate independently — status = worst-of)
    if n_rows_compared:
        cat1_rate = n_cat1_teams / n_rows_compared
        cat2_rate = n_cat2_teams / n_rows_compared
        cat3_rate = n_cat3_teams / n_rows_compared
    else:
        cat1_rate = cat2_rate = cat3_rate = 0.0

    def _status_for(rate: float, pass_ceil: float, warn_ceil: float) -> str:
        if rate <= pass_ceil:
            return "pass"
        if rate <= warn_ceil:
            return "warn"
        return "fail"

    cat1_status = _status_for(cat1_rate, CAT1_PASS_CEILING, CAT1_WARN_CEILING)
    cat2_status = _status_for(cat2_rate, CAT2_PASS_CEILING, CAT2_WARN_CEILING)
    cat3_status = _status_for(cat3_rate, CAT3_PASS_CEILING, CAT3_WARN_CEILING)

    if n_rows_compared == 0:
        status = "info"
    else:
        # Worst-of (fail > warn > pass)
        rank = {"pass": 0, "warn": 1, "fail": 2}
        status = max([cat1_status, cat2_status, cat3_status], key=lambda s: rank[s])

    return CheckResult(
        check_name="0.7_cross_source",
        status=status,
        sport_id=sport_id,
        sport_name=sport_name,
        season_year=season_year,
        metrics={
            "n_pdfs_in_index": len(entries),
            "n_pdfs_parsed": n_pdfs_parsed,
            "n_pdfs_skipped_parse": n_pdfs_skipped_parse,
            "n_rows_total": n_rows_total,
            "n_rows_no_school_match": n_rows_no_school_match,
            "n_rows_no_team": n_rows_no_team,
            "n_rows_div_select_filtered": n_rows_div_select_filtered,
            "n_rows_compared": n_rows_compared,
            "n_exact": n_exact,
            "n_off_by_one_forgiven": n_off_by_one_forgiven,
            "n_cat1_teams": n_cat1_teams,
            "n_cat2_teams": n_cat2_teams,
            "n_cat3_teams": n_cat3_teams,
            "sum_cat1_lower_bound_games": sum_cat1_lower,
            "sum_cat2_lower_bound_games": sum_cat2_lower,
            "sum_cat3_definite_games": sum_cat3_definite,
            "cat1_team_rate": round(cat1_rate, 4),
            "cat2_team_rate": round(cat2_rate, 4),
            "cat3_team_rate": round(cat3_rate, 4),
            "cat1_status": cat1_status,
            "cat2_status": cat2_status,
            "cat3_status": cat3_status,
        },
        thresholds={
            "cat1_pass_ceiling": CAT1_PASS_CEILING,
            "cat1_warn_ceiling": CAT1_WARN_CEILING,
            "cat2_pass_ceiling": CAT2_PASS_CEILING,
            "cat2_warn_ceiling": CAT2_WARN_CEILING,
            "cat3_pass_ceiling": CAT3_PASS_CEILING,
            "cat3_warn_ceiling": CAT3_WARN_CEILING,
            "off_by_one_tolerance": OFF_BY_ONE_TOLERANCE,
            "gating_metric": (
                "worst-of(cat1_status, cat2_status, cat3_status). "
                "Cat 1 = teams with cat1_lower_bound > 0 (we're missing games); "
                "Cat 2 = teams with cat2_lower_bound > 0 (we have extras — "
                "jamborees, non-LHSAA games can be legitimate); "
                "Cat 3 = teams with cat3_definite > 0 (winner disagreement)."
            ),
            "out_of_state_handling": (
                "Included on our side to mirror LHSAA's PDF which counts "
                "out-of-state games via the U1 Update Tool."
            ),
            "cat3_inferability_note": (
                "From W/L counts alone, Cat 3 is definitely observable only "
                "when N_pdf == N_ours and W splits differ. Other deltas are "
                "ambiguous (could be Cat 1 + Cat 3, Cat 2 + Cat 3, etc.). "
                "Per-game cross-check would require an independent game-level "
                "source (e.g., MaxPreps schedules) — out of scope for v2 spec."
            ),
        },
        anomalies=anomalies,
    )
