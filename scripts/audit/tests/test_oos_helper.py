"""Tests for the OOS helper used by both ingest scripts."""
from __future__ import annotations

from scripts.oos_helper import detect_oos_state, get_or_create_oos_school


def test_detect_oos_state_recognizes_state_suffix():
    # Dash separator (sports schedules)
    assert detect_oos_state("Alto - TX") == "TX"
    assert detect_oos_state("Madison Central - MS") == "MS"
    assert detect_oos_state("Belen Jesuit - FL") == "FL"
    assert detect_oos_state("Hot Springs - AR") == "AR"
    # Comma separator (football schedules)
    assert detect_oos_state("Dallas Christian School, TX") == "TX"
    assert detect_oos_state("Drew Central, AR") == "AR"
    assert detect_oos_state("Germantown High School, MS") == "MS"
    # Parenthesized city
    assert detect_oos_state("KIPP Northeast (Houston, TX)") == "TX"
    assert detect_oos_state("Holy Cross San Antonio, TX") == "TX"


def test_detect_oos_state_skips_louisiana():
    # "School - LA" suffix shouldn't trigger OOS treatment
    assert detect_oos_state("Some School - LA") is None


def test_detect_oos_state_skips_non_state_suffixes():
    assert detect_oos_state("Acadiana Renaissance Charter") is None
    assert detect_oos_state("Anacoco") is None
    assert detect_oos_state("Bolton-Closed") is None
    assert detect_oos_state("School - XX") is None  # XX not a real state
    assert detect_oos_state("") is None
    assert detect_oos_state(None) is None


def test_get_or_create_oos_school_uses_cache():
    """Same opp_name in same run -> same school_id without re-querying DB."""
    cache: dict[str, int] = {"Alto - TX": 9999}
    # The mock sb is irrelevant when cache hits.
    sid = get_or_create_oos_school(None, "Alto - TX", "TX", cache)
    assert sid == 9999


def test_get_or_create_oos_school_dry_run():
    cache: dict[str, int] = {}
    sid = get_or_create_oos_school(None, "Alto - TX", "TX", cache, dry_run=True)
    assert sid is None
    assert cache == {}  # nothing cached in dry-run mode either
