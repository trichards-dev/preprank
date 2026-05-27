"""Tests for the LHSAA 2025-2026 alignment loader.

Per Reese 2026-05-27 B1.2a: real data lands at
``data/lhsaa/lhsaa_participation_by_sport_2025_26.json``. These tests
use synthetic JSON fixtures with the verified totals (or with seeded
violations) to validate the loader's behavior. When the real file
lands, an integration test that loads it can be added; the unit-level
contract is exercised here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.data.lhsaa_alignment import (
    LHSAA_2025_26_VERIFIED_TOTALS,
    LHSAA_2025_26_VERIFIED_UNIQUE_SCHOOL_COUNT,
    LhsaaAlignmentLoadError,
    LhsaaAlignmentValidationError,
    get_participation_for_sport,
    get_unique_schools_across_sports,
    list_sports,
    load_lhsaa_participation,
)


def _synthetic_participation(
    *,
    counts: dict[str, int] | None = None,
    unique_school_count: int | None = None,
) -> dict:
    """Build a synthetic participation dict that matches Thomas's verified
    totals (or override with ``counts`` for mismatch tests).

    Generates N unique fake school names per sport; if ``unique_school_count``
    is given, ensures the union across sports has exactly that many.
    Used for unit tests only.
    """
    counts = counts if counts is not None else LHSAA_2025_26_VERIFIED_TOTALS
    if unique_school_count is None:
        unique_school_count = sum(counts.values())  # worst case: all distinct

    # Generate a flat pool of school names; reuse across sports by indexing.
    school_pool = [
        {"school": f"School_{i:03d}", "city": "Baton Rouge", "classification": "3A"}
        for i in range(unique_school_count)
    ]
    participation = {}
    for sport, n in counts.items():
        # Cycle through pool; for the 'verified totals' case, each sport gets
        # the first N entries — overlap across sports comes from index cycling.
        participation[sport] = [school_pool[i % len(school_pool)] for i in range(n)]
    return {
        "season": "2025-26",
        "source": "synthetic test fixture",
        "participation": participation,
    }


# ---------------------------------------------------------------------------
# Load happy path — verified totals match
# ---------------------------------------------------------------------------
def test_load_happy_path_with_verified_totals(tmp_path: Path):
    fixture = _synthetic_participation()
    fp = tmp_path / "alignment.json"
    fp.write_text(json.dumps(fixture))
    data = load_lhsaa_participation(
        fp, verified_unique_count=None  # disable unique-count check for this happy path
    )
    assert data["season"] == "2025-26"
    assert "participation" in data
    assert set(data["participation"].keys()) == set(LHSAA_2025_26_VERIFIED_TOTALS.keys())


# ---------------------------------------------------------------------------
# Validation: per-sport count mismatch must raise
# ---------------------------------------------------------------------------
def test_validation_raises_on_sport_count_mismatch(tmp_path: Path):
    bad_counts = dict(LHSAA_2025_26_VERIFIED_TOTALS)
    bad_counts["Football"] = 100  # wrong
    fixture = _synthetic_participation(counts=bad_counts)
    fp = tmp_path / "bad.json"
    fp.write_text(json.dumps(fixture))
    with pytest.raises(LhsaaAlignmentValidationError) as exc:
        load_lhsaa_participation(fp, verified_unique_count=None)
    assert "Football" in str(exc.value)
    assert "100" in str(exc.value)
    assert "324" in str(exc.value)


def test_validation_raises_on_missing_sport(tmp_path: Path):
    fixture = _synthetic_participation()
    del fixture["participation"]["Football"]
    fp = tmp_path / "missing_fb.json"
    fp.write_text(json.dumps(fixture))
    with pytest.raises(LhsaaAlignmentValidationError) as exc:
        load_lhsaa_participation(fp, verified_unique_count=None)
    assert "Football" in str(exc.value)


def test_validation_collects_all_errors(tmp_path: Path):
    """Multiple per-sport mismatches should all surface in one error."""
    bad_counts = dict(LHSAA_2025_26_VERIFIED_TOTALS)
    bad_counts["Football"] = 1
    bad_counts["Volleyball"] = 2
    fixture = _synthetic_participation(counts=bad_counts)
    fp = tmp_path / "bad.json"
    fp.write_text(json.dumps(fixture))
    with pytest.raises(LhsaaAlignmentValidationError) as exc:
        load_lhsaa_participation(fp, verified_unique_count=None)
    msg = str(exc.value)
    assert "Football" in msg
    assert "Volleyball" in msg


# ---------------------------------------------------------------------------
# Load errors: file not found, malformed JSON, unexpected shape
# ---------------------------------------------------------------------------
def test_load_file_not_found_raises(tmp_path: Path):
    missing = tmp_path / "nope.json"
    with pytest.raises(LhsaaAlignmentLoadError) as exc:
        load_lhsaa_participation(missing)
    assert "not found" in str(exc.value).lower()


def test_load_malformed_json_raises(tmp_path: Path):
    fp = tmp_path / "broken.json"
    fp.write_text("{not valid json")
    with pytest.raises(LhsaaAlignmentLoadError) as exc:
        load_lhsaa_participation(fp)
    assert "parse" in str(exc.value).lower() or "json" in str(exc.value).lower()


def test_load_wrong_shape_raises(tmp_path: Path):
    fp = tmp_path / "wrong_shape.json"
    fp.write_text(json.dumps({"some_other_top_level_key": []}))
    with pytest.raises(LhsaaAlignmentLoadError) as exc:
        load_lhsaa_participation(fp)
    assert "participation" in str(exc.value)


def test_load_participation_not_dict_raises(tmp_path: Path):
    fp = tmp_path / "participation_not_dict.json"
    fp.write_text(json.dumps({"participation": ["not a dict"]}))
    with pytest.raises(LhsaaAlignmentLoadError) as exc:
        load_lhsaa_participation(fp)
    assert "not a dict" in str(exc.value)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------
def test_get_participation_for_sport():
    data = _synthetic_participation()
    fb = get_participation_for_sport(data, "Football")
    assert len(fb) == LHSAA_2025_26_VERIFIED_TOTALS["Football"]
    assert get_participation_for_sport(data, "Cricket") == []


def test_list_sports_returns_all_8():
    data = _synthetic_participation()
    sports = list_sports(data)
    assert set(sports) == set(LHSAA_2025_26_VERIFIED_TOTALS.keys())
    assert len(sports) == 8


def test_get_unique_schools_across_sports():
    """The unique-schools set deduplicates across sports."""
    data = {
        "participation": {
            "Football": [{"school": "Alpha", "classification": "5A"},
                         {"school": "Beta", "classification": "4A"}],
            "Volleyball": [{"school": "Alpha", "classification": "5A"},
                            {"school": "Gamma", "classification": "3A"}],
        }
    }
    uniq = get_unique_schools_across_sports(data)
    assert ("alpha", "5A") in uniq
    assert ("beta", "4A") in uniq
    assert ("gamma", "3A") in uniq
    assert len(uniq) == 3


# ---------------------------------------------------------------------------
# Verified-totals constants sanity
# ---------------------------------------------------------------------------
def test_verified_totals_match_reese_published_numbers():
    """Sanity check on the LHSAA_2025_26_VERIFIED_TOTALS constant."""
    expected = {
        "Football": 324, "Volleyball": 284,
        "Boys Basketball": 404, "Girls Basketball": 410,
        "Boys Soccer": 196, "Girls Soccer": 189,
        "Baseball": 375, "Softball": 388,
    }
    assert LHSAA_2025_26_VERIFIED_TOTALS == expected
    assert LHSAA_2025_26_VERIFIED_UNIQUE_SCHOOL_COUNT == 446
