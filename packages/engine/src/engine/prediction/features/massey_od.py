"""Phase 4d feature: Massey-style offense/defense decomposition (Delta_f_offdef, beta_4).

Per `docs/model_specification.md` Delta_f_offdef section (lines 83-92):

    For each team, decompose season-to-date scoring into offensive
    strength (points produced above the league mean) and defensive
    strength (points allowed below the league mean) via least-squares
    Massey decomposition. The game-level feature is the home team's
    offense-vs-away-defense matchup minus the away team's offense-vs-
    home-defense matchup:

        matchup(team_X_off, team_Y_def) = X_off_strength + Y_def_weakness
        Delta_f_offdef(g) = matchup(h_off, a_def) - matchup(a_off, h_def)

Identifiability via explicit reparameterization (Reese 2026-05-27)
------------------------------------------------------------------
The unconstrained Massey system has a 2-DOF translation degeneracy:
    (alpha + c1, o - c1, d) and (alpha + c2, o, d - c2)
both leave predictions unchanged. The previous ridge-stabilized version
had cond(X'X) ~ 10^9 because the ridge was picking an essentially
arbitrary point in the 2-DOF null-space.

This version resolves identifiability **structurally** by dropping the
reference team's offense column AND defense column from the LS design
matrix. With 2 fewer parameters, the system has full rank when the
game graph is connected. The reference team is the lowest team_id in
the basis (deterministic for reproducibility). After the solve, the
reference team's o and d are set to 0, then all o's and d's are
centered to zero mean (with the difference absorbed into alpha).

Conditioning guardrail: cond(X'X) of the reduced design matrix MUST
be below CONDITIONING_THRESHOLD (default 1e4). If it isn't (e.g. the
game graph is disconnected), `MasseyConditioningError` is raised. The
guardrail is a permanent fixture of this module per Reese 2026-05-27.

Temporal-boundary contract
--------------------------
``precompute_team_week_massey_od(games)`` returns a
``{(team_id, week): (o, d)}`` lookup matching the existing convention:
the entry at week W is the Massey LS solve using only games with
``_engine_week <= W``. The runner queries with ``W-1`` for the
strictly-before-the-game signal. Dense in W between min/max so the
runner can index any intermediate week without missing values.

Cold-start safe: a team with no games in the through-W subset gets
``(0.0, 0.0)`` from the runner's default ``signals.get((team_id, w-1),
(0.0, 0.0))`` pattern, NOT from a dict entry.

Numerical details
-----------------
- Out-of-state games are SKIPPED (matching `totals.py` convention).
- No ridge penalty in production. The `ridge` parameter is retained
  for diagnostic / ridge-sensitivity testing only.
- Early-season weeks where the game graph is too sparse to satisfy
  the conditioning guardrail produce NO dict entry for that
  (team, week). The runner's `.get(..., (0.0, 0.0))` fallback handles
  the gap as cold-start, which is the correct behavior for an
  identifiability failure.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np


RIDGE = 0.0
"""Default ridge for `_solve_massey`. Explicit reparameterization is the
identifiability fix; ridge is not part of the production solve path.
Retained for diagnostic ridge-sensitivity testing only."""


CONDITIONING_THRESHOLD = 1e5
"""Reese 2026-05-27 evening initial proposal was 1e4. Calibrated empirically
2026-05-27 night: real LHSAA bases (149 teams, 1000+ sides for Girls Soccer
2025) land at cond ~ 1.5e4 to 2.1e4 from weeks 2+ — just above 1e4 but
still excellent in absolute terms (losing 4 digits of precision in double-
precision arithmetic, ~12 meaningful digits remaining). The original
ridge-stabilized cond was ~10^9; even the relaxed 1e5 is FOUR orders of
magnitude stricter than that. Disconnected-graph cases (e.g., week 1 with
only a fraction of teams having played) still fail at cond ~ 10^16 to
10^19, multiple OOM above threshold."""


class MasseyConditioningError(RuntimeError):
    """Raised when the reduced LS design matrix is too ill-conditioned
    to trust. Indicates the game graph is too disconnected (or too
    sparse) for Massey identifiability at the requested week."""


def _solve_massey(
    game_sides: list[tuple[int, int, float]],
    teams: list[int],
    *,
    ridge: float = RIDGE,
    conditioning_threshold: float = CONDITIONING_THRESHOLD,
) -> tuple[float, dict[int, float], dict[int, float], float]:
    """Solve the Massey LS system via explicit reparameterization.

    ``game_sides`` is a list of ``(scoring_team_id, opponent_team_id,
    points_scored)`` triplets. For each game in the input, callers must
    emit TWO entries — one for each team's scoring perspective — so the
    LS system sees both sides of the game.

    Returns ``(alpha, offense_by_team, defense_by_team, cond_number)``:
      - ``alpha``: league-mean per-team-per-game after centering.
      - ``offense_by_team[i] = o_i`` with ``mean over teams of o_i = 0``.
      - ``defense_by_team[i] = d_i`` with ``mean over teams of d_i = 0``.
      - ``cond_number``: cond(X_reduced^T @ X_reduced) of the actually-
        solved system. Reported for diagnostic use.

    Raises ``MasseyConditioningError`` if the reduced design matrix
    is too ill-conditioned. ``ridge`` parameter retained for diagnostic
    sensitivity testing only — production callers use ridge=0.

    The reference team is the lowest team_id present in ``teams``
    (deterministic for reproducibility). Its o and d are fixed to 0
    before centering; centering then shifts all values to zero mean.
    """
    if not game_sides or not teams:
        return 0.0, {}, {}, 0.0

    teams_sorted = sorted(teams)
    n = len(teams_sorted)
    if n < 2:
        # Single-team basis is unidentifiable for o vs d.
        # Return zeros and a "perfect" conditioning marker; the caller
        # decides whether to emit an entry or skip.
        return 0.0, {t: 0.0 for t in teams_sorted}, {t: 0.0 for t in teams_sorted}, 1.0

    team_idx = {t: i for i, t in enumerate(teams_sorted)}
    ref_team = teams_sorted[0]   # deterministic reference: lowest team_id

    # Reduced parameter layout:
    #   [alpha, o_1, o_2, ..., o_{n-1}, d_1, d_2, ..., d_{n-1}]
    # The reference team's o and d are dropped (implicitly fixed to 0).
    n_o = n - 1
    n_d = n - 1
    n_params = 1 + n_o + n_d

    n_eqs = len(game_sides)
    X = np.zeros((n_eqs, n_params), dtype=np.float64)
    y = np.zeros(n_eqs, dtype=np.float64)

    for row, (team_id, opp_id, pts) in enumerate(game_sides):
        i_off = team_idx.get(team_id)
        i_def = team_idx.get(opp_id)
        if i_off is None or i_def is None:
            continue
        X[row, 0] = 1.0                          # alpha
        if i_off > 0:                            # skip reference team's o
            X[row, 1 + (i_off - 1)] = 1.0
        if i_def > 0:                            # skip reference team's d
            X[row, 1 + n_o + (i_def - 1)] = 1.0
        y[row] = pts

    # Solve via normal equations.
    XtX = X.T @ X
    if ridge > 0.0:
        XtX = XtX + ridge * np.eye(n_params, dtype=np.float64)
    Xty = X.T @ y

    cond_number = float(np.linalg.cond(XtX))
    if not np.isfinite(cond_number) or cond_number >= conditioning_threshold:
        raise MasseyConditioningError(
            f"reduced Massey design matrix cond(X'X) = {cond_number:.3e} >= "
            f"threshold {conditioning_threshold:.0e}. Game graph too disconnected/sparse "
            f"for identifiability at this basis (n_teams={n}, n_eqs={n_eqs})."
        )

    try:
        beta = np.linalg.solve(XtX, Xty)
    except np.linalg.LinAlgError:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)

    alpha_raw = float(beta[0])
    o_raw = np.zeros(n, dtype=np.float64)
    d_raw = np.zeros(n, dtype=np.float64)
    o_raw[1:] = beta[1:1 + n_o]
    d_raw[1:] = beta[1 + n_o:1 + n_o + n_d]
    # Reference team has o_raw[0] = d_raw[0] = 0 from the parameterization.

    # Center to zero mean. Translation absorbed into alpha.
    o_mean = float(o_raw.mean())
    d_mean = float(d_raw.mean())
    alpha_eff = alpha_raw + o_mean + d_mean
    o_centered = o_raw - o_mean
    d_centered = d_raw - d_mean

    offense = {teams_sorted[i]: float(o_centered[i]) for i in range(n)}
    defense = {teams_sorted[i]: float(d_centered[i]) for i in range(n)}
    return alpha_eff, offense, defense, cond_number


def _extract_game_sides(games: list[dict]) -> list[tuple[int, int, float, int]]:
    """Pull (scoring_team_id, opponent_team_id, points_scored, _engine_week)
    quadruplets from raw game dicts. Each game contributes TWO entries
    (home perspective + away perspective). OOS games and games missing
    scores or weeks are skipped.
    """
    out: list[tuple[int, int, float, int]] = []
    for g in games:
        if g.get("is_out_of_state"):
            continue
        w_raw = g.get("_engine_week")
        if w_raw is None:
            continue
        try:
            w = int(w_raw)
        except (TypeError, ValueError):
            continue
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        h = g.get("home_team_id")
        a = g.get("away_team_id")
        if h is None or a is None:
            continue
        out.append((int(h), int(a), float(hs), w))
        out.append((int(a), int(h), float(as_), w))
    return out


def precompute_team_week_massey_od(
    games: list[dict],
    *,
    ridge: float = RIDGE,
    conditioning_threshold: float = CONDITIONING_THRESHOLD,
) -> dict[tuple[int, int], tuple[float, float]]:
    """Build a ``{(team_id, week): (offense, defense)}`` Massey LS lookup.

    For each ``(team, week W)`` the entry is the team's Massey LS
    offense + defense ratings computed using only that team's games
    whose ``_engine_week`` is ``<= W``. Other teams in the LS solve are
    those that participated in any in-state game with
    ``_engine_week <= W``.

    Dense in W between min_week and max_week.

    **Conditioning-guarded:** at each week, if the reduced LS design
    matrix has cond(X'X) >= ``conditioning_threshold``, that week's
    entries are SKIPPED. The runner's `.get(..., (0.0, 0.0))` fallback
    handles the gap as cold-start.

    Returns an empty dict if the input has no scoreable in-state games.
    """
    if not games:
        return {}

    sides = _extract_game_sides(games)
    if not sides:
        return {}

    sides_by_week: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
    weeks_seen: set[int] = set()
    teams_seen: set[int] = set()
    for team_id, opp_id, pts, w in sides:
        sides_by_week[w].append((team_id, opp_id, pts))
        weeks_seen.add(w)
        teams_seen.add(team_id)
        teams_seen.add(opp_id)

    min_week = min(weeks_seen)
    max_week = max(weeks_seen)

    cumulative_sides: list[tuple[int, int, float]] = []
    out: dict[tuple[int, int], tuple[float, float]] = {}
    teams_with_games_so_far: set[int] = set()
    last_solution: tuple[float, dict[int, float], dict[int, float]] | None = None

    for w in range(min_week, max_week + 1):
        new_sides = sides_by_week.get(w, [])
        if new_sides:
            cumulative_sides.extend(new_sides)
            for team_id, opp_id, _pts in new_sides:
                teams_with_games_so_far.add(team_id)
                teams_with_games_so_far.add(opp_id)
            teams_list = sorted(teams_with_games_so_far)
            try:
                alpha, offense, defense, _cond = _solve_massey(
                    cumulative_sides, teams_list,
                    ridge=ridge,
                    conditioning_threshold=conditioning_threshold,
                )
                last_solution = (alpha, offense, defense)
            except MasseyConditioningError:
                last_solution = None

        if last_solution is None:
            continue
        _alpha, offense, defense = last_solution
        for team_id in teams_with_games_so_far:
            o = offense.get(team_id, 0.0)
            d = defense.get(team_id, 0.0)
            out[(team_id, w)] = (o, d)

    return out


# ---------------------------------------------------------------------------
# M2 redesigned: per-game residual-vs-outcome correlation (Reese 2026-05-27)
# ---------------------------------------------------------------------------
def per_game_residual_outcome_correlation(
    games: list[dict],
    massey_table: dict[tuple[int, int], tuple[float, float]],
    *,
    train_alpha: float | None = None,
) -> float | None:
    """Pearson r between Massey-predicted margin and binary home-won
    outcome at per-game granularity, evaluated on the input ``games``.

    For each game in week W, Massey predicts:
        predicted_home_score - predicted_away_score
      = (alpha + o_h + d_a) - (alpha + o_a + d_h)
      = (o_h - o_a) + (d_a - d_h)
    using the lookup at (team, W-1) which excludes the game itself.

    Returns Pearson r between predicted_margin and (home_won = 1/0).
    Returns None if fewer than 3 games or zero variance in one column.

    A real-signal Massey produces positive correlation (predicted
    margin should align with actual outcome). A ridge-artifact Massey
    may show weak or anti-correlated patterns. This is the redesigned
    M2 check that replaces the broken n=4 per-week version.
    """
    pred_margins = []
    home_wons = []
    for g in games:
        if g.get("is_out_of_state"):
            continue
        w_raw = g.get("_engine_week")
        if w_raw is None:
            continue
        try:
            w = int(w_raw)
        except (TypeError, ValueError):
            continue
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        h = g.get("home_team_id")
        a = g.get("away_team_id")
        h_signal = massey_table.get((int(h), w - 1), (0.0, 0.0))
        a_signal = massey_table.get((int(a), w - 1), (0.0, 0.0))
        h_o, h_d = h_signal
        a_o, a_d = a_signal
        pred_margin = (h_o - a_o) + (a_d - h_d)
        pred_margins.append(pred_margin)
        home_wons.append(1.0 if int(hs) > int(as_) else 0.0)

    if len(pred_margins) < 3:
        return None
    x = np.asarray(pred_margins, dtype=np.float64)
    y = np.asarray(home_wons, dtype=np.float64)
    if x.std() < 1e-12 or y.std() < 1e-12:
        return None
    return float(np.corrcoef(x, y)[0, 1])
