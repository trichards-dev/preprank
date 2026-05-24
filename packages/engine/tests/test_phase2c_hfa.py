"""Tests for the Phase-2c per-sport home-field-advantage (HFA) wiring.

Coverage:
    - ``_build_config_for_label('phase-2c')`` loads ``home_advantage_by_sport``
      from ``fitted_params.json``.
    - The phase-2c config preserves the Phase-2a margin weights.
    - The phase-2a config is NOT contaminated by HFA entries written to
      ``fitted_params.json`` by the Phase-2c fit step (regression guard
      so prior runs stay numerically identical).
    - ``predict_game`` at the phase-2c config applies the per-sport HFA
      value, not the global ``home_advantage`` default of 0.5.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.prediction.config import PredictionConfig
from engine.validator import cli as validator_cli
from engine.validator.predictor import predict_game
from engine.win_probability import win_probability_v2


@pytest.fixture
def patched_fitted_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect both the module-level ``FITTED_PARAMS_PATH`` and the
    ``_load_fitted_params`` reader at a writable temp file.

    ``_load_fitted_params``'s ``path`` default is captured at function
    definition time, so patching only the module-level constant isn't
    enough — we wrap the loader so it always reads from our temp file.
    """
    target = tmp_path / "fitted_params.json"
    monkeypatch.setattr(validator_cli, "FITTED_PARAMS_PATH", target)

    real_load = validator_cli._load_fitted_params

    def _load(path: Path = target) -> dict:
        return real_load(path)

    monkeypatch.setattr(validator_cli, "_load_fitted_params", _load)
    return target


# ---------------------------------------------------------------------------
# _build_config_for_label('phase-2c')
# ---------------------------------------------------------------------------
def test_phase2c_config_loads_hfa_from_fitted_params(patched_fitted_params: Path):
    """phase-2c reads home_advantage_by_sport from fitted_params.json."""
    patched_fitted_params.write_text(
        json.dumps(
            {
                "margin_weight_by_sport": {"Football": 0.5},
                "home_advantage_by_sport": {
                    "Football": 2.0,
                    "Boys Basketball": 1.5,
                    "Baseball": -1.0,
                },
            }
        )
    )

    cfg = validator_cli._build_config_for_label("phase-2c")

    assert cfg.home_advantage_by_sport == {
        "Football": 2.0,
        "Boys Basketball": 1.5,
        "Baseball": -1.0,
    }


def test_phase2c_config_preserves_margin_weights(patched_fitted_params: Path):
    """phase-2c keeps margin enabled with the Phase-2a margin weights."""
    patched_fitted_params.write_text(
        json.dumps(
            {
                "margin_weight_by_sport": {
                    "Football": 0.5,
                    "Boys Basketball": 1.0,
                    "Baseball": 0.5,
                },
                "home_advantage_by_sport": {"Football": 2.0},
            }
        )
    )

    cfg = validator_cli._build_config_for_label("phase-2c")

    assert "margin" in cfg.enabled_features
    # recent_form was rejected in Phase 2b — must NOT be in phase-2c.
    assert "recent_form" not in cfg.enabled_features
    assert cfg.margin_weight_by_sport == {
        "Football": 0.5,
        "Boys Basketball": 1.0,
        "Baseball": 0.5,
    }


# ---------------------------------------------------------------------------
# Regression: prior phases unaffected by HFA fit
# ---------------------------------------------------------------------------
def test_phase2a_config_unaffected_by_hfa_fit(patched_fitted_params: Path):
    """phase-2a must keep home_advantage_by_sport={} even after a Phase-2c
    fit has written per-sport HFA values to fitted_params.json. Otherwise
    re-running the phase-2a validator after Phase 2c would silently change
    its baseline-comparable numbers."""
    patched_fitted_params.write_text(
        json.dumps(
            {
                "margin_weight_by_sport": {"Football": 0.5},
                "home_advantage_by_sport": {
                    "Football": 2.0,
                    "Boys Basketball": 1.5,
                },
            }
        )
    )

    cfg = validator_cli._build_config_for_label("phase-2a")

    assert cfg.home_advantage_by_sport == {}
    assert cfg.home_advantage == 0.5
    # Margin weights should still be loaded from the file.
    assert cfg.margin_weight_by_sport == {"Football": 0.5}


def test_baseline_config_unaffected_by_hfa_fit(patched_fitted_params: Path):
    """baseline must remain a default-everything config even after the
    Phase-2c fit step has populated fitted_params.json with HFA entries."""
    patched_fitted_params.write_text(
        json.dumps(
            {
                "margin_weight_by_sport": {"Football": 0.5},
                "home_advantage_by_sport": {"Football": 2.0},
            }
        )
    )

    cfg = validator_cli._build_config_for_label("baseline")

    assert cfg.home_advantage_by_sport == {}
    assert cfg.home_advantage == 0.5
    assert cfg.margin_weight_by_sport == {}
    assert cfg.enabled_features == []


# ---------------------------------------------------------------------------
# predict_game: phase-2c uses per-sport HFA, not the 0.5 default
# ---------------------------------------------------------------------------
def test_phase2c_predict_game_uses_per_sport_hfa(patched_fitted_params: Path):
    """At the phase-2c config, predict_game for Football must apply the
    Football HFA value rather than the global 0.5 default. We verify this
    by computing the expected probability with the per-sport HFA wired
    directly into win_probability_v2."""
    football_hfa = 2.0
    patched_fitted_params.write_text(
        json.dumps(
            {
                # Use a zero margin weight so the margin signal cannot
                # contribute and the HFA term is what the test actually
                # measures.
                "margin_weight_by_sport": {"Football": 0.0},
                "home_advantage_by_sport": {"Football": football_hfa},
            }
        )
    )

    cfg = validator_cli._build_config_for_label("phase-2c")

    # Equal ratings, zero margin signals -> the only thing shifting the
    # probability away from 0.5 is the HFA.
    got = predict_game(
        70.0, 70.0, "Football", cfg,
        home_margin_signal=0.0, away_margin_signal=0.0,
    )

    # Build the comparison via win_probability_v2 with the same per-sport HFA.
    expected_cfg = PredictionConfig(home_advantage_by_sport={"Football": football_hfa})
    expected = win_probability_v2(70.0, 70.0, expected_cfg, sport="Football")
    assert got == pytest.approx(expected, abs=1e-12)

    # And the default-HFA value (0.5) would give a *different* probability,
    # proving the per-sport override actually took effect.
    default_cfg = PredictionConfig()
    default_p = win_probability_v2(70.0, 70.0, default_cfg, sport="Football")
    assert got != pytest.approx(default_p, abs=1e-6)


def test_phase2c_predict_game_unknown_sport_falls_back_to_global_hfa(
    patched_fitted_params: Path,
):
    """A sport with no per-sport HFA entry should fall back to the global
    ``home_advantage`` (0.5), matching win_probability_v2's resolution rule."""
    patched_fitted_params.write_text(
        json.dumps(
            {
                "margin_weight_by_sport": {},
                "home_advantage_by_sport": {"Football": 2.0},
            }
        )
    )

    cfg = validator_cli._build_config_for_label("phase-2c")

    got = predict_game(70.0, 70.0, "Lacrosse", cfg)
    # 'Lacrosse' isn't in home_advantage_by_sport -> uses config.home_advantage (0.5).
    expected = win_probability_v2(70.0, 70.0, PredictionConfig(), sport="Lacrosse")
    assert got == pytest.approx(expected, abs=1e-12)
