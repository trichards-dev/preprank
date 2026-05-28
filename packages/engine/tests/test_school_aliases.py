"""Tests for the school name alias resolver.

Spec from Reese 2026-05-27 B1.1:
  - Known-alias resolution: explicit table entries return the DB row.
  - Fuzzy threshold respects the 0.75 floor (in list_fuzzy_candidates).
  - NO false positives on visually similar but distinct school names:
      * Woodlawn-BR vs Woodlawn-Shrev pattern (synthetic)
      * Ben Franklin vs Franklin (real)
      * David Thibodaux vs Thibodaux (real)
      * Archbishop Chapelle vs Archbishop Shaw (real)
      * River Oaks vs Live Oak (real)

The resolver does NOT auto-resolve via fuzzy match. It only resolves
via explicit alias table or exact normalized-name match. Fuzzy
candidates are enumerated separately for human review.
"""
from __future__ import annotations

import pytest

from engine.data.school_aliases import (
    EXPLICIT_ALIASES,
    KNOWN_FALSE_POSITIVES,
    PENDING_MANUAL_VERIFICATION,
    is_known_false_positive,
    is_pending_verification,
    list_fuzzy_candidates,
    normalize_name,
    resolve_school,
)


# ---------------------------------------------------------------------------
# normalize_name
# ---------------------------------------------------------------------------
def test_normalize_lowercases_and_strips_punctuation():
    assert normalize_name("St. Helena's") == "st helenas"
    assert normalize_name("  Mt. Hermon  ") == "mt hermon"
    assert normalize_name("McDonogh #35") == "mcdonogh 35"


def test_normalize_handles_none_and_empty():
    assert normalize_name(None) == ""
    assert normalize_name("") == ""


# ---------------------------------------------------------------------------
# Explicit alias resolution — the one confirmed true alias
# ---------------------------------------------------------------------------
def test_st_helena_ampersand_variant_resolves():
    """The canonical 'and' variant must resolve to the DB '&' row (id=98).
    This is the only confirmed 1A-5A Mech-1 case as of 2026-05-27."""
    db_schools = [
        {"id": 98, "name": "St. Helena College & Career Acad.", "classification": "3A"},
        {"id": 200, "name": "Some other school", "classification": "4A"},
    ]
    result = resolve_school("St. Helena College and Career Acad.", db_schools)
    assert result is not None
    assert result["id"] == 98


def test_explicit_alias_with_punctuation_variant_still_resolves():
    """Different punctuation in input still hits the alias because of
    normalization."""
    db_schools = [
        {"id": 98, "name": "St. Helena College & Career Acad.", "classification": "3A"},
    ]
    result = resolve_school("St Helena College and Career Acad", db_schools)
    assert result is not None
    assert result["id"] == 98


def test_explicit_alias_missing_target_returns_none():
    """If the alias points to a DB id that's not in db_schools (deleted/
    renamed), resolve_school returns None rather than raising."""
    db_schools = [{"id": 999, "name": "Some Other School"}]
    result = resolve_school("St. Helena College and Career Acad.", db_schools)
    assert result is None


# ---------------------------------------------------------------------------
# Exact normalized match (no alias needed)
# ---------------------------------------------------------------------------
def test_exact_normalized_match_resolves():
    db_schools = [{"id": 1, "name": "Lafayette", "classification": "5A"}]
    result = resolve_school("Lafayette", db_schools)
    assert result is not None
    assert result["id"] == 1


def test_exact_match_with_punctuation_difference_resolves():
    """'St. Amant' input matches 'St Amant' in DB after normalization."""
    db_schools = [{"id": 5, "name": "St Amant"}]
    result = resolve_school("St. Amant", db_schools)
    assert result is not None
    assert result["id"] == 5


# ---------------------------------------------------------------------------
# Unknown schools — return None, do NOT auto-fuzzy
# ---------------------------------------------------------------------------
def test_unknown_school_returns_none():
    db_schools = [{"id": 1, "name": "Lafayette"}, {"id": 2, "name": "Acadiana"}]
    result = resolve_school("Some Totally New School", db_schools)
    assert result is None


