"""Calibration-layer utilities for the forecast API.

Per `confidence_disclosure_ux_options_2026-05-29.md` (memory) and the
locked forecast-api design 2026-05-29, this package houses:

- `source_caveats`: sport-keyed source-data caveat enum (Baseball at v1.0)
- `forecast`: per-game forecast computation (CI, tier label, premium fields)
- `reliability_table`: load + lookup the per-decile reliability table the
  forecast endpoint consumes

These modules are PURE computation: no DB, no HTTP, no auth. The
forecast API router (`apps/api/app/routers/forecast.py`) wires them
to the request layer.
"""
