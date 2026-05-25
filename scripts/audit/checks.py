"""Phase 0 data sanity checks.

Each check function takes the raw inputs it needs and returns a
``CheckResult``. The runner is responsible for loading data once and
dispatching the result of one check at a time so the writer layer can stream
out as it goes (instead of holding everything in memory).

Status convention:
  * ``pass``  — value within the safe band; no action needed.
  * ``warn``  — value drifted into a tolerated-but-watch zone.
  * ``fail``  — value outside any acceptable range; downstream work
                that assumes clean data must not proceed.
  * ``info``  — measurement-only (no pass/fail semantics). Used for
                checks that surface diagnostics rather than assertions
                (mercy-rule rate, classification drift).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from statistics import mean, pstdev
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Check 0.1 — home win rate (ties excluded from denominator).
# Full-range bands: every value lands in exactly one bucket. Tightened upper
# FAIL cliff to 0.65 per 2026-05-25 review — anything above is bug-suspicious,
# not natural HFA. Lower FAIL cliff at <0.40 (extreme away-bias) is symmetric.
HOME_WIN_RATE_PASS_LO, HOME_WIN_RATE_PASS_HI = 0.50, 0.62
HOME_WIN_RATE_WARN_LO, HOME_WIN_RATE_WARN_HI = 0.40, 0.65

# Check 0.2 — sport-specific expected mean total score (rough plausibility band)
EXPECTED_TOTAL_SCORE_BAND: dict[str, tuple[float, float]] = {
    "Football": (30.0, 80.0),
    "Boys Basketball": (80.0, 160.0),
    "Girls Basketball": (60.0, 140.0),
    "Baseball": (4.0, 18.0),
    "Softball": (4.0, 22.0),
    "Volleyball": (1.0, 10.0),
    "Boys Soccer": (0.5, 9.0),
    "Girls Soccer": (0.5, 9.0),
}
NULL_SCORE_RATE_PASS = 0.005
NULL_SCORE_RATE_WARN = 0.02
# Per-game total-score outlier threshold — surface anything in the top 0.5%
# of totals as an anomaly for inspection (added 2026-05-25 per review).
SCORE_OUTLIER_PERCENTILE = 0.995
SCORE_OUTLIER_ANOMALY_CAP = 50

# Check 0.3 — per-team home/away imbalance.
# Calibrated to HS football's 10-game regular season: binomial(10, 0.5)
# gives σ≈1.6 games → ±3 (imbalance 0.30) covers ~95% of natural variation.
# For longer-season sports (basketball ~30, baseball ~30) this is comfortably
# loose. Anything past 0.30 is genuinely skewed (likely real but worth a look).
TEAM_IMBALANCE_TOL = 0.30
TEAM_BALANCE_PASS_FRAC = 0.90
TEAM_BALANCE_WARN_FRAC = 0.75

# Check 0.5 — mercy-rule absolute score-diff threshold per sport.
# Tuned 2026-05-25: Football 36 (one TD past 5-TD blowout), Basketball 35
# both genders (HS norm), Baseball 15 (above LHSAA's 10-run rule — surfaces
# clearly uncompetitive games beyond the run-rule shortened ones), Softball
# 10 (LHSAA run-rule margin — unchanged), Soccer 5 (1-goal margins are
# competitive; 5+ is a blowout).
#
# Volleyball SPECIAL CASE: spec calls for (a) 3-0 sweep AND every set won by
# 8+ points OR (b) total point differential ≥ 30 across all sets. BOTH
# require per-set point totals we don't have — games.home_score / away_score
# store only sets-won (0-3). The most we can detect with the current
# schema is 3-0 sweeps (set-margin 3). The volleyball check below carries
# an explicit data-constraint note in its output so the limitation is
# visible in reports rather than buried in code. A future schema change
# (re-scrape with per-set scores) would unlock spec options (a) and (b).
MERCY_THRESHOLD_BY_SPORT: dict[str, int] = {
    "Football": 36,
    "Boys Basketball": 35,
    "Girls Basketball": 35,
    "Baseball": 15,
    "Softball": 10,
    "Boys Soccer": 5,
    "Girls Soccer": 5,
    "Volleyball": 3,  # 3-0 sweeps only; per-set data needed for spec rule
}
MERCY_DATA_CONSTRAINT_NOTE: dict[str, str] = {
    "Volleyball": (
        "Per-set point data not in current schema; only 3-0 set-sweep "
        "(margin == 3) is detectable. Spec rule '(a) 3-0 AND every set "
        "won by 8+' or '(b) total point differential ≥ 30' requires a "
        "schema upgrade (re-scrape with per-set point totals)."
    ),
}

# Check 0.6 — rewritten 2026-05-25.
# Was: counted distinct values in schools.classification (school-level field,
# never changes across seasons in our schema) — structurally found 0/N drift.
# Now: counts changes in teams.division across seasons for the same school,
# which IS per-season. Threshold = 0 (any change is flagged).
DIVISION_DRIFT_MAX_CHANGES = 0


# ---------------------------------------------------------------------------
# CheckResult container
# ---------------------------------------------------------------------------

Status = Literal["pass", "warn", "fail", "info"]


@dataclass
class CheckResult:
    check_name: str
    status: Status
    sport_id: int | None = None
    sport_name: str | None = None
    season_year: int | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    anomalies: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_final_with_scores(g: dict) -> bool:
    return (
        g.get("status") in ("final", "forfeit")
        and g.get("home_score") is not None
        and g.get("away_score") is not None
        and not g.get("is_out_of_state")
    )


def _status_from_thresholds(
    value: float,
    pass_lo: float,
    pass_hi: float,
    warn_lo: float,
    warn_hi: float,
) -> Status:
    if pass_lo <= value <= pass_hi:
        return "pass"
    if warn_lo <= value <= warn_hi:
        return "warn"
    return "fail"


# ---------------------------------------------------------------------------
# 0.1 — home/away win-rate sanity
# ---------------------------------------------------------------------------

def check_0_1_home_away_sanity(
    games: list[dict],
    sport_id: int,
    sport_name: str,
    season_year: int,
) -> CheckResult:
    valid = [g for g in games if _is_final_with_scores(g)]
    n_total = len(valid)
    n_home_wins = sum(1 for g in valid if g["home_score"] > g["away_score"])
    n_away_wins = sum(1 for g in valid if g["away_score"] > g["home_score"])
    n_ties = sum(1 for g in valid if g["home_score"] == g["away_score"])
    decisive = n_home_wins + n_away_wins
    home_win_rate = (n_home_wins / decisive) if decisive else 0.0
    tie_rate = (n_ties / n_total) if n_total else 0.0

    status: Status
    if n_total < 20:
        status = "info"
    else:
        status = _status_from_thresholds(
            home_win_rate,
            HOME_WIN_RATE_PASS_LO,
            HOME_WIN_RATE_PASS_HI,
            HOME_WIN_RATE_WARN_LO,
            HOME_WIN_RATE_WARN_HI,
        )

    return CheckResult(
        check_name="0.1_home_away_sanity",
        status=status,
        sport_id=sport_id,
        sport_name=sport_name,
        season_year=season_year,
        metrics={
            "n_games": n_total,
            "n_home_wins": n_home_wins,
            "n_away_wins": n_away_wins,
            "n_ties": n_ties,
            "home_win_rate": round(home_win_rate, 4),
            "tie_rate": round(tie_rate, 4),
        },
        thresholds={
            "pass_band": [HOME_WIN_RATE_PASS_LO, HOME_WIN_RATE_PASS_HI],
            "warn_band": [HOME_WIN_RATE_WARN_LO, HOME_WIN_RATE_WARN_HI],
            "min_sample_for_pass_fail": 20,
        },
    )


# ---------------------------------------------------------------------------
# 0.2 — score distribution
# ---------------------------------------------------------------------------

def check_0_2_score_distribution(
    games: list[dict],
    sport_id: int,
    sport_name: str,
    season_year: int,
) -> CheckResult:
    n_total = len(games)
    n_status_final = sum(1 for g in games if g.get("status") in ("final", "forfeit"))
    n_null_score = sum(
        1
        for g in games
        if g.get("status") in ("final", "forfeit")
        and (g.get("home_score") is None or g.get("away_score") is None)
    )
    n_negative = sum(
        1
        for g in games
        if (g.get("home_score") is not None and g["home_score"] < 0)
        or (g.get("away_score") is not None and g["away_score"] < 0)
    )

    valid = [g for g in games if _is_final_with_scores(g)]
    totals = [g["home_score"] + g["away_score"] for g in valid]
    home_scores = [g["home_score"] for g in valid]
    away_scores = [g["away_score"] for g in valid]

    null_score_rate = (n_null_score / n_status_final) if n_status_final else 0.0
    mean_total = mean(totals) if totals else 0.0
    band = EXPECTED_TOTAL_SCORE_BAND.get(sport_name, (None, None))

    # p99.5 outlier cutoff (only meaningful with enough data points)
    p995_cutoff: int | None = None
    if len(totals) >= 200:
        sorted_totals = sorted(totals)
        p995_cutoff = sorted_totals[int(len(sorted_totals) * SCORE_OUTLIER_PERCENTILE)]

    status: Status
    if n_negative > 0:
        status = "fail"
    elif null_score_rate > NULL_SCORE_RATE_WARN:
        status = "fail"
    elif band[0] is not None and not (band[0] <= mean_total <= band[1]):
        status = "fail"
    elif null_score_rate > NULL_SCORE_RATE_PASS:
        status = "warn"
    else:
        status = "pass"

    anomalies: list[dict] = []
    # Always surface NULL/negative anomalies (rare). Always surface top-0.5%
    # outliers (capped) so reviewers can spot data-entry mistakes (e.g. 144-0
    # final scores worth verifying).
    for g in games:
        if g.get("status") in ("final", "forfeit") and (
            g.get("home_score") is None or g.get("away_score") is None
        ):
            anomalies.append(
                {
                    "type": "null_score",
                    "game_id": g.get("id"),
                    "home_team_id": g.get("home_team_id"),
                    "away_team_id": g.get("away_team_id"),
                    "game_date": g.get("game_date"),
                    "home_score": g.get("home_score"),
                    "away_score": g.get("away_score"),
                }
            )
        elif (g.get("home_score") is not None and g["home_score"] < 0) or (
            g.get("away_score") is not None and g["away_score"] < 0
        ):
            anomalies.append(
                {
                    "type": "negative_score",
                    "game_id": g.get("id"),
                    "home_score": g.get("home_score"),
                    "away_score": g.get("away_score"),
                }
            )
        if len(anomalies) >= 200:
            break

    if p995_cutoff is not None:
        # Sort by total desc; emit up to SCORE_OUTLIER_ANOMALY_CAP rows.
        flagged = sorted(
            (g for g in valid if (g["home_score"] + g["away_score"]) > p995_cutoff),
            key=lambda g: -(g["home_score"] + g["away_score"]),
        )[:SCORE_OUTLIER_ANOMALY_CAP]
        for g in flagged:
            anomalies.append(
                {
                    "type": "score_outlier_p995",
                    "game_id": g.get("id"),
                    "home_team_id": g.get("home_team_id"),
                    "away_team_id": g.get("away_team_id"),
                    "game_date": g.get("game_date"),
                    "home_score": g.get("home_score"),
                    "away_score": g.get("away_score"),
                    "total": g["home_score"] + g["away_score"],
                    "cutoff": p995_cutoff,
                }
            )

    return CheckResult(
        check_name="0.2_score_distribution",
        status=status,
        sport_id=sport_id,
        sport_name=sport_name,
        season_year=season_year,
        metrics={
            "n_total_rows": n_total,
            "n_final_or_forfeit": n_status_final,
            "n_valid_scored": len(valid),
            "n_null_score_in_final": n_null_score,
            "n_negative_score": n_negative,
            "null_score_rate": round(null_score_rate, 6),
            "home_score_mean": round(mean(home_scores), 2) if home_scores else 0.0,
            "away_score_mean": round(mean(away_scores), 2) if away_scores else 0.0,
            "total_score_mean": round(mean_total, 2),
            "total_score_std": round(pstdev(totals), 2) if len(totals) > 1 else 0.0,
            "total_score_min": min(totals) if totals else 0,
            "total_score_max": max(totals) if totals else 0,
            "total_score_p99_5": p995_cutoff,
            "n_p99_5_outliers": sum(1 for t in totals if p995_cutoff is not None and t > p995_cutoff),
        },
        thresholds={
            "expected_total_band": list(band) if band[0] is not None else None,
            "null_score_rate_pass": NULL_SCORE_RATE_PASS,
            "null_score_rate_warn": NULL_SCORE_RATE_WARN,
            "outlier_percentile": SCORE_OUTLIER_PERCENTILE,
            "outlier_anomaly_cap": SCORE_OUTLIER_ANOMALY_CAP,
        },
        anomalies=anomalies,
    )


# ---------------------------------------------------------------------------
# 0.3 — per-team home/away balance
# ---------------------------------------------------------------------------

def check_0_3_team_game_balance(
    games: list[dict],
    teams: dict[int, dict],
    sport_id: int,
    sport_name: str,
    season_year: int,
) -> CheckResult:
    valid = [g for g in games if _is_final_with_scores(g)]
    home_counts: Counter[int] = Counter()
    away_counts: Counter[int] = Counter()
    for g in valid:
        home_counts[g["home_team_id"]] += 1
        away_counts[g["away_team_id"]] += 1

    team_ids = set(home_counts) | set(away_counts)
    per_team_imbalance: list[tuple[int, int, int, float]] = []
    for tid in team_ids:
        h, a = home_counts[tid], away_counts[tid]
        total = h + a
        imbalance = abs(h - a) / total if total else 0.0
        per_team_imbalance.append((tid, h, a, imbalance))

    n_teams = len(per_team_imbalance)
    n_balanced = sum(1 for *_, imb in per_team_imbalance if imb <= TEAM_IMBALANCE_TOL)
    frac_balanced = (n_balanced / n_teams) if n_teams else 1.0

    status: Status
    if n_teams < 10:
        status = "info"
    elif frac_balanced >= TEAM_BALANCE_PASS_FRAC:
        status = "pass"
    elif frac_balanced >= TEAM_BALANCE_WARN_FRAC:
        status = "warn"
    else:
        status = "fail"

    anomalies: list[dict] = []
    for tid, h, a, imb in sorted(per_team_imbalance, key=lambda x: -x[3])[:50]:
        if imb <= TEAM_IMBALANCE_TOL:
            continue
        t = teams.get(tid, {})
        anomalies.append(
            {
                "team_id": tid,
                "school_name": t.get("school_name"),
                "division": t.get("division"),
                "home_games": h,
                "away_games": a,
                "imbalance": round(imb, 3),
            }
        )

    return CheckResult(
        check_name="0.3_team_game_balance",
        status=status,
        sport_id=sport_id,
        sport_name=sport_name,
        season_year=season_year,
        metrics={
            "n_teams": n_teams,
            "n_teams_balanced": n_balanced,
            "frac_balanced": round(frac_balanced, 4),
            "median_imbalance": round(
                sorted(imb for *_, imb in per_team_imbalance)[len(per_team_imbalance) // 2],
                4,
            ) if per_team_imbalance else 0.0,
            "max_imbalance": round(max((imb for *_, imb in per_team_imbalance), default=0.0), 4),
        },
        thresholds={
            "imbalance_tolerance": TEAM_IMBALANCE_TOL,
            "pass_frac": TEAM_BALANCE_PASS_FRAC,
            "warn_frac": TEAM_BALANCE_WARN_FRAC,
            "min_teams_for_pass_fail": 10,
        },
        anomalies=anomalies,
    )


# ---------------------------------------------------------------------------
# 0.4 — intra-division W/L arithmetic
# ---------------------------------------------------------------------------

def check_0_4_league_arithmetic(
    games: list[dict],
    teams: dict[int, dict],
    sport_id: int,
    sport_name: str,
    season_year: int,
) -> CheckResult:
    """League arithmetic invariants for intra- and cross-division games.

    Ties handling: counted as their own bucket (ties), NOT as half-W +
    half-L. The invariant `games == home_wins + away_wins + ties` must
    hold for every division and for the cross-division aggregate.

    Intra-division: ΣW per division equals ΣL per division by construction
    (1 W + 1 L per game) so we don't separately assert it.

    Cross-division (home.division != away.division): tracked as a separate
    aggregate so we can see how many games span divisions and confirm those
    rows are internally consistent. A cross-division "anomaly" doesn't fail
    the check — it's informational.
    """
    valid = [g for g in games if _is_final_with_scores(g)]
    by_division: dict[str, dict[str, int]] = defaultdict(
        lambda: {"games": 0, "home_wins": 0, "away_wins": 0, "ties": 0}
    )
    cross_div: dict[str, int] = {"games": 0, "home_wins": 0, "away_wins": 0, "ties": 0}
    n_missing_division = 0

    for g in valid:
        h_div = teams.get(g["home_team_id"], {}).get("division")
        a_div = teams.get(g["away_team_id"], {}).get("division")
        if not h_div or not a_div:
            n_missing_division += 1
            continue
        bucket = by_division[h_div] if h_div == a_div else cross_div
        bucket["games"] += 1
        if g["home_score"] > g["away_score"]:
            bucket["home_wins"] += 1
        elif g["away_score"] > g["home_score"]:
            bucket["away_wins"] += 1
        else:
            bucket["ties"] += 1

    anomalies: list[dict] = []
    fail_any = False
    for div, b in sorted(by_division.items()):
        decisive = b["home_wins"] + b["away_wins"]
        if b["games"] != decisive + b["ties"]:
            fail_any = True
            anomalies.append(
                {
                    "scope": f"intra:{div}",
                    "games": b["games"],
                    "decisive": decisive,
                    "ties": b["ties"],
                    "expected_zero": 0,
                    "actual": b["games"] - decisive - b["ties"],
                }
            )

    # Same invariant on the cross-division aggregate
    cd_decisive = cross_div["home_wins"] + cross_div["away_wins"]
    if cross_div["games"] != cd_decisive + cross_div["ties"]:
        fail_any = True
        anomalies.append(
            {
                "scope": "cross-division",
                "games": cross_div["games"],
                "decisive": cd_decisive,
                "ties": cross_div["ties"],
                "expected_zero": 0,
                "actual": cross_div["games"] - cd_decisive - cross_div["ties"],
            }
        )

    status: Status
    if not by_division and cross_div["games"] == 0:
        status = "info"
    elif fail_any:
        status = "fail"
    else:
        status = "pass"

    return CheckResult(
        check_name="0.4_league_arithmetic",
        status=status,
        sport_id=sport_id,
        sport_name=sport_name,
        season_year=season_year,
        metrics={
            "n_divisions": len(by_division),
            "intra_division_games": sum(b["games"] for b in by_division.values()),
            "cross_division_games": cross_div["games"],
            "n_games_missing_division_label": n_missing_division,
            "by_division": dict(by_division),
            "cross_division": dict(cross_div),
        },
        thresholds={
            "intra_invariant": "games == home_wins + away_wins + ties (per division)",
            "cross_invariant": "games == home_wins + away_wins + ties (cross-division aggregate)",
            "ties_handled_as": "own bucket (not split into half-W/half-L)",
        },
        anomalies=anomalies,
    )


# ---------------------------------------------------------------------------
# 0.5 — mercy-rule detection
# ---------------------------------------------------------------------------

def check_0_5_mercy_rule(
    games: list[dict],
    sport_id: int,
    sport_name: str,
    season_year: int,
) -> CheckResult:
    valid = [g for g in games if _is_final_with_scores(g)]
    threshold = MERCY_THRESHOLD_BY_SPORT.get(sport_name)
    if threshold is None:
        return CheckResult(
            check_name="0.5_mercy_rule",
            status="info",
            sport_id=sport_id,
            sport_name=sport_name,
            season_year=season_year,
            metrics={"n_games": len(valid), "note": "no mercy threshold defined for this sport"},
        )

    n_games = len(valid)
    margins = [abs(g["home_score"] - g["away_score"]) for g in valid]
    n_mercy = sum(1 for m in margins if m >= threshold)
    mercy_rate = (n_mercy / n_games) if n_games else 0.0

    metrics = {
        "n_games": n_games,
        "threshold": threshold,
        "n_mercy_games": n_mercy,
        "mercy_rate": round(mercy_rate, 4),
        "max_margin": max(margins) if margins else 0,
        "p99_margin": sorted(margins)[int(len(margins) * 0.99)] if len(margins) >= 100 else None,
    }
    constraint = MERCY_DATA_CONSTRAINT_NOTE.get(sport_name)
    if constraint:
        metrics["data_constraint_note"] = constraint

    return CheckResult(
        check_name="0.5_mercy_rule",
        status="info",
        sport_id=sport_id,
        sport_name=sport_name,
        season_year=season_year,
        metrics=metrics,
        thresholds={"sport_threshold": threshold},
    )


# ---------------------------------------------------------------------------
# 0.6 — classification drift across seasons
# ---------------------------------------------------------------------------

def check_0_6_classification_drift(
    teams_all_seasons: list[dict],
    sport_id: int,
    sport_name: str,
) -> CheckResult:
    """How often does a school's *division* (per-season) change across seasons?

    Reads `teams.division` — the per-season field. The old version read
    `schools.classification` which is school-level (never changes) so always
    found 0 drift. Threshold = 0; ANY change is flagged as info.

    Why this matters: walk-forward validation should be aware of teams that
    move divisions between train/test folds, because rating distributions
    shift across divisions and a team's prior-year carryover is much less
    informative when they jumped class.
    """
    # Group by school -> ordered list of (season, division)
    by_school: dict[int, list[tuple[int, str | None]]] = defaultdict(list)
    for t in teams_all_seasons:
        if t.get("sport_id") != sport_id:
            continue
        sid = t.get("school_id")
        season = t.get("season_year")
        div = t.get("division")
        if sid is None or season is None:
            continue
        by_school[sid].append((int(season), div))

    anomalies: list[dict] = []
    n_schools = 0
    n_drifted = 0
    drift_counts: Counter[int] = Counter()
    for sid, series in by_school.items():
        series.sort()
        n_schools += 1
        distinct_nonnull = [c for _, c in series if c is not None]
        changes = sum(
            1
            for i in range(1, len(distinct_nonnull))
            if distinct_nonnull[i] != distinct_nonnull[i - 1]
        )
        drift_counts[changes] += 1
        if changes > DIVISION_DRIFT_MAX_CHANGES:
            n_drifted += 1
            anomalies.append(
                {
                    "school_id": sid,
                    "n_changes": changes,
                    "timeline": [{"season": s, "division": c} for s, c in series],
                }
            )

    return CheckResult(
        check_name="0.6_division_drift",
        status="info",
        sport_id=sport_id,
        sport_name=sport_name,
        season_year=None,
        metrics={
            "n_schools": n_schools,
            "n_drifted_above_threshold": n_drifted,
            "change_count_histogram": dict(drift_counts),
        },
        thresholds={
            "field_read": "teams.division (per-season)",
            "max_changes_before_flag": DIVISION_DRIFT_MAX_CHANGES,
        },
        anomalies=anomalies[:100],
    )
