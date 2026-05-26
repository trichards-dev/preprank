"""Tests for ``engine.prediction.release_gate`` — code-level enforcement
of the four TASK-3 output conditions from 2026-05-26."""
from __future__ import annotations

import pytest

from engine.prediction.release_gate import (
    ReleaseGateError,
    ReleaseMetadata,
    _PROHIBITED_PATTERNS,
    add_prohibited_pattern,
    assert_external_release_allowed,
    scan_for_prohibited_phrases,
)


# ---------------------------------------------------------------------------
# Condition 1: Cat 1 residual closed
# ---------------------------------------------------------------------------


def test_gate_blocks_when_cat1_not_closed():
    metadata = ReleaseMetadata(
        sport="Football",
        config_label="wf-baseline-v2-fitted",
        run_id="abc-123",
        cat1_residual_closed=False,
        recalibration_applied=True,
        recalibration_required=False,
        stratification_computed=True,
    )
    with pytest.raises(ReleaseGateError, match=r"\(1\) Residual Cat 1 not closed"):
        assert_external_release_allowed(metadata)


# ---------------------------------------------------------------------------
# Condition 2: Recalibration gate (conditional)
# ---------------------------------------------------------------------------


def test_gate_blocks_when_recalibration_required_but_not_applied():
    metadata = ReleaseMetadata(
        sport="Football",
        config_label="wf-baseline-v2-fitted",
        run_id="abc-123",
        cat1_residual_closed=True,
        recalibration_required=True,
        recalibration_applied=False,
        stratification_computed=True,
    )
    with pytest.raises(ReleaseGateError, match=r"\(2\) Recalibration was triggered"):
        assert_external_release_allowed(metadata)


def test_gate_passes_when_recalibration_required_and_applied():
    metadata = ReleaseMetadata(
        sport="Football",
        config_label="wf-baseline-v2-fitted",
        run_id="abc-123",
        cat1_residual_closed=True,
        recalibration_required=True,
        recalibration_applied=True,
        stratification_computed=True,
    )
    assert_external_release_allowed(metadata)  # no raise


def test_gate_passes_when_recalibration_not_required():
    """When the slope test doesn't trigger, recalibration_applied is irrelevant."""
    metadata = ReleaseMetadata(
        sport="Volleyball",
        config_label="wf-baseline-v2-fitted",
        run_id="abc-123",
        cat1_residual_closed=True,
        recalibration_required=False,
        recalibration_applied=False,
        stratification_computed=True,
    )
    assert_external_release_allowed(metadata)


# ---------------------------------------------------------------------------
# Condition 4: Q1-Q4 stratification
# ---------------------------------------------------------------------------


def test_gate_blocks_when_stratification_not_computed():
    metadata = ReleaseMetadata(
        sport="Football",
        config_label="wf-baseline-v2-fitted",
        run_id="abc-123",
        cat1_residual_closed=True,
        recalibration_applied=True,
        recalibration_required=False,
        stratification_computed=False,
    )
    with pytest.raises(ReleaseGateError, match=r"\(4\) Q1-Q4 stratification"):
        assert_external_release_allowed(metadata)


# ---------------------------------------------------------------------------
# Multiple failures surface together
# ---------------------------------------------------------------------------


def test_gate_aggregates_multiple_failures():
    metadata = ReleaseMetadata(
        sport="Football",
        config_label="wf-baseline-v2-fitted",
        run_id="abc-123",
        cat1_residual_closed=False,
        recalibration_required=True,
        recalibration_applied=False,
        stratification_computed=False,
    )
    with pytest.raises(ReleaseGateError) as exc_info:
        assert_external_release_allowed(metadata)
    message = str(exc_info.value)
    assert "(1)" in message
    assert "(2)" in message
    assert "(4)" in message


# ---------------------------------------------------------------------------
# Defaults are pessimistic
# ---------------------------------------------------------------------------


def test_default_metadata_fails_the_gate():
    """An un-initialized ReleaseMetadata must NOT silently pass."""
    metadata = ReleaseMetadata(sport="X", config_label="y", run_id="z")
    with pytest.raises(ReleaseGateError):
        assert_external_release_allowed(metadata)


# ---------------------------------------------------------------------------
# Condition 3: Prohibited phrases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Our model beats professional benchmarks across all sports.",
        "Our predictions beat the pros.",
        "BEATS PROFESSIONAL BENCHMARKS",  # case-insensitive
        "Our football model is more accurate than the NFL prediction industry.",
        "We outperform the NBA's official models.",
    ],
)
def test_prohibited_phrases_detected(text):
    with pytest.raises(ReleaseGateError, match="Prohibited Phase-7 framing"):
        scan_for_prohibited_phrases(text, source="test")


def test_acceptable_phrases_pass():
    rigor_text = (
        "Walk-forward validation on the 2025 holdout shows 70.5% game-winner "
        "accuracy with a 95% bootstrap CI of [68.9%, 72.0%]. FDR-corrected "
        "across the 8-sport phase sweep. Reliability plots per Q1-Q4 quartile "
        "are disclosed in the methodology appendix."
    )
    scan_for_prohibited_phrases(rigor_text, source="marketing/claims_v2.md")


def test_pro_benchmarks_as_context_acceptable():
    """Citing pro benchmarks as context (not as a 'we beat them' claim) is OK."""
    text = (
        "For context, professional benchmarks for game-winner accuracy: "
        "NFL 68.6%, MLB 57.1%, NBA tournament 72%, club soccer 61.6%. "
        "High-school football, with shorter seasons and higher roster turnover, "
        "operates in a different statistical regime."
    )
    scan_for_prohibited_phrases(text, source="marketing/claims_v2.md")


# ---------------------------------------------------------------------------
# Runtime extensibility
# ---------------------------------------------------------------------------


def test_add_prohibited_pattern_extends_scan():
    original_len = len(_PROHIBITED_PATTERNS)
    try:
        add_prohibited_pattern(r"world['’]s most accurate", "'world's most accurate'")
        with pytest.raises(ReleaseGateError):
            scan_for_prohibited_phrases("PrepRank is the world's most accurate.")
    finally:
        # Restore module state so other tests aren't affected by the addition
        import engine.prediction.release_gate as gate

        gate._PROHIBITED_PATTERNS = gate._PROHIBITED_PATTERNS[:original_len]
