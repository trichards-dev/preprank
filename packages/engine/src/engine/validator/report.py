"""Report writers (JSON, CSV, Markdown, reliability PNG).

All writers take a target ``Path`` and a :class:`RunResult` (or list of
``PredictionRecord``) and produce a file. matplotlib is imported lazily —
runners that don't need the PNG won't pay the import cost.
"""
from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .predictor import PredictionRecord

if TYPE_CHECKING:  # pragma: no cover
    from .runner import RunResult


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def write_summary_json(path: Path, result: "RunResult") -> None:
    """Write ``summary.json`` matching the spec schema."""
    payload = {
        "config": result.config_label,
        "run_id": result.run_id,
        "run_timestamp": result.timestamp.isoformat(),
        "n_predictions": result.n_predictions,
        "n_cold_start": result.n_cold_start,
        "sports": result.sports,
        "overall": result.overall,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")


def _json_default(obj):
    # Pydantic models / sets etc.
    if isinstance(obj, set):
        return sorted(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
PER_GAME_LOG_COLUMNS = [
    "run_id",
    "sport",
    "season_year",
    "week_number",
    "game_id",
    "home_team_id",
    "away_team_id",
    "home_rating_pregame",
    "away_rating_pregame",
    "home_win_probability",
    "predicted_winner",
    "actual_winner",
    "correct",
    "home_cold_start",
    "away_cold_start",
]


def write_per_game_log_csv(
    path: Path, predictions: Sequence[PredictionRecord], run_id: str
) -> None:
    """Write one row per ``PredictionRecord`` to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(PER_GAME_LOG_COLUMNS)
        for p in predictions:
            if p.home_win_probability == 0.5:
                # Treat as no-opinion to match game_winner_accuracy()'s exclusion rule.
                predicted_winner = "tie"
                if p.actual_home_won is None:
                    actual_winner = ""
                    correct = ""
                else:
                    actual_winner = "home" if p.actual_home_won else "away"
                    correct = ""
            else:
                pick_home = p.home_win_probability > 0.5
                predicted_winner = "home" if pick_home else "away"
                if p.actual_home_won is None:
                    actual_winner = ""
                    correct = ""
                else:
                    actual_winner = "home" if p.actual_home_won else "away"
                    correct = "1" if (pick_home == bool(p.actual_home_won)) else "0"
            writer.writerow([
                run_id,
                p.sport,
                p.season_year,
                p.week_number,
                p.game_id,
                p.home_team_id,
                p.away_team_id,
                f"{p.home_rating_pregame:.4f}",
                f"{p.away_rating_pregame:.4f}",
                f"{p.home_win_probability:.6f}",
                predicted_winner,
                actual_winner,
                correct,
                "1" if p.home_cold_start else "0",
                "1" if p.away_cold_start else "0",
            ])


# ---------------------------------------------------------------------------
# Reliability PNG (matplotlib)
# ---------------------------------------------------------------------------
def write_reliability_plot(path: Path, predictions: Sequence[PredictionRecord]) -> None:
    """Write a reliability diagram PNG. Raises ImportError if matplotlib is missing."""
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    from .metrics import reliability_bins  # noqa: PLC0415

    bins = reliability_bins(predictions, n_bins=10)
    xs: list[float] = []
    ys: list[float] = []
    ns: list[int] = []
    for b in bins:
        if b["n_games"] == 0:
            continue
        xs.append(b["mean_predicted"])
        ys.append(b["mean_observed"])
        ns.append(b["n_games"])

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], color="grey", linestyle="--", label="perfect calibration")
    if xs:
        sizes = [max(20, min(400, n / 5)) for n in ns]
        ax.scatter(xs, ys, s=sizes, color="C0", alpha=0.7, label="empirical")
        ax.plot(xs, ys, color="C0", alpha=0.4)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Predicted P(home wins)")
    ax.set_ylabel("Observed P(home wins)")
    ax.set_title(f"Reliability diagram (n={sum(ns)})")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def write_markdown_report(path: Path, result: "RunResult") -> None:
    """Write a short Markdown report with the per-sport summary table."""
    lines: list[str] = []
    lines.append(f"# Validator run — `{result.config_label}`")
    lines.append("")
    lines.append(f"- Run ID: `{result.run_id}`")
    lines.append(f"- Timestamp: {result.timestamp.isoformat()}")
    lines.append(f"- Predictions: {result.n_predictions}")
    lines.append(f"- Cold-start games (either side): {result.n_cold_start}")
    lines.append("")

    lines.append("## Overall")
    lines.append("")
    lines.append("| Split | N | Game-winner acc | Brier |")
    lines.append("|---|---|---|---|")
    lines.append(_overall_row("Train", result.overall.get("train", {}), result.overall.get("n_train", 0)))
    lines.append(_overall_row("Holdout", result.overall.get("holdout", {}), result.overall.get("n_holdout", 0)))
    ci = result.overall.get("ci_95", {})
    if ci:
        acc_ci = ci.get("game_winner_acc", [0.0, 0.0])
        bri_ci = ci.get("brier", [0.0, 0.0])
        lines.append(
            f"| Train 95% CI |  | [{acc_ci[0]:.4f}, {acc_ci[1]:.4f}] | [{bri_ci[0]:.4f}, {bri_ci[1]:.4f}] |"
        )
    lines.append("")

    lines.append("## Per-sport summary")
    lines.append("")
    lines.append("| Sport | N train | N holdout | Train acc | Holdout acc | Train brier | Holdout brier |")
    lines.append("|---|---|---|---|---|---|---|")
    for sport_name, block in result.sports.items():
        train = block.get("train", {})
        hold = block.get("holdout", {})
        lines.append(
            f"| {sport_name} | {block.get('n_train', 0)} | {block.get('n_holdout', 0)} | "
            f"{train.get('game_winner_acc', 0.0):.4f} | {hold.get('game_winner_acc', 0.0):.4f} | "
            f"{train.get('brier', 0.0):.4f} | {hold.get('brier', 0.0):.4f} |"
        )
    lines.append("")

    lines.append("## Reliability bins (overall, train)")
    lines.append("")
    lines.append("| Bin lower | Bin upper | Mean predicted | Mean observed | N games |")
    lines.append("|---|---|---|---|---|")
    for b in result.overall.get("train", {}).get("reliability_bins", []):
        mp = b["mean_predicted"]
        mo = b["mean_observed"]
        mp_s = f"{mp:.4f}" if mp == mp else "—"  # NaN check (NaN != NaN)
        mo_s = f"{mo:.4f}" if mo == mo else "—"
        lines.append(
            f"| {b['bin_lower']:.2f} | {b['bin_upper']:.2f} | {mp_s} | {mo_s} | {b['n_games']} |"
        )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _overall_row(label: str, block: dict, n: int) -> str:
    acc = block.get("game_winner_acc", 0.0)
    bri = block.get("brier", 0.0)
    return f"| {label} | {n} | {acc:.4f} | {bri:.4f} |"
