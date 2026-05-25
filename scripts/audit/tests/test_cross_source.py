"""Cross-source check tests with a mocked parse_pdf + in-memory games table.

We don't pull a real PDF here — that's covered by the live audit run. These
tests verify the comparison logic: school-name fuzzy match, snapshot-date
filtering, and pass/warn/fail thresholding.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from datetime import date

import pytest

from scripts.audit import cross_source as cs


@dataclass
class _Row:
    school_name: str
    wins: int
    losses: int
    snapshot_date: date | None
    division: str = "I"
    select_status: str = ""
    season_year: int = 2025
    rank: int | None = 1
    power_rating: float = 0.0
    strength_factor: float | None = None


def _games(rows):
    """rows = [(home_id, away_id, hs, as_, date)] → game dicts."""
    return [
        {
            "id": i,
            "home_team_id": h,
            "away_team_id": a,
            "home_score": hs,
            "away_score": ascore,
            "status": "final",
            "is_out_of_state": False,
            "game_date": gd,
            "week_number": None,
        }
        for i, (h, a, hs, ascore, gd) in enumerate(rows)
    ]


def _patch_parse_pdf(monkeypatch, returned_rows):
    """Stub scripts.parse_lhsaa_pdf.parse_pdf to return the given rows."""
    mod = types.ModuleType("scripts.parse_lhsaa_pdf")
    mod.parse_pdf = lambda entry, force_firecrawl=False: returned_rows
    monkeypatch.setitem(sys.modules, "scripts.parse_lhsaa_pdf", mod)


def test_cross_source_pass_when_wl_matches(monkeypatch):
    pdf_rows = [_Row("West Monroe", wins=3, losses=1, snapshot_date=date(2025, 10, 1))]
    _patch_parse_pdf(monkeypatch, pdf_rows)
    # Team 10 = West Monroe. 3 wins + 1 loss by 2025-10-01.
    games = _games(
        [
            (10, 20, 28, 14, "2025-09-05"),  # West Monroe wins
            (20, 10, 7, 21, "2025-09-12"),   # West Monroe wins
            (10, 30, 14, 21, "2025-09-19"),  # West Monroe loses
            (30, 10, 0, 42, "2025-09-26"),   # West Monroe wins
            (10, 40, 0, 50, "2025-10-15"),   # AFTER snapshot — should NOT count
        ]
    )
    teams_for_sport_season = {
        10: {"school_id": 100, "division": "I"},
        20: {"school_id": 200, "division": "I"},
        30: {"school_id": 300, "division": "I"},
        40: {"school_id": 400, "division": "I"},
    }
    r = cs.check_0_7_cross_source(
        sport_id=1, sport_name="Football", season_year=2025,
        games=games,
        teams_for_sport_season=teams_for_sport_season,
        schools_by_name={"West Monroe": 100, "Hahnville": 200, "Slidell": 300, "Other": 400},
        pdf_index=[{"sport": "Football", "season_year": 2025, "url": "x", "snapshot": "10/1/2025"}],
    )
    assert r.status == "pass"
    assert r.metrics["n_exact"] == 1
    assert r.metrics["n_cat3_teams"] == 0


def test_cross_source_fail_on_definite_cat3(monkeypatch):
    """N_pdf == N_ours but W splits differ → guaranteed Cat 3 mismatch."""
    pdf_rows = [_Row("West Monroe", wins=1, losses=3, snapshot_date=None)]
    _patch_parse_pdf(monkeypatch, pdf_rows)
    # Our record: 3-1 (same total games, different W/L → guaranteed disagreement on 2)
    games = _games(
        [
            (10, 20, 28, 14, "2025-09-05"),
            (10, 30, 21, 0, "2025-09-12"),
            (10, 40, 35, 7, "2025-09-19"),
            (10, 50, 0, 21, "2025-09-26"),
        ]
    )
    teams_for_sport_season = {
        10: {"school_id": 100, "division": "I"},
        20: {"school_id": 200, "division": "I"},
        30: {"school_id": 300, "division": "I"},
        40: {"school_id": 400, "division": "I"},
        50: {"school_id": 500, "division": "I"},
    }
    r = cs.check_0_7_cross_source(
        sport_id=1, sport_name="Football", season_year=2025,
        games=games, teams_for_sport_season=teams_for_sport_season,
        schools_by_name={"West Monroe": 100, "X": 200, "Y": 300, "Z": 400, "Q": 500},
        pdf_index=[{"sport": "Football", "season_year": 2025, "url": "x"}],
    )
    assert r.status == "fail"
    assert r.metrics["n_cat3_teams"] == 1
    assert r.metrics["sum_cat3_definite_games"] == 2


def test_cross_source_info_when_no_pdf_for_sport_season(monkeypatch):
    _patch_parse_pdf(monkeypatch, [])
    r = cs.check_0_7_cross_source(
        sport_id=2, sport_name="Volleyball", season_year=2021,
        games=[], teams_for_sport_season={}, schools_by_name={},
        pdf_index=[{"sport": "Football", "season_year": 2025, "url": "x"}],
    )
    assert r.status == "info"
    assert r.metrics["n_pdfs"] == 0


def test_cross_source_skips_when_pdf_division_mismatches_our_team(monkeypatch):
    """Northlake-style false positive: PDF is Div III Select, our team is
    Div IV Non-Select. The check should not even compare them."""
    pdf_rows = [_Row("Northlake Christian", wins=9, losses=11,
                     snapshot_date=None, division="III", select_status="Select")]
    _patch_parse_pdf(monkeypatch, pdf_rows)
    games = _games([(10, 20, 60, 50, "2021-01-15")])
    teams_for_sport_season = {
        10: {"school_id": 100, "division": "IV", "select_status": "Non-Select"},
        20: {"school_id": 200, "division": "IV", "select_status": "Non-Select"},
    }
    r = cs.check_0_7_cross_source(
        sport_id=5, sport_name="Boys Basketball", season_year=2021,
        games=games, teams_for_sport_season=teams_for_sport_season,
        schools_by_name={"Northlake Christian": 100, "Other": 200},
        pdf_index=[{"sport": "Boys Basketball", "season_year": 2021, "url": "x",
                    "division": "III", "select_status": "Select", "snapshot": "Final"}],
    )
    # PDF row's div doesn't match our team's div → filtered out before compare.
    assert r.metrics["n_rows_div_select_filtered"] == 1
    assert r.metrics["n_rows_compared"] == 0
    assert r.status == "info"


def test_parse_snapshot_handles_week_and_date_forms():
    from scripts.audit.cross_source import parse_snapshot
    assert parse_snapshot("Week 10 Final") == (None, 10)
    assert parse_snapshot("Week 8") == (None, 8)
    sd, wc = parse_snapshot("2/9/2024")
    assert sd == date(2024, 2, 9) and wc is None
    assert parse_snapshot("Final") == (None, None)
    assert parse_snapshot(None) == (None, None)
    sd, wc = parse_snapshot("10/30/2023 Final")
    assert sd == date(2023, 10, 30) and wc is None


def test_cross_source_applies_week_cutoff_for_football(monkeypatch):
    """A 'Week 10 Final' PDF should cause our games past week 10 to be excluded."""
    pdf_rows = [_Row("West Monroe", wins=8, losses=2, snapshot_date=None)]
    _patch_parse_pdf(monkeypatch, pdf_rows)
    # Make 12 games: 8 wins + 2 losses in weeks 1-10, then 2 playoff losses in weeks 11-12.
    games = []
    for i, (h, a, hs, ascore, week) in enumerate([
        (10, 20, 28, 14, 1), (10, 30, 21, 7, 2), (10, 40, 35, 10, 3),
        (10, 50, 24, 17, 4), (10, 60, 31, 14, 5), (10, 70, 28, 21, 6),
        (10, 80, 14, 21, 7),  # loss
        (10, 90, 35, 14, 8), (10, 99, 21, 17, 9),
        (10, 98, 17, 24, 10),  # loss
        (10, 97, 7, 35, 11),   # playoff loss — should be excluded
        (10, 96, 14, 28, 12),  # playoff loss — should be excluded
    ]):
        games.append({
            "id": i, "home_team_id": h, "away_team_id": a,
            "home_score": hs, "away_score": ascore,
            "status": "final", "is_out_of_state": False,
            "game_date": f"2025-{8+week//4:02d}-01", "week_number": week,
        })
    teams_for_sport_season = {
        10: {"school_id": 100, "division": "I"},
        **{tid: {"school_id": 100 + tid, "division": "I"} for tid in (20, 30, 40, 50, 60, 70, 80, 90, 96, 97, 98, 99)},
    }
    r = cs.check_0_7_cross_source(
        sport_id=1, sport_name="Football", season_year=2025,
        games=games, teams_for_sport_season=teams_for_sport_season,
        schools_by_name={"West Monroe": 100, **{f"T{tid}": 100 + tid for tid in (20, 30, 40, 50, 60, 70, 80, 90, 96, 97, 98, 99)}},
        pdf_index=[{"sport": "Football", "season_year": 2025, "url": "x",
                    "division": "all", "select_status": "Select", "snapshot": "Week 10 Final"}],
    )
    assert r.metrics["n_exact"] == 1
    assert r.metrics["n_cat3_teams"] == 0
