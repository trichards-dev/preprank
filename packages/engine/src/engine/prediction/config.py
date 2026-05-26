"""Feature-flag configuration for the PrepRank prediction layer.

The :class:`PredictionConfig` Pydantic model gates the prediction features
across two generations of the model:

- **v1 / Phase 2 features** (margin, recent_form, sos_depth, totals): legacy
  feature flags driving the additive-signal path in
  ``engine.validator.predictor.predict_game``. Default-constructed config
  reproduces engine behavior exactly (regression guarantee).
- **v2 / Phase 1+ model** (this generation): per-sport β-vector logistic
  regression fitted via max-likelihood on the train fold. Lives in
  ``engine.prediction.model.predict_game_v3``. Coefficients are stored in
  ``model_coefficients_by_sport``; recalibration outputs (Phase 6) in
  ``recalibration_params_by_sport``. Both are empty by default so that v2
  callers fall back to the v1 path when no coefficients are fitted.

See ``docs/model_specification.md`` for the v2 model's formal equation and
fitting protocol.
"""
from __future__ import annotations

from typing import Any

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

    # ------------------------------------------------------------------
    # DEPRECATED — v1 Phase-2 weight fields kept for regression safety.
    # New work (v2 Phase 1+) writes to ``model_coefficients_by_sport``
    # below. These v1 fields are NOT read by ``predict_game_v3``; they
    # remain in place so existing tests + the validator's
    # ``predict_game`` path stay green during the v1→v2 transition.
    # See docs/model_specification.md for the v2 model.
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # v2 Phase 1+ — per-sport β-vector coefficients and recalibration
    # parameters. Populated by ``engine.prediction.model.fit_sport``.
    # Read by ``engine.prediction.model.predict_game_v3``. Empty default
    # means v2 callers fall back to the v1 ``predict_game`` path
    # (regression guarantee).
    # ------------------------------------------------------------------

    model_coefficients_by_sport: dict[str, dict[str, float]] = Field(default_factory=dict)
    """Per-sport fitted logistic-regression β-vectors.

    Keys: sport name (e.g. ``"Football"``).
    Values: dict mapping coefficient name → fitted value. Expected keys
    per the v2 model spec (``docs/model_specification.md``):

    * ``beta_0`` — intercept
    * ``beta_1`` — Δrating slope
    * ``beta_2`` — HFA shift
    * ``beta_3`` — Δf_margin slope (Phase 4b log-compressed margin)
    * ``beta_4`` — Δf_offdef slope (Phase 4d Massey decomposition)
    * ``beta_5`` — Δf_pyc slope (Phase 4e prior-year carryover)
    * ``w_mercy`` — Phase 4c per-game training weight for mercy games
                   (NOT a logit coefficient; affects loss only)
    * ``beta_6`` — Phase 4f recent-form slope, IF Phase 4f lands as a
                  new logit term rather than an engine-rating tweak

    Any missing β key is treated as 0.0 by ``predict_game_v3``. Empty
    dict for a sport ⇒ fall back to legacy ``win_probability_v2``.
    """

    recalibration_params_by_sport: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Per-sport recalibration outputs from Phase 6.

    Keys: sport name.
    Values: dict with method-specific parameters. Expected shape:

    * ``method`` — ``"isotonic"`` (current default) or ``"platt"``
    * ``breakpoints`` — list[float] of x-coordinates (for isotonic)
    * ``values``      — list[float] of y-coordinates (for isotonic)
    * ``slope``       — float (for platt: a in σ(a·logit + b))
    * ``intercept``   — float (for platt)
    * ``trained_on_run_id`` — UUID of the walk-forward run whose train
                              fold produced these parameters

    Empty dict for a sport ⇒ no recalibration applied; ``predict_game_v3``
    returns the raw fitted-model probability. See
    ``docs/model_specification.md`` "Phase 6 recalibration gate" for
    the trigger condition (calibration slope ∉ [0.85, 1.15]).
    """

    @classmethod
    def baseline(cls) -> "PredictionConfig":
        """Explicit baseline config = current engine behavior."""
        return cls()