def test_empty_canonical_name_returns_none():
    assert resolve_school("", [{"id": 1, "name": "X"}]) is None
    assert resolve_school(None, [{"id": 1, "name": "X"}]) is None


# ---------------------------------------------------------------------------
# False-positive rejection — the core spec requirement
# ---------------------------------------------------------------------------
def test_ben_franklin_does_not_auto_resolve_to_franklin():
    """Ben Franklin HS (New Orleans, 4A) is NOT the same as Franklin HS
    (Franklin LA, 2A). Fuzzy ratio is ~0.80 but they're distinct schools.
    The resolver must return None."""
    db_schools = [
        {"id": 138, "name": "Franklin", "classification": "2A"},  # Franklin, LA
    ]
    result = resolve_school("Ben Franklin", db_schools)
    assert result is None
    # And the false-positive ledger documents why
    assert is_known_false_positive("Ben Franklin")


def test_david_thibodaux_does_not_auto_resolve_to_thibodaux():
    """David Thibodaux HS (Lafayette, 4A) is NOT the same as Thibodaux
    HS (Thibodaux, 5A). Both are LHSAA members."""
    db_schools = [
        {"id": 15, "name": "Thibodaux", "classification": "5A"},
    ]
    result = resolve_school("David Thibodaux", db_schools)
    assert result is None
    assert is_known_false_positive("David Thibodaux")


def test_archbishop_chapelle_does_not_auto_resolve_to_archbishop_shaw():
    """Two distinct Catholic schools."""
    db_schools = [
        {"id": 202, "name": "Archbishop Shaw", "classification": "4A"},
    ]
    result = resolve_school("Archbishop Chapelle", db_schools)
    assert result is None
    assert is_known_false_positive("Archbishop Chapelle")


def test_river_oaks_does_not_auto_resolve_to_live_oak():
    """River Oaks (Monroe, 1A) and Live Oak (Watson, 5A) share only the
    'oak' word fragment. Resolver must not bridge them."""
    db_schools = [
        {"id": 32, "name": "Live Oak", "classification": "5A"},
    ]
    result = resolve_school("River Oaks", db_schools)
    assert result is None
    assert is_known_false_positive("River Oaks")


# ---------------------------------------------------------------------------
# Same-surname-different-city pattern (synthetic, per Reese's spec)
# ---------------------------------------------------------------------------
def test_woodlawn_br_does_not_match_woodlawn_shrev_synthetic():
    """Synthetic Woodlawn pattern from Reese's spec: two LHSAA schools
    named Woodlawn in different cities (BR and Shreveport). Even though
    the names share the entire surname, they're distinct schools. The
    resolver returns None because there's no exact name match (BR /
    Shrev suffix differs) and no explicit alias."""
    db_schools = [
        {"id": 301, "name": "Woodlawn - B.R.", "classification": "5A"},
        {"id": 302, "name": "Woodlawn - Shrev.", "classification": "4A"},
    ]
    # Bare "Woodlawn" with no suffix - ambiguous, must NOT auto-resolve
    result = resolve_school("Woodlawn", db_schools)
    assert result is None


def test_woodlawn_br_canonical_resolves_via_exact_match():
    """When canonical name matches exactly (with the - B.R. suffix), it
    resolves to that specific DB row, NOT the Shreveport one."""
    db_schools = [
        {"id": 301, "name": "Woodlawn - B.R.", "classification": "5A"},
        {"id": 302, "name": "Woodlawn - Shrev.", "classification": "4A"},
    ]
    result = resolve_school("Woodlawn - B.R.", db_schools)
    assert result is not None
    assert result["id"] == 301
    # And the inverse
    result = resolve_school("Woodlawn - Shrev.", db_schools)
    assert result is not None
    assert result["id"] == 302


# ---------------------------------------------------------------------------
# Pending-verification cases — flagged for review, NOT auto-resolved
# ---------------------------------------------------------------------------
def test_cohen_college_prep_resolves_to_walter_l_cohen_post_verification():
    """Cohen College Prep (LHSAA canonical, 1A, NOLA) resolves to
    Walter L. Cohen (DB id=252) per the 2026-05-27 Investigation 1
    verification: school operates as 'Walter L. Cohen College Prep',
    canonical xlsx records 'Cohen College Prep', lhsaaonline records
    'Walter L. Cohen'."""
    db_schools = [
        {"id": 252, "name": "Walter L. Cohen", "classification": "3A"},
    ]
    result = resolve_school("Cohen College Prep", db_schools)
    assert result is not None
    assert result["id"] == 252


