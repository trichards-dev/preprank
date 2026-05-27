"""School name resolver — explicit aliases + fuzzy candidate enumeration.

Resolves canonical LHSAA school names against the DB ``schools`` table.
Used during ingest to avoid creating duplicate rows for the same school
under different spellings (the canonical LHSAA participation file may
list a school as "St. Helena College and Career Acad." while our DB has
it as "St. Helena College & Career Acad.").

Design — Reese 2026-05-27 B1.1 sign-off
---------------------------------------
- **Explicit alias table** is the primary resolution path. Entries are
  hand-curated against LHSAA 2025-2026 alignment ground truth + manual
  verification of fuzzy candidates. Each entry maps a normalized
  canonical name to an existing DB ``schools.id``.
- **Fuzzy matching is NOT used for automatic resolution**, only for
  candidate enumeration during data-hygiene work. The B0 diagnostic
  showed that fuzzy threshold 0.75 produces a high false-positive
  density on LHSAA-style school names — schools with similar
  surnames in different cities ("Ben Franklin" vs "Franklin",
  "David Thibodaux" vs "Thibodaux", "River Oaks" vs "Live Oak")
  cross-match at 0.75-0.85 ratios but are demonstrably different
  institutions. Auto-resolution on fuzzy matches would create false
  aliases. The ``list_fuzzy_candidates`` API exists for surfacing
  these candidates to a human reviewer, NOT for automatic linking.

Source verification — per Reese 2026-05-27 instruction
------------------------------------------------------
Of 6 fuzzy candidates ≥ 0.75 identified in the B0 1A-5A subset:
  1. Archbishop Chapelle (5A, Metairie) vs Archbishop Shaw (4A, Marrero)
     → FALSE POSITIVE. Distinct Catholic schools.
  2. Ben Franklin (4A, New Orleans) vs Franklin (2A, Franklin LA)
     → FALSE POSITIVE. Different schools, different cities.
  3. David Thibodaux (4A, Lafayette) vs Thibodaux (5A, Thibodaux)
     → FALSE POSITIVE. Two distinct LHSAA member schools.
  4. Mentorship Academy (3A, Baton Rouge) vs Helix Mentorship Academy
     (4A, Baton Rouge) → UNRESOLVED. May be related (rebrand/sister
     school) or distinct; needs LHSAA contact for confirmation. NOT
     auto-aliased. Listed as a manual-verification item.
  5. River Oaks (1A, Monroe) vs Live Oak (5A, Watson)
     → FALSE POSITIVE. Wildly different schools (1A rural vs 5A urban).
  6. St. Helena College and Career Acad. (2A, Greensburg) vs
     St. Helena College & Career Acad. (id=98, 3A) → TRUE ALIAS.
     Same school, "and" vs "&" spelling. Class diff (2A vs 3A) is a
     1-level shift, plausibly a between-season classification update.

So 1 of 6 fuzzy candidates is a confirmed alias. The table below has 1
entry. Future aliases land here only after similar verification.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher


# ---------------------------------------------------------------------------
# Explicit alias table — confirmed mappings only
# ---------------------------------------------------------------------------
# Maps NORMALIZED canonical LHSAA name → DB schools.id.
# Each entry carries an inline citation justifying the alias.
EXPLICIT_ALIASES: dict[str, int] = {
    # St. Helena College and Career Acad. (LHSAA 2025-26 canonical, 2A) →
    # St. Helena College & Career Acad. (DB id=98, classification 3A).
    # Same institution; canonical uses "and", DB uses "&"; class diff
    # is a 1-level seasonal shift consistent with LHSAA reclassifications.
    "st helena college and career acad": 98,
}


# Schools known to be NEAR-MATCHES but DEMONSTRABLY DIFFERENT.
# This is the explicit false-positive ledger — used to make the
# resolver's behavior auditable and to fail loudly if anyone ever tries
# to auto-resolve these. Maps normalized canonical name → reason text.
KNOWN_FALSE_POSITIVES: dict[str, str] = {
    "archbishop chapelle": "Distinct from Archbishop Shaw (different Catholic school, different city). Verified 2026-05-27.",
    "ben franklin": "Distinct from Franklin (Benjamin Franklin HS in New Orleans vs Franklin HS in Franklin LA).",
    "david thibodaux": "Distinct from Thibodaux (two separate LHSAA member schools).",
    "river oaks": "Distinct from Live Oak (different cities, 1A vs 5A).",
}


# Schools that need manual verification before being added to the alias
# table. Listed here for human review tracking. Not auto-resolved.
PENDING_MANUAL_VERIFICATION: dict[str, str] = {
    "mentorship academy": "Possibly related to Helix Mentorship Academy (same city, similar name). LHSAA contact needed to confirm same/distinct institution.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def normalize_name(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Matches the normalization used throughout the B0 diagnostic and
    canonical-vs-DB comparisons so aliases keyed here are consistent
    with elsewhere in the codebase.
    """
    s = (s or "").strip().lower()
    s = re.sub(r"[\.\,\'\#]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


# ---------------------------------------------------------------------------
# Resolution API
# ---------------------------------------------------------------------------
def resolve_school(
    canonical_name: str,
    db_schools: list[dict],
) -> dict | None:
    """Resolve a canonical LHSAA school name to an existing DB row.

    Resolution order:
    1. Explicit alias table lookup (by normalized canonical name).
    2. Exact normalized-name match against DB.
    3. Return None — do NOT auto-resolve via fuzzy matching.

    The explicit-only policy is intentional: B0 verification showed that
    fuzzy candidates at threshold ≥ 0.75 are dominantly false positives
    on LHSAA school names. Auto-resolving fuzzy matches would corrupt
    the schools table with bad aliases. Use ``list_fuzzy_candidates``
    for human-review enumeration instead.

    Returns the matched DB row dict, or None if no confident resolution.

    Parameters
    ----------
    canonical_name : str
        The school name from the canonical source (e.g., LHSAA roster).
    db_schools : list[dict]
        DB schools, each with at least ``id`` and ``name``. Typically
        from ``sb.table('schools').select('id, name, ...').execute().data``.
    """
    if not canonical_name:
        return None

    norm = normalize_name(canonical_name)

    # 1. Explicit alias table
    if norm in EXPLICIT_ALIASES:
        target_id = EXPLICIT_ALIASES[norm]
        for s in db_schools:
            if s.get("id") == target_id:
                return s
        # Explicit alias points to a missing id — surface as None and let
        # the caller decide whether to log/fail. Returning None here is
        # safer than raising, because callers may handle missing-DB-row
        # cases gracefully.
        return None

    # 2. Exact normalized match
    for s in db_schools:
        if normalize_name(s.get("name", "")) == norm:
            return s

    # 3. No auto-fuzzy. Caller should use list_fuzzy_candidates for review.
    return None


def list_fuzzy_candidates(
    canonical_name: str,
    db_schools: list[dict],
    *,
    threshold: float = 0.75,
    max_results: int = 5,
) -> list[dict]:
    """Enumerate fuzzy-match candidates for human review.

    Returns a list of ``{db_row, ratio}`` dicts sorted by ratio
    descending, restricted to candidates above ``threshold``. Includes
    a ``known_false_positive`` flag when the canonical name is in the
    KNOWN_FALSE_POSITIVES ledger, so reviewers don't re-investigate
    already-rejected pairs.

    This is the data-hygiene workflow tool, NOT the ingest path.
    """
    if not canonical_name:
        return []

    norm = normalize_name(canonical_name)
    out = []
    for s in db_schools:
        db_norm = normalize_name(s.get("name", ""))
        if not db_norm:
            continue
        if db_norm == norm:
            continue  # exact match handled by resolve_school
        ratio = SequenceMatcher(None, norm, db_norm).ratio()
        if ratio < threshold:
            continue
        out.append({
            "db_row": s,
            "db_name": s.get("name"),
            "db_id": s.get("id"),
            "ratio": float(ratio),
        })
    out.sort(key=lambda x: -x["ratio"])
    candidates = out[:max_results]

    # Annotate with false-positive flag
    is_known_fp = norm in KNOWN_FALSE_POSITIVES
    is_pending = norm in PENDING_MANUAL_VERIFICATION
    for c in candidates:
        c["canonical_known_false_positive"] = is_known_fp
        c["canonical_pending_verification"] = is_pending
        if is_known_fp:
            c["false_positive_reason"] = KNOWN_FALSE_POSITIVES[norm]
        if is_pending:
            c["pending_reason"] = PENDING_MANUAL_VERIFICATION[norm]
    return candidates


def is_known_false_positive(canonical_name: str) -> bool:
    """Quick check whether a canonical name is a known false-positive
    fuzzy-match pair."""
    return normalize_name(canonical_name) in KNOWN_FALSE_POSITIVES


def is_pending_verification(canonical_name: str) -> bool:
    """Quick check whether a canonical name is pending manual
    verification before being added to the alias table."""
    return normalize_name(canonical_name) in PENDING_MANUAL_VERIFICATION
