"""Reclassification-event detector.

Per Reese's 2026-05-25 review: when ≥ threshold fraction of teams in a
sport changes division vs the prior season, that's a fleet-wide
reclassification event — load-bearing for walk-forward fold construction
because it represents a regime change that prior-year carryover features
must explicitly account for.

Reports events as a distinct section in SUMMARY.md (NOT buried inside
0.6_division_drift's per-school flagging). The threshold is configurable.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any


DEFAULT_EVENT_THRESHOLD = 0.50
# Don't fire a fleet-wide event from a too-small sample. With sparse PDF
# coverage (some sport-season pairs only cover a single division), a
# trivially small overlap can hit 100% change and be reported as a
# reclassification — almost always spurious. Require at least N schools
# in both seasons before reporting.
MIN_SCHOOLS_FOR_EVENT = 30


@dataclass
class ReclassEvent:
    sport_id: int
    sport_name: str
    season_year: int          # the season WHERE the changes are observed
    prior_season: int
    n_schools_both_seasons: int
    n_changed: int
    change_fraction: float
    division_transitions: dict[str, int]   # "I -> IV": count, etc.
    threshold: float = DEFAULT_EVENT_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_reclass_events(
    teams_all_seasons: list[dict],
    sport_id: int,
    sport_name: str,
    threshold: float = DEFAULT_EVENT_THRESHOLD,
    min_schools: int = MIN_SCHOOLS_FOR_EVENT,
) -> list[ReclassEvent]:
    """teams_all_seasons: list of team dicts already filtered to this sport,
    each carrying school_id, season_year, division.

    Returns one ReclassEvent per (season, prior_season) pair where the
    fraction of schools that changed division exceeds threshold.
    """
    by_school: dict[int, dict[int, str | None]] = defaultdict(dict)
    for t in teams_all_seasons:
        if t.get("sport_id") != sport_id:
            continue
        sid = t.get("school_id")
        season = t.get("season_year")
        div = t.get("division")
        if sid is None or season is None:
            continue
        by_school[sid][int(season)] = div

    all_seasons = sorted({s for series in by_school.values() for s in series.keys()})
    events: list[ReclassEvent] = []
    for i, season in enumerate(all_seasons):
        if i == 0:
            continue
        prior_season = all_seasons[i - 1]
        n_both = 0
        n_changed = 0
        transitions: dict[str, int] = defaultdict(int)
        for sid, series in by_school.items():
            prior_div = series.get(prior_season)
            curr_div = series.get(season)
            if prior_div is None or curr_div is None:
                continue
            n_both += 1
            if prior_div != curr_div:
                n_changed += 1
                transitions[f"{prior_div} -> {curr_div}"] += 1
        if n_both < min_schools:
            continue
        frac = n_changed / n_both
        if frac >= threshold:
            events.append(
                ReclassEvent(
                    sport_id=sport_id,
                    sport_name=sport_name,
                    season_year=season,
                    prior_season=prior_season,
                    n_schools_both_seasons=n_both,
                    n_changed=n_changed,
                    change_fraction=round(frac, 4),
                    division_transitions=dict(sorted(transitions.items(), key=lambda kv: -kv[1])),
                    threshold=threshold,
                )
            )
    return events