def test_mentorship_academy_resolves_to_helix_post_verification():
    """Mentorship Academy (LHSAA canonical, 3A, Baton Rouge) resolves to
    Helix Mentorship Academy (DB id=222) per the 2026-05-27 web-search +
    LHSAA directory verification: same school, rebranded over time
    (Mentorship Academy → Helix Mentorship STEAM/Maritime Academy)."""
    db_schools = [
        {"id": 222, "name": "Helix Mentorship Academy", "classification": "4A"},
    ]
    result = resolve_school("Mentorship Academy", db_schools)
    assert result is not None
    assert result["id"] == 222
    # No longer in PENDING_MANUAL_VERIFICATION after resolution
    assert not is_pending_verification("Mentorship Academy")


# ---------------------------------------------------------------------------
# list_fuzzy_candidates — surfaces for human review with false-positive flag
# ---------------------------------------------------------------------------
def test_list_fuzzy_candidates_respects_075_threshold():
    """list_fuzzy_candidates honors the 0.75 floor and sorts by ratio desc."""
    db_schools = [
        {"id": 1, "name": "St. Helena College & Career Acad.", "classification": "3A"},
        {"id": 2, "name": "Slidell"},
        {"id": 3, "name": "Westminster Christian"},
    ]
    candidates = list_fuzzy_candidates("St. Helena College and Career Acad.", db_schools)
    # Should surface St. Helena ampersand variant as the top candidate
    assert len(candidates) >= 1
    assert candidates[0]["db_id"] == 1
    assert candidates[0]["ratio"] >= 0.75


def test_list_fuzzy_candidates_below_075_returns_empty():
    db_schools = [{"id": 1, "name": "Acadiana"}, {"id": 2, "name": "Bossier"}]
    # Completely unrelated name should produce no candidates above 0.75
    candidates = list_fuzzy_candidates("Totally Unrelated High School", db_schools)
    assert candidates == []


def test_list_fuzzy_candidates_flags_known_false_positives():
    """When the canonical input is a known FP, candidates are annotated
    so a human reviewer doesn't re-investigate."""
    db_schools = [
        {"id": 138, "name": "Franklin", "classification": "2A"},
    ]
    candidates = list_fuzzy_candidates("Ben Franklin", db_schools)
    assert len(candidates) >= 1
    assert candidates[0]["canonical_known_false_positive"] is True
    assert "Verified" in candidates[0]["false_positive_reason"] or "Distinct" in candidates[0]["false_positive_reason"]


def test_list_fuzzy_candidates_pending_verification_dict_is_empty_after_mentorship_resolved():
    """After Mentorship Academy was resolved 2026-05-27, the
    PENDING_MANUAL_VERIFICATION dict is empty. The pending-flag
    plumbing is still tested at the unit level (it just has no live
    cases to surface today). This test documents that state."""
    from engine.data.school_aliases import PENDING_MANUAL_VERIFICATION
    assert PENDING_MANUAL_VERIFICATION == {}


# ---------------------------------------------------------------------------
# Internal-consistency invariants
# ---------------------------------------------------------------------------
def test_no_alias_target_appears_in_false_positives():
    """Sanity: nothing in EXPLICIT_ALIASES should be marked as a false
    positive — they're mutually exclusive categories."""
    for canonical_norm in EXPLICIT_ALIASES:
        assert canonical_norm not in KNOWN_FALSE_POSITIVES, canonical_norm
        assert canonical_norm not in PENDING_MANUAL_VERIFICATION, canonical_norm


def test_st_helena_in_explicit_alias_table():
    """Sanity: confirmed alias is in the table."""
    assert "st helena college and career acad" in EXPLICIT_ALIASES
    assert EXPLICIT_ALIASES["st helena college and career acad"] == 98
