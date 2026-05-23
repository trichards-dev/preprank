"""Compare two prior validator runs and write a diff report.

Loads the most-recent ``game_predictions`` rows for each ``config_label``
(or for explicit ``run_id`` values), recomputes per-sport
game-winner-accuracy + Brier on the **paired** game set (games predicted
under both configs), and bootstraps a CI on the per-game accuracy
*difference*.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .data import load_sports_map, load_teams_with_schools
from .metrics import bootstrap_ci
from .report import _json_default


@dataclass
class _PerGameJoinRow:
    sport: str
    game_id: int
    p_a: float        # home_win_probability under config A
    p_b: float        # under config B
    actual_home_won: bool


def diff(
    config_a: str,
    config_b: str,
    output_dir: Path | str = "reports",
    *,
    run_id_a: str | None = None,
    run_id_b: str | None = None,
    n_bootstrap: int = 1000,
    seed: int = 42,
    supabase_client: Any | None = None,
    supabase_client_factory: Callable[[], Any] | None = None,
) -> dict:
    """Diff two validator runs by config label (default: latest of each).

    Writes ``diff_<a>_vs_<b>.json`` and ``.md`` under ``output_dir/_diffs/``.
    Returns the structured diff dict.
    """
    if supabase_client is None:
        if supabase_client_factory is None:
            supabase_client_factory = _default_factory
        supabase_client = supabase_client_factory()
    sb = supabase_client

    rid_a = run_id_a or _latest_run_id(sb, config_a)
    rid_b = run_id_b or _latest_run_id(sb, config_b)
    if not rid_a or not rid_b:
        raise RuntimeError(
            f"Could not resolve run_ids for ({config_a}, {config_b}); "
            f"got ({rid_a}, {rid_b}). Has a run been written?"
        )

    rows_a = _load_predictions(sb, rid_a)
    rows_b = _load_predictions(sb, rid_b)

    # Join on game_id and pair to sport / actual outcome.
    rows_a_by_game = {r["game_id"]: r for r in rows_a}
    rows_b_by_game = {r["game_id"]: r for r in rows_b}
    common_game_ids = set(rows_a_by_game.keys()) & set(rows_b_by_game.keys())

    games_by_id = _load_games_by_id(sb, list(common_game_ids))
    sports_map = load_sports_map(sb)
    teams = load_teams_with_schools(sb)
    team_to_sport = {tid: sports_map.get(t.get("sport_id"), "?") for tid, t in teams.items()}

    joined: list[_PerGameJoinRow] = []
    for gid in common_game_ids:
        g = games_by_id.get(gid)
        if g is None:
            continue
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs is None or as_ is None:
            continue
        sport = team_to_sport.get(g.get("home_team_id"), "?")
        joined.append(_PerGameJoinRow(
            sport=sport,
            game_id=gid,
            p_a=float(rows_a_by_game[gid]["home_win_probability"]),
            p_b=float(rows_b_by_game[gid]["home_win_probability"]),
            actual_home_won=bool(hs > as_),
        ))

    by_sport: dict[str, list[_PerGameJoinRow]] = defaultdict(list)
    for r in joined:
        by_sport[r.sport].append(r)

    out_sports: dict[str, dict] = {}
    for sport, rows in by_sport.items():
        out_sports[sport] = _per_sport_diff(rows, n_bootstrap=n_bootstrap, seed=seed)

    overall = _per_sport_diff(joined, n_bootstrap=n_bootstrap, seed=seed) if joined else {}

    payload = {
        "config_a": config_a, "run_id_a": rid_a,
        "config_b": config_b, "run_id_b": rid_b,
        "paired_games": len(joined),
        "sports": out_sports,
        "overall": overall,
    }

    diff_dir = Path(output_dir) / "_diffs"
    diff_dir.mkdir(parents=True, exist_ok=True)
    json_path = diff_dir / f"diff_{config_a}_vs_{config_b}.json"
    md_path = diff_dir / f"diff_{config_a}_vs_{config_b}.md"
    json_path.write_text(
        json.dumps(payload, indent=2, default=_json_default),
        encoding="utf-8",
    )
    _write_diff_markdown(md_path, payload)
    payload["_output_dir"] = str(diff_dir)
    return payload


def _per_sport_diff(rows: list[_PerGameJoinRow], n_bootstrap: int, seed: int) -> dict:
    """Compute paired accuracy + brier deltas and bootstrap CI on the delta."""
    if not rows:
        return {"n": 0}
    acc_a = _acc(rows, "p_a")
    acc_b = _acc(rows, "p_b")
    bri_a = _brier(rows, "p_a")
    bri_b = _brier(rows, "p_b")

    def acc_diff(sample: list[_PerGameJoinRow]) -> float:
        return _acc(sample, "p_b") - _acc(sample, "p_a")

    def bri_diff(sample: list[_PerGameJoinRow]) -> float:
        return _brier(sample, "p_b") - _brier(sample, "p_a")

    acc_lo, acc_hi = bootstrap_ci(acc_diff, rows, n_resamples=n_bootstrap, seed=seed)
    bri_lo, bri_hi = bootstrap_ci(bri_diff, rows, n_resamples=n_bootstrap, seed=seed + 1)
    return {
        "n": len(rows),
        "acc_a": acc_a, "acc_b": acc_b,
        "acc_delta": acc_b - acc_a,
        "acc_delta_ci_95": [acc_lo, acc_hi],
        "brier_a": bri_a, "brier_b": bri_b,
        "brier_delta": bri_b - bri_a,
        "brier_delta_ci_95": [bri_lo, bri_hi],
    }


def _acc(rows: list[_PerGameJoinRow], prob_field: str) -> float:
    if not rows:
        return 0.0
    correct = 0
    for r in rows:
        p = getattr(r, prob_field)
        pick_home = p > 0.5
        if pick_home == r.actual_home_won and p != 0.5:
            correct += 1
    return correct / len(rows)


def _brier(rows: list[_PerGameJoinRow], prob_field: str) -> float:
    if not rows:
        return 0.0
    arr = np.array([(getattr(r, prob_field) - (1.0 if r.actual_home_won else 0.0)) ** 2 for r in rows])
    return float(arr.mean())


def _latest_run_id(sb, config_label: str) -> str | None:
    res = (
        sb.table("game_predictions")
        .select("run_id,created_at")
        .eq("config_label", config_label)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    return res.data[0].get("run_id")


def _load_predictions(sb, run_id: str) -> list[dict]:
    out: list[dict] = []
    offset, page = 0, 1000
    while True:
        res = (
            sb.table("game_predictions")
            .select("game_id,home_win_probability,config_label,run_id")
            .eq("run_id", run_id)
            .range(offset, offset + page - 1)
            .execute()
        )
        if not res.data:
            break
        out.extend(res.data)
        if len(res.data) < page:
            break
        offset += page
    return out


def _load_games_by_id(sb, game_ids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not game_ids:
        return out
    for i in range(0, len(game_ids), 500):
        chunk = game_ids[i : i + 500]
        res = (
            sb.table("games")
            .select("id,home_team_id,away_team_id,home_score,away_score,status")
            .in_("id", chunk)
            .execute()
        )
        for r in res.data:
            out[r["id"]] = r
    return out


def _write_diff_markdown(path: Path, payload: dict) -> None:
    lines: list[str] = []
    lines.append(f"# Diff: `{payload['config_a']}` vs `{payload['config_b']}`")
    lines.append("")
    lines.append(f"- Run A: `{payload['run_id_a']}`")
    lines.append(f"- Run B: `{payload['run_id_b']}`")
    lines.append(f"- Paired games: {payload['paired_games']}")
    lines.append("")
    overall = payload.get("overall") or {}
    if overall.get("n"):
        lines.append("## Overall")
        lines.append("")
        lines.append(f"- Acc A: {overall['acc_a']:.4f} → Acc B: {overall['acc_b']:.4f} "
                     f"(Δ {overall['acc_delta']:+.4f}, 95% CI "
                     f"[{overall['acc_delta_ci_95'][0]:+.4f}, {overall['acc_delta_ci_95'][1]:+.4f}])")
        lines.append(f"- Brier A: {overall['brier_a']:.4f} → Brier B: {overall['brier_b']:.4f} "
                     f"(Δ {overall['brier_delta']:+.4f}, 95% CI "
                     f"[{overall['brier_delta_ci_95'][0]:+.4f}, {overall['brier_delta_ci_95'][1]:+.4f}])")
        lines.append("")
    lines.append("## Per-sport")
    lines.append("")
    lines.append("| Sport | N | Δ acc | Acc CI | Δ brier | Brier CI |")
    lines.append("|---|---|---|---|---|---|")
    for sport, b in payload.get("sports", {}).items():
        if not b.get("n"):
            continue
        ac = b["acc_delta_ci_95"]
        bc = b["brier_delta_ci_95"]
        lines.append(
            f"| {sport} | {b['n']} | {b['acc_delta']:+.4f} | "
            f"[{ac[0]:+.4f}, {ac[1]:+.4f}] | {b['brier_delta']:+.4f} | "
            f"[{bc[0]:+.4f}, {bc[1]:+.4f}] |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _default_factory():  # pragma: no cover - thin wrapper
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "https://ywlaekkxkwfznwuupggi.supabase.co")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY env var is required")
    return create_client(url, key)
