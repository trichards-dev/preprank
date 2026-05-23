"""Monte Carlo simulation engine using NumPy vectorization."""
from __future__ import annotations

import numpy as np

from engine.types import (
    TeamRecord, GameResult, GameStatus,
    ScheduledGame, SimulationConfig, TeamProjection,
)
from engine.power_rating import calculate_all_ratings, _eligible_games, _build_team_games, calculate_game_points
from engine.win_probability import win_probability_batch, win_probability_batch_v2
from engine.prediction.config import PredictionConfig


def run_simulation(
    teams: dict[int, TeamRecord],
    played_games: list[GameResult],
    remaining_games: list[ScheduledGame],
    config: SimulationConfig,
    seed: int | None = None,
    prediction_config: PredictionConfig | None = None,
) -> dict[int, TeamProjection]:
    """Run Monte Carlo simulation and return projections for all teams.

    When ``prediction_config`` is ``None`` (the default), the simulation uses
    ``config.home_advantage`` / ``config.k_factor`` and the legacy
    :func:`win_probability_batch` path - existing callers are unaffected.

    When a :class:`PredictionConfig` is supplied, its ``home_advantage`` /
    ``k_factor`` override ``config``'s values and the routing flips to
    :func:`win_probability_batch_v2`. With a default ``PredictionConfig()``
    this still produces numerically identical results.
    """
    rng = np.random.default_rng(seed)
    num_runs = config.num_runs
    num_remaining = len(remaining_games)
    team_ids = sorted(teams.keys())
    tid_to_idx = {tid: i for i, tid in enumerate(team_ids)}
    num_teams = len(team_ids)

    # Pre-compute current ratings for win probability
    current = calculate_all_ratings(teams, played_games)

    if num_remaining == 0:
        return _projections_from_single_state(current, team_ids, config)

    # Build arrays for remaining games
    home_ratings = np.array([current[g.home_team_id].power_rating for g in remaining_games])
    away_ratings = np.array([current[g.away_team_id].power_rating for g in remaining_games])

    # Win probabilities for all remaining games
    if prediction_config is None:
        probs = win_probability_batch(home_ratings, away_ratings, config.home_advantage, config.k_factor)
    else:
        probs = win_probability_batch_v2(
            home_ratings,
            away_ratings,
            prediction_config,
            sport=config.sport_name,
        )

    # Generate all random outcomes at once: (num_runs, num_remaining)
    random_draws = rng.random((num_runs, num_remaining))
    home_wins_matrix = random_draws < probs  # broadcast probs across runs

    # --- Pre-compute base game structure for fast per-run rating calc ---
    eligible_played = _eligible_games(played_games)
    base_team_games = _build_team_games(eligible_played)

    # Pre-compute classification lookup and play-up points for each game edge
    classifications = {tid: teams[tid].classification for tid in team_ids}

    # Build a compact representation of all played-game edges per team
    # For each team: list of (won: bool, opp_id: int, play_up_pts: float)
    base_edges: dict[int, list[tuple[bool, int, float]]] = {}
    for tid in team_ids:
        my_cls = classifications[tid]
        edges = []
        for won, opp_id in base_team_games.get(tid, []):
            opp_cls = classifications.get(opp_id, my_cls)
            from engine.types import ClassificationLevel
            pup = 2.0 * ClassificationLevel.play_up_levels(my_cls, opp_cls)
            edges.append((won, opp_id, pup))
        base_edges[tid] = edges

    # Pre-compute remaining game edges (per team) - these are indexed by remaining game index
    # For each remaining game, store (team_id, opp_id, play_up_pts, is_home)
    remaining_edges_by_team: dict[int, list[tuple[int, int, float]]] = {tid: [] for tid in team_ids}
    for g_idx, game in enumerate(remaining_games):
        h, a = game.home_team_id, game.away_team_id
        h_cls = classifications.get(h, "5A")
        a_cls = classifications.get(a, "5A")
        from engine.types import ClassificationLevel
        h_pup = 2.0 * ClassificationLevel.play_up_levels(h_cls, a_cls)
        a_pup = 2.0 * ClassificationLevel.play_up_levels(a_cls, h_cls)
        remaining_edges_by_team[h].append((g_idx, a, h_pup))  # home team's perspective
        remaining_edges_by_team[a].append((g_idx, h, a_pup))  # away team's perspective

    # Which team is home for each remaining game (needed to determine win/loss)
    remaining_home_ids = np.array([g.home_team_id for g in remaining_games])

    # Base wins/losses from played games
    base_wins = np.zeros(num_teams, dtype=np.int32)
    base_losses = np.zeros(num_teams, dtype=np.int32)
    for tid in team_ids:
        idx = tid_to_idx[tid]
        for won, _, _ in base_edges[tid]:
            if won:
                base_wins[idx] += 1
            else:
                base_losses[idx] += 1

    # Precompute division membership for ranking
    div_teams: dict[str, list[int]] = {}
    for tid in team_ids:
        div = teams[tid].division
        div_teams.setdefault(div, []).append(tid)

    # Storage for per-run results
    all_ratings = np.zeros((num_runs, num_teams))
    all_wins = np.zeros((num_runs, num_teams))
    all_losses = np.zeros((num_runs, num_teams))
    all_ranks = np.zeros((num_runs, num_teams))

    for run_idx in range(num_runs):
        home_wins_run = home_wins_matrix[run_idx]

        # Compute wins/losses for this run
        run_wins = base_wins.copy()
        run_losses = base_losses.copy()

        for g_idx in range(num_remaining):
            h_idx = tid_to_idx[remaining_games[g_idx].home_team_id]
            a_idx = tid_to_idx[remaining_games[g_idx].away_team_id]
            if home_wins_run[g_idx]:
                run_wins[h_idx] += 1
                run_losses[a_idx] += 1
            else:
                run_losses[h_idx] += 1
                run_wins[a_idx] += 1

        # Total games per team
        run_total = run_wins + run_losses

        # Single-pass rating calculation (no iteration - fast approximation)
        # For each team, compute game_points using opponent win records from this run
        run_ratings = np.zeros(num_teams)

        for tid in team_ids:
            tidx = tid_to_idx[tid]
            total_pts = 0.0
            num_games = 0

            # Base (played) games
            for won, opp_id, pup in base_edges[tid]:
                opp_idx = tid_to_idx.get(opp_id)
                if opp_idx is not None:
                    opp_w = run_wins[opp_idx]
                    opp_t = run_total[opp_idx]
                else:
                    opp_w = 0
                    opp_t = 0
                result_pts = 10.0 if won else 0.0
                opp_win_pts = (opp_w / opp_t * 10.0) if opp_t > 0 else 0.0
                total_pts += result_pts + pup + opp_win_pts
                num_games += 1

            # Remaining (simulated) games
            for g_idx, opp_id, pup in remaining_edges_by_team[tid]:
                home_won = home_wins_run[g_idx]
                # Did this team win?
                is_home = remaining_games[g_idx].home_team_id == tid
                won = home_won if is_home else not home_won

                opp_idx = tid_to_idx.get(opp_id)
                if opp_idx is not None:
                    opp_w = run_wins[opp_idx]
                    opp_t = run_total[opp_idx]
                else:
                    opp_w = 0
                    opp_t = 0
                result_pts = 10.0 if won else 0.0
                opp_win_pts = (opp_w / opp_t * 10.0) if opp_t > 0 else 0.0
                total_pts += result_pts + pup + opp_win_pts
                num_games += 1

            if num_games > 0:
                run_ratings[tidx] = round(total_pts / num_games, 2)

        all_ratings[run_idx] = run_ratings
        all_wins[run_idx] = run_wins
        all_losses[run_idx] = run_losses

        # Rank by division
        for div, dtids in div_teams.items():
            div_data = [(tid, run_ratings[tid_to_idx[tid]]) for tid in dtids]
            div_data.sort(key=lambda x: -x[1])
            for rank, (tid, _) in enumerate(div_data, 1):
                all_ranks[run_idx, tid_to_idx[tid]] = rank

    return _aggregate_projections(
        team_ids, tid_to_idx, all_ratings, all_wins, all_losses, all_ranks,
        config, num_runs, teams,
    )


