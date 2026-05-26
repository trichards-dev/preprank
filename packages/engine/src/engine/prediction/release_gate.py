"""Code-level enforcement of the four TASK-3 output conditions.

Per ``claude-memory/apps/preprank/decisions.md`` 2026-05-26 "TASK 3
sign-off granted":

1. No external accuracy numbers until residual Football Cat 1 is closed.
2. No accuracy claims until Phase 6 recalibration is applied when the
   calibration slope is outside [0.85, 1.15] for the sport.
3. Marketing claims (Phase 7) rewritten for rigor positioning — prohibit
   "beats professional benchmarks" framing.
4. Competitive-game stratification (Q1/Q2/Q3/Q4 by abs(Δrating))
   computed before any Phase 7 work.

These rules used to live in prose. This module is the code-level
enforcement point: every Phase-7 emitter and every walk-forward run that
intends to publish externally MUST call
``assert_external_release_allowed`` before writing any artifact, and
``scan_for_prohibited_phrases`` before printing any text. The two
functions raise ``ReleaseGateError`` on violation — refusing to silently
let a partial / un-recalibrated / un-Cat1-closed number reach the public
side.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class ReleaseGateError(RuntimeError):
    """Raised when an external release would violate one of the four
    output conditions from the 2026-05-26 TASK-3 sign-off."""


# Prohibited phrases for Phase-7 marketing artifacts. Matched
# case-insensitively against full text. Each entry is a regex pattern
# (re.escape'd source for plain strings); add new entries when
# external-claim review surfaces another bad framing.
_PROHIBITED_PATTERNS: tuple[tuple[str, str], ...] = (
    # (pattern, human-readable label for the error message)
    (r"beats?\s+(?:the\s+)?professional\s+benchmarks?", "'beats professional benchmarks'"),
    (r"beats?\s+(?:the\s+)?pros", "'beats the pros'"),
    (r"more\s+accurate\s+than\s+(?:the\s+)?(?:NFL|NBA|MLB)", "'more accurate than [pro league]'"),
    (r"out[\s-]?perform(?:s|ed)?\s+(?:the\s+)?(?:NFL|NBA|MLB|professional)",
     "'outperforms [pro league/professional]'"),
)


@dataclass
class ReleaseMetadata:
    """The auditable facts about a per-sport prediction artifact.

    The Phase-7 emitter constructs one of these from the latest
    walk-forward run + the latest Cat 1 audit. The constructor MUST
    populate every field — defaults are intentionally pessimistic
    (False / 0.0) so an un-initialized metadata instance always fails
    the gate.

    Attributes
    ----------
    sport
        Sport label, e.g. ``"Football"``.
    config_label
        Walk-forward run label, e.g. ``"wf-baseline-v2-fitted"``.
    run_id
        UUID of the walk-forward run that produced the numbers.
    cat1_residual_closed
        True only when the latest Cat 1 audit for this sport shows the
        residual is either at-or-below the documented acceptable rate
        OR has been formally characterized in the limitations section.
    recalibration_applied
        True when Phase-6 isotonic / Platt recalibration parameters
        are present in ``PredictionConfig.recalibration_params_by_sport``
        for this sport AND were applied during the run.
    recalibration_required
        True when the un-recalibrated calibration slope on the train
        fold was outside [0.85, 1.15] — i.e., recalibration was
        triggered. When True, ``recalibration_applied`` must also be
        True; when False, recalibration is optional.
    stratification_computed
        True when the run computed per-sport Q1/Q2/Q3/Q4 stratification
        metrics. The Phase 7 generator can only quote quartile-specific
        numbers; aggregate-only numbers are prohibited unless this is
        True.
    """

    sport: str
    config_label: str
    run_id: str
    cat1_residual_closed: bool = False
    recalibration_applied: bool = False
    recalibration_required: bool = False
    stratification_computed: bool = False


def assert_external_release_allowed(metadata: ReleaseMetadata) -> None:
    """Raise ``ReleaseGateError`` if any of the four conditions is unmet.

    Conditions 1 and 4 are unconditional gates. Condition 2 is a
    conditional gate — recalibration is required only when the slope
    test triggered for this sport. Condition 3 is enforced separately
    by :func:`scan_for_prohibited_phrases` on the generated text.
    """
    failures: list[str] = []

    if not metadata.cat1_residual_closed:
        failures.append(
            f"(1) Residual Cat 1 not closed for {metadata.sport!r}. "
            "Either fix or formally characterize the diagnostic before publishing."
        )
    if metadata.recalibration_required and not metadata.recalibration_applied:
        failures.append(
            f"(2) Recalibration was triggered for {metadata.sport!r} (slope outside "
            "[0.85, 1.15]) but PredictionConfig.recalibration_params_by_sport is "
            "missing or empty for this sport. Fit isotonic on the train fold and "
            "store the params before publishing."
        )
    if not metadata.stratification_computed:
        failures.append(
            f"(4) Q1-Q4 stratification was not computed for {metadata.sport!r}. "
            "Phase 7 can only quote quartile-specific numbers; run "
            "engine.validator.stratify on this run first."
        )

    if failures:
        details = "\n  - ".join(failures)
        raise ReleaseGateError(
            f"External release blocked for "
            f"{metadata.sport!r} (run {metadata.run_id}):\n  - {details}"
        )


def scan_for_prohibited_phrases(text: str, *, source: str = "<unknown>") -> None:
    """Raise ``ReleaseGateError`` if ``text`` contains a prohibited phrase.

    Called by the Phase-7 marketing-claim generator on every artifact
    body before write. ``source`` is included in the error message so
    a generation pipeline can pinpoint which template / claim row
    triggered the gate.
    """
    hits: list[str] = []
    for pattern, label in _PROHIBITED_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(label)
    if hits:
        raise ReleaseGateError(
            f"Prohibited Phase-7 framing in {source}: {', '.join(hits)}. "
            "Replace with rigor positioning (walk-forward + FDR + competitive "
            "stratification + reliability disclosure)."
        )


def add_prohibited_pattern(pattern: str, label: str) -> None:
    """Test/runtime hook for extending the prohibited-phrase list.

    Use sparingly — production additions should be committed to the
    module's ``_PROHIBITED_PATTERNS`` tuple. This exists so tests can
    exercise the scan path without monkey-patching, and so a future
    Phase-7 review can register additional bad phrases at runtime
    without a code edit.
    """
    global _PROHIBITED_PATTERNS
    _PROHIBITED_PATTERNS = _PROHIBITED_PATTERNS + ((pattern, label),)
