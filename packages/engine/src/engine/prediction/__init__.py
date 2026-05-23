"""Prediction layer for the PrepRank engine.

This package houses the Phase-2 prediction features (margin, recent form,
sport-specific home-field advantage, strength-of-schedule depth, and points
totals) along with the :class:`PredictionConfig` feature-flag object that
turns them on or off.

The default ``PredictionConfig()`` is a no-op: it preserves the legacy
engine behavior exactly so callers that don't opt into any features get
bit-for-bit identical results.
"""
from engine.prediction.config import PredictionConfig

__all__ = ["PredictionConfig"]
