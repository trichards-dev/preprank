"""Feature-flag configuration for the PrepRank prediction layer.

The :class:`PredictionConfig` Pydantic model gates the Phase-2 prediction
features. A default-constructed config reproduces the engine's legacy
behavior exactly (regression guarantee); each feature is opted into via
``enabled_features`` and parameterized by the matching field below.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PredictionConfig(BaseModel):
    """Feature-flag config for the prediction layer.

    Default constructor preserves current engine behavior exactly
    (regression guarantee). Each Phase-2 feature is opted into via
    ``enabled_features`` and parameterized via the matching field below.
    """

    enabled_features: list[str] = Field(default_factory=list)
    """Subset of {'margin', 'recent_form', 'hfa', 'sos_depth', 'totals'} - applied in this order."""

    # --- Logistic primitive parameters (currently hardcoded in win_probability.py) ---
    k_factor: float = 0.8
    """Logistic steepness; matches the legacy ``win_probability`` default."""

    home_advantage: float = 0.5
    """Global home-field advantage (rating-point units); legacy default."""

    # --- Phase 2c: per-sport HFA overrides ---
    home_advantage_by_sport: dict[str, float] = Field(default_factory=dict)
    """Per-sport HFA overrides. Empty default = use the global ``home_advantage`` above."""

    # --- Phase 2a: score margin caps per sport (anti-blowout) ---
    margin_cap_by_sport: dict[str, int] = Field(
        default_factory=lambda: {
            "Football": 35,
            "Boys Basketball": 25,
            "Girls Basketball": 25,
            "Baseball": 15,
            "Softball": 15,
            "Boys Soccer": 5,
            "Girls Soccer": 5,
            "Volleyball": 3,
        }
    )
    """Per-sport margin caps used when 'margin' is enabled to dampen blowouts."""

    margin_weight_by_sport: dict[str, float] = Field(default_factory=dict)
    """Per-sport weight (alpha) on the capped-margin signal. Empty = use margin_weight."""

    margin_weight: float = 0.0
    """Default weight on the capped-margin signal. 0.0 = feature disabled even if 'margin' in enabled_features."""

    # --- Phase 2b: recent form ---
    recent_form_window: int = 3
    """Window size: how many of a team's most-recent games count as 'recent'."""

    recent_form_weight: float = 1.5
    """Multiplicative weight applied to recent-window games when 'recent_form' is on."""

    form_weight_by_sport: dict[str, float] = Field(default_factory=dict)
    """Per-sport weight (alpha) on the recent-form signal."""

    form_weight: float = 0.0
    """Default weight on the recent-form signal. 0.0 = feature disabled."""

    # --- Phase 2d: strength-of-schedule depth ---
    sos_depth: int = 1
    """SOS recursion depth. LHSAA's own formula uses depth=1 (opponents' win pct only)."""

    sos_depth_weight_by_sport: dict[str, float] = Field(default_factory=dict)
    """Per-sport weight on the depth-2 SOS adjustment signal."""

    sos_depth_weight: float = 0.0
    """Default weight on the SOS depth signal. 0.0 = feature disabled."""

    # --- Phase 2e: scoring offense / scoring defense totals ---
    totals_weight_by_sport: dict[str, float] = Field(default_factory=dict)
    """Per-sport weight on the uncapped points-totals matchup signal
    (offense_strength - opponent_defense_weakness). Empty default = use
    ``totals_weight``."""

    totals_weight: float = 0.0
    """Default weight on the points-totals signal. 0.0 = feature disabled
    even if 'totals' is in ``enabled_features``."""

    @classmethod
    def baseline(cls) -> "PredictionConfig":
        """Explicit baseline config = current engine behavior."""
        return cls()