def _aggregate_projections(
    team_ids: list[int],
    tid_to_idx: dict[int, int],
    all_ratings: np.ndarray,
    all_wins: np.ndarray,
    all_losses: np.ndarray,
    all_ranks: np.ndarray,
    config: SimulationConfig,
    num_runs: int,
    teams: dict[int, TeamRecord],
) -> dict[int, TeamProjection]:
    projections: dict[int, TeamProjection] = {}

    for tid in team_ids:
        idx = tid_to_idx[tid]
        ratings = all_ratings[:, idx]
        wins = all_wins[:, idx]
        losses = all_losses[:, idx]
        ranks = all_ranks[:, idx]

        playoff_count = np.sum(ranks <= config.playoff_spots)
        champ_count = np.sum(ranks == 1)

        projections[tid] = TeamProjection(
            team_id=tid,
            projected_rating_mean=round(float(np.mean(ratings)), 2),
            projected_rating_median=round(float(np.median(ratings)), 2),
            projected_rating_p10=round(float(np.percentile(ratings, 10)), 2),
            projected_rating_p90=round(float(np.percentile(ratings, 90)), 2),
            projected_rank_mean=round(float(np.mean(ranks)), 1),
            playoff_probability=round(float(playoff_count / num_runs * 100), 2),
            championship_probability=round(float(champ_count / num_runs * 100), 2),
            projected_wins_mean=round(float(np.mean(wins)), 1),
            projected_losses_mean=round(float(np.mean(losses)), 1),
        )

    return projections


def _projections_from_single_state(
    current: dict[int, TeamRecord],
    team_ids: list[int],
    config: SimulationConfig,
) -> dict[int, TeamProjection]:
    divisions: dict[str, list[tuple[int, float]]] = {}
    for tid in team_ids:
        t = current[tid]
        divisions.setdefault(t.division, []).append((tid, t.power_rating))

    ranks: dict[int, int] = {}
    for div_teams in divisions.values():
        sorted_teams = sorted(div_teams, key=lambda x: -x[1])
        for rank, (tid, _) in enumerate(sorted_teams, 1):
            ranks[tid] = rank

    projections: dict[int, TeamProjection] = {}
    for tid in team_ids:
        t = current[tid]
        rank = ranks[tid]
        projections[tid] = TeamProjection(
            team_id=tid,
            projected_rating_mean=t.power_rating,
            projected_rating_median=t.power_rating,
            projected_rating_p10=t.power_rating,
            projected_rating_p90=t.power_rating,
            projected_rank_mean=float(rank),
            playoff_probability=100.0 if rank <= config.playoff_spots else 0.0,
            championship_probability=100.0 if rank == 1 else 0.0,
            projected_wins_mean=float(t.wins),
            projected_losses_mean=float(t.losses),
        )
    return projections
