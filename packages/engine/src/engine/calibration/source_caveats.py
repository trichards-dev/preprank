"""Sport-keyed source-data caveat enum for the forecast API.

Per Specification 1a (UX options doc 2026-05-29): when a sport has a
known source-data quality issue independent of model calibration,
surface a small caveat alongside the per-game forecast. The CI
captures calibration uncertainty; the caveat captures source-side
margin issues that wider CIs would NOT fully repair.

At v1.0, only Baseball has a caveat. The LHSAA source records
Baseball games as "winner_runs - 0" with winner_runs varying across
perspective pages (e.g., Parkview 8-0 on its 3A page vs Opelousas
5-0 on its 1A page for the same game, MaxPreps truth 8-5). Engine
parser is correct; the source convention is the issue. See open
task #92.

Drift test: only Baseball returns a non-None caveat; all 7 other
sports return None.

This module is pure data — no I/O, no compute. The API router
imports SOURCE_CAVEATS at request time and threads it into the
response.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceCaveat:
    """Sport-keyed source-data caveat for forecast API responses.

    The enum-style ``code`` is for programmatic UI mapping; ``prose``
    is the user-facing string.
    """

    code: str
    prose: str


SOURCE_CAVEATS: dict[str, SourceCaveat] = {
    "Baseball": SourceCaveat(
        code="baseball_winner_first_recording",
        prose=(
            "Margin estimates for Baseball games carry additional "
            "uncertainty due to LHSAA source-page recording conventions."
        ),
    ),
}


def get_source_caveat(sport_name: str) -> SourceCaveat | None:
    """Return the caveat for a sport, or None if no caveat applies.

    Sport name is matched case-sensitively against the canonical
    sport-name list used by `engine.validator.data.ALL_SPORTS`.
    """
    return SOURCE_CAVEATS.get(sport_name)
