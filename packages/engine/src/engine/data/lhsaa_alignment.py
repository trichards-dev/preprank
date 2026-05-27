"""LHSAA 2025-2026 alignment loader.

Reads the canonical per-sport participation lists from
``data/lhsaa/lhsaa_participation_by_sport_2025_26.json`` (placed by
Thomas from his consolidated LHSAA alignment data, Reese 2026-05-27).
Output is a structured per-sport list usable by the
B1.2b schools/teams bootstrap.

Per Reese 2026-05-27 B1.2a, PDF parsing is OUT OF SCOPE for this turn —
the xlsx/csv/json files Thomas provides ARE the source-of-truth ground
data. The parser for future LHSAA PDF refresh (e.g., 2026-2027
alignment) is a separate v1.1 task. See open-questions.md.

Expected schema (long-form JSON)
-------------------------------
``data/lhsaa/lhsaa_participation_by_sport_2025_26.json`` should
deserialize to a dict with this shape:

```
{
    "season": "2025-26",
    "source": "LHSAA 2025-2026 alignment, consolidated by Thomas",
    "participation": {
        "Football":           [{"school": "Acadiana", "city": "Lafayette", "classification": "5A"}, ...],
        "Volleyball":         [...],
        "Boys Basketball":    [...],
        "Girls Basketball":   [...],
        "Boys Soccer":        [...],
        "Girls Soccer":       [...],
        "Baseball":           [...],
        "Softball":           [...]
    }
}
```

Validation
----------
At load time, the loader validates that the per-sport count for each
of the 8 sports matches Thomas's verified totals. Mismatches raise
``LhsaaAlignmentValidationError`` — there's no recovery path because
the validation gate is the whole point of using xlsx-as-source-of-truth.
Verified totals (Reese 2026-05-27):
  Football 324  ·  Volleyball 284  ·  Boys Basketball 404
  Girls Basketball 410  ·  Boys Soccer 196  ·  Girls Soccer 189
  Baseball 375  ·  Softball 388

Total per sport check + total unique-schools check (~446) act as the
two-line ground-truth gate.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Ground-truth totals — Reese 2026-05-27 verified counts.
# These come from the consolidated LHSAA 2025-2026 alignment.
# ---------------------------------------------------------------------------
LHSAA_2025_26_VERIFIED_TOTALS: dict[str, int] = {
    "Football": 324,
    "Volleyball": 284,
    "Boys Basketball": 404,
    "Girls Basketball": 410,
    "Boys Soccer": 196,
    "Girls Soccer": 189,
    "Baseball": 375,
    "Softball": 388,
}

LHSAA_2025_26_VERIFIED_UNIQUE_SCHOOL_COUNT: int = 446
"""Total unique schools across all 8 sports per the LHSAA alignment."""


# Default file path — relative to repo root.
DEFAULT_PARTICIPATION_JSON_PATH = Path("data/lhsaa/lhsaa_participation_by_sport_2025_26.json")


class LhsaaAlignmentValidationError(RuntimeError):
    """Raised when the loaded alignment file doesn't match Thomas's
    verified ground-truth totals. There's no recovery — the file is
    authoritative; a mismatch means something is wrong upstream."""


class LhsaaAlignmentLoadError(RuntimeError):
    """Raised when the alignment file can't be read or parsed."""


def load_lhsaa_participation(
    path: Path | None = None,
    *,
    verified_totals: dict[str, int] = LHSAA_2025_26_VERIFIED_TOTALS,
    verified_unique_count: int | None = LHSAA_2025_26_VERIFIED_UNIQUE_SCHOOL_COUNT,
) -> dict[str, Any]:
    """Load + validate the LHSAA 2025-2026 participation JSON.

    Returns the deserialized dict with shape:
        { "season": ..., "source": ..., "participation": { sport: [...] } }

    Raises:
        LhsaaAlignmentLoadError: file missing, unreadable, or malformed
        LhsaaAlignmentValidationError: counts don't match verified totals

    The path defaults to ``DEFAULT_PARTICIPATION_JSON_PATH`` relative
    to wherever the loader is called from. Callers can pass an absolute
    path or override the verified totals (for testing).
    """
    p = path if path is not None else DEFAULT_PARTICIPATION_JSON_PATH

    if not p.exists():
        raise LhsaaAlignmentLoadError(
            f"LHSAA participation file not found at {p!s}. "
            f"This file must be placed by Thomas's consolidation pipeline. "
            f"See open-questions.md / decisions.md 2026-05-27."
        )

    try:
        with p.open() as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise LhsaaAlignmentLoadError(f"failed to parse {p!s}: {e}") from e

    if not isinstance(data, dict) or "participation" not in data:
        raise LhsaaAlignmentLoadError(
            f"{p!s} has unexpected shape: expected dict with 'participation' key"
        )

    participation = data["participation"]
    if not isinstance(participation, dict):
        raise LhsaaAlignmentLoadError(
            f"{p!s} participation field is not a dict"
        )

    # Validate per-sport totals
    errors = []
    for sport, expected_count in verified_totals.items():
        sport_list = participation.get(sport)
        if sport_list is None:
            errors.append(f"sport {sport!r} missing from participation map")
            continue
        if not isinstance(sport_list, list):
            errors.append(f"sport {sport!r} participation is not a list")
            continue
        actual_count = len(sport_list)
        if actual_count != expected_count:
            errors.append(
                f"sport {sport!r} count mismatch: file has {actual_count}, "
                f"verified total is {expected_count}"
            )
    if errors:
        raise LhsaaAlignmentValidationError(
            f"validation against verified totals failed:\n  - " + "\n  - ".join(errors)
        )

    # Validate unique-school count if requested
    if verified_unique_count is not None:
        all_schools: set[str] = set()
        for sport, sport_list in participation.items():
            for entry in sport_list:
                if isinstance(entry, dict):
                    name = entry.get("school") or entry.get("name") or ""
                    if name:
                        all_schools.add(name.strip().lower())
        actual_unique = len(all_schools)
        if actual_unique != verified_unique_count:
            # Don't raise here — unique-count is a softer check than per-sport
            # totals because the same school appearing under slightly different
            # names is plausible. Surface as a warning via the load result.
            data.setdefault("_validation_warnings", []).append(
                f"unique-school count mismatch: file has {actual_unique}, "
                f"verified is {verified_unique_count}. Likely name-spelling "
                f"variation; alias resolver should reconcile during ingest."
            )

    return data


def get_participation_for_sport(
    data: dict[str, Any], sport: str,
) -> list[dict[str, Any]]:
    """Convenience: pull the per-sport participation list.

    Returns the list of ``{school, city, classification}`` dicts for the
    requested sport, or empty list if not found.
    """
    return data.get("participation", {}).get(sport, [])


def list_sports(data: dict[str, Any]) -> list[str]:
    """Return the list of sport names in the participation data."""
    return list(data.get("participation", {}).keys())


def get_unique_schools_across_sports(data: dict[str, Any]) -> set[tuple[str, str]]:
    """Return the set of (normalized_school_name, classification) tuples
    that appear in ANY sport's participation list. Useful for the
    schools-table seed step in B1.2b ingest."""
    out: set[tuple[str, str]] = set()
    for _sport, sport_list in data.get("participation", {}).items():
        for entry in sport_list:
            if not isinstance(entry, dict):
                continue
            name = (entry.get("school") or entry.get("name") or "").strip().lower()
            classification = (entry.get("classification") or "").strip()
            if name:
                out.add((name, classification))
    return out
