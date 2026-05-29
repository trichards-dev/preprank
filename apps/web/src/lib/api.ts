const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// NOTE (2026-05-29): `GET /api/v1/games/{game_id}/forecast` was added to
// the API in commit 40dfc16 (Phase 2 of the confidence-disclosure UX
// workstream). Endpoint shape: per-game home_win_probability + CI bounds +
// confidence tier label + auth-conditional premium_detail block. This file
// will gain a `fetchGameForecast()` helper + corresponding TypeScript types
// when the Phase 3 web layer kicks off after the week-1 engine checkpoint
// (see claude-memory/apps/preprank/forecast_api_design_2026-05-29.md +
// confidence_disclosure_ux_options_2026-05-29.md Spec 6).
//
// AMENDMENT (2026-05-29 evening, commit 8d321e9): the forecast endpoint's
// CI methodology changed from post-iso bin gap to binomial sampling CI
// (Option D, approved by Reese; see decisions.md 2026-05-29 evening).
// The API response shape is UNCHANGED — same fields, same types — only
// the underlying CI computation differs. No web client work required for
// this amendment; this comment confirms contract review.

// --- Types ---

export interface RankedTeam {
  rank: number;
  school_name: string;
  division: string;
  classification: string;
  select_status: string;
  power_rating: number;
  strength_factor: number | null;
  team_id: number;
  school_id: number;
}

export interface School {
  id: number;
  name: string;
  city: string | null;
  parish: string | null;
  classification: string | null;
  division: string | null;
  select_status: string | null;
  enrollment: number | null;
}

export interface Team {
  id: number;
  school_id: number;
  sport_id: number;
  season_year: number;
  head_coach: string | null;
  division: string | null;
  select_status: string | null;
  school_name: string;
  sport_name: string;
}

export interface Game {
  id: number;
  home_team_id: number;
  away_team_id: number;
  sport_id: number;
  season_year: number;
  game_date: string | null;
  week_number: number | null;
  home_score: number | null;
  away_score: number | null;
  status: string;
  is_district: boolean;
  is_playoff: boolean;
  is_championship: boolean;
  is_out_of_state: boolean;
  home_team_name: string | null;
  away_team_name: string | null;
}

export interface TeamProjection {
  team_id: number;
  school_name: string | null;
  division: string | null;
  projected_rating_mean: number;
  projected_rating_median: number;
  projected_rating_p10: number;
  projected_rating_p90: number;
  projected_rank_mean: number;
  playoff_probability: number;
  championship_probability: number;
  projected_wins_mean: number;
  projected_losses_mean: number;
}

export interface GameImpact {
  affected_team_id: number;
  school_name: string | null;
  rating_if_home_wins: number;
  rating_if_away_wins: number;
  rank_if_home_wins: number;
  rank_if_away_wins: number;
  playoff_prob_if_home_wins: number;
  playoff_prob_if_away_wins: number;
}

export interface PowerRating {
  id: number;
  team_id: number;
  week_number: number;
  season_year: number;
  power_rating: number;
  strength_factor: number | null;
  rank_in_division: number | null;
  total_teams_in_division: number | null;
}

// --- API Functions ---

async function apiFetch<T>(path: string, options?: RequestInit & { token?: string }): Promise<T> {
  const { token, ...fetchOptions } = options || {};
  const headers: Record<string, string> = {
    ...(fetchOptions.headers as Record<string, string> || {}),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  } else if (typeof window !== "undefined") {
    const stored = localStorage.getItem("preprank_token");
    if (stored) headers["Authorization"] = `Bearer ${stored}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...fetchOptions,
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${path}`);
  }
  return res.json();
}

export async function fetchRankings(
  sport: string,
  seasonYear: number,
  weekNumber: number,
  division?: string,
): Promise<RankedTeam[]> {
  const params = new URLSearchParams({
    sport,
    season_year: String(seasonYear),
    week_number: String(weekNumber),
  });
  if (division) params.set("division", division);
  return apiFetch(`/api/v1/ratings/rankings?${params}`);
}

export async function fetchSchools(params?: {
  division?: string;
  classification?: string;
}): Promise<School[]> {
  const sp = new URLSearchParams();
  if (params?.division) sp.set("division", params.division);
  if (params?.classification) sp.set("classification", params.classification);
  return apiFetch(`/api/v1/schools/?${sp}`);
}

export async function fetchTeams(params?: {
  sport?: string;
  season_year?: number;
  division?: string;
}): Promise<Team[]> {
  const sp = new URLSearchParams();
  if (params?.sport) sp.set("sport", params.sport);
  if (params?.season_year) sp.set("season_year", String(params.season_year));
  if (params?.division) sp.set("division", params.division);
  return apiFetch(`/api/v1/teams/?${sp}`);
}

export async function fetchTeam(teamId: number): Promise<Team> {
  return apiFetch(`/api/v1/teams/${teamId}`);
}

export async function fetchGames(params: {
  season_year: number;
  sport: string;
  week_number?: number;
  status?: string;
  team_id?: number;
}): Promise<Game[]> {
  const sp = new URLSearchParams({
    season_year: String(params.season_year),
    sport: params.sport,
  });
  if (params.week_number !== undefined) sp.set("week_number", String(params.week_number));
  if (params.status) sp.set("status", params.status);
  if (params.team_id !== undefined) sp.set("team_id", String(params.team_id));
  return apiFetch(`/api/v1/games/?${sp}`);
}

export async function fetchGame(gameId: number): Promise<Game> {
  return apiFetch(`/api/v1/games/${gameId}`);
}

export async function fetchTeamRatings(
  teamId: number,
  seasonYear: number,
): Promise<PowerRating[]> {
  return apiFetch(`/api/v1/ratings/${teamId}?season_year=${seasonYear}`);
}

export async function fetchTeamProjections(
  teamId: number,
): Promise<TeamProjection | null> {
  try {
    return await apiFetch(`/api/v1/simulations/team/${teamId}/projections`);
  } catch {
    return null;
  }
}

export async function fetchGameImpact(
  gameId: number,
): Promise<GameImpact[]> {
  try {
    return await apiFetch(`/api/v1/simulations/game/${gameId}/impact`);
  } catch {
    return [];
  }
}

// --- Favorites ---

export interface Favorite {
  id: number;
  entity_type: string;
  entity_id: number;
  school_name: string | null;
  division: string | null;
  classification: string | null;
}

export async function fetchFavorites(): Promise<Favorite[]> {
  return apiFetch("/api/v1/favorites/");
}

export async function addFavorite(entityType: string, entityId: number): Promise<Favorite> {
  return apiFetch("/api/v1/favorites/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
  });
}

export async function removeFavorite(favoriteId: number): Promise<void> {
  await fetch(`${API_BASE}/api/v1/favorites/${favoriteId}`, {
    method: "DELETE",
    headers: {
      Authorization: `Bearer ${localStorage.getItem("preprank_token") || ""}`,
    },
  });
}

// --- Subscriptions ---

export interface SubscriptionStatus {
  tier: string;
  expires: string | null;
  is_active: boolean;
}

export async function fetchSubscriptionStatus(): Promise<SubscriptionStatus> {
  return apiFetch("/api/v1/subscriptions/status");
}

export async function createCheckout(tier: string): Promise<{ url: string; price: number; name: string }> {
  return apiFetch("/api/v1/subscriptions/checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tier }),
  });
}

// --- Pick'em ---

export interface PickemContest {
  id: number;
  sport_id: number;
  season_year: number;
  week_number: number;
  title: string;
  status: string;
  opens_at: string | null;
  locks_at: string | null;
  scored_at: string | null;
  game_count: number;
}

export interface PickemGame {
  game_id: number;
  home_team_id: number;
  away_team_id: number;
  home_team_name: string | null;
  away_team_name: string | null;
  game_date: string | null;
  home_score: number | null;
  away_score: number | null;
  status: string;
}

export interface PickemEntryData {
  id: number;
  game_id: number;
  picked_team_id: number;
  picked_team_name: string | null;
  home_team_name: string | null;
  away_team_name: string | null;
  home_score: number | null;
  away_score: number | null;
  is_correct: boolean | null;
  points_earned: number;
}

export interface LeaderboardRow {
  rank: number;
  user_id: number;
  display_name: string;
  total_correct: number;
  total_picks: number;
  accuracy_pct: number;
  total_points: number;
}

export interface SchoolLeaderboardRow {
  rank: number;
  school_name: string;
  school_id: number;
  total_correct: number;
  total_picks: number;
  accuracy_pct: number;
  participant_count: number;
}

export interface Badge {
  id: number;
  badge_type: string;
  badge_name: string;
  description: string | null;
  earned_at: string;
}

export async function fetchContests(params?: {
  sport?: string; season_year?: number; status?: string;
}): Promise<PickemContest[]> {
  const sp = new URLSearchParams();
  if (params?.sport) sp.set("sport", params.sport);
  if (params?.season_year) sp.set("season_year", String(params.season_year));
  if (params?.status) sp.set("status", params.status);
  return apiFetch(`/api/v1/pickem/contests?${sp}`);
}

export async function fetchContest(contestId: number): Promise<PickemContest> {
  return apiFetch(`/api/v1/pickem/contests/${contestId}`);
}

export async function fetchContestGames(contestId: number): Promise<PickemGame[]> {
  return apiFetch(`/api/v1/pickem/contests/${contestId}/games`);
}

export async function submitPicks(
  contestId: number, picks: { game_id: number; picked_team_id: number }[],
): Promise<PickemEntryData[]> {
  return apiFetch(`/api/v1/pickem/contests/${contestId}/picks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ picks }),
  });
}

export async function fetchMyPicks(contestId: number): Promise<PickemEntryData[]> {
  return apiFetch(`/api/v1/pickem/contests/${contestId}/my-picks`);
}

export async function fetchIndividualLeaderboard(params?: {
  contest_id?: number; season_year?: number;
}): Promise<LeaderboardRow[]> {
  const sp = new URLSearchParams();
  if (params?.contest_id) sp.set("contest_id", String(params.contest_id));
  if (params?.season_year) sp.set("season_year", String(params.season_year));
  return apiFetch(`/api/v1/pickem/leaderboard/individual?${sp}`);
}

export async function fetchSchoolLeaderboard(params?: {
  contest_id?: number; season_year?: number;
}): Promise<SchoolLeaderboardRow[]> {
  const sp = new URLSearchParams();
  if (params?.contest_id) sp.set("contest_id", String(params.contest_id));
  if (params?.season_year) sp.set("season_year", String(params.season_year));
  return apiFetch(`/api/v1/pickem/leaderboard/schools?${sp}`);
}

export async function fetchMyBadges(): Promise<Badge[]> {
  return apiFetch("/api/v1/pickem/badges");
}

// --- Hype Scores ---

export interface HypeScore {
  team_id: number;
  school_name: string;
  division: string;
  hype_score: number;
  hype_label: string;
  rating_velocity: number | null;
  win_streak: number;
  power_rating: number | null;
}

export async function fetchTeamHype(teamId: number): Promise<HypeScore | null> {
  try {
    return await apiFetch(`/api/v1/hype/team/${teamId}`);
  } catch {
    return null;
  }
}

export async function fetchTrendingTeams(seasonYear: number = 2025): Promise<HypeScore[]> {
  try {
    return await apiFetch(`/api/v1/hype/trending?season_year=${seasonYear}`);
  } catch {
    return [];
  }
}

export function getShareImageUrl(type: string, id: number): string {
  return `${API_BASE}/api/v1/share/${type}/${id}/image`;
}

// --- Scenarios ---

export interface ScenarioResult {
  team_id: number;
  school_name: string | null;
  projected_rating: number;
  projected_rank: number;
  playoff_probability: number;
  championship_probability: number;
  projected_wins: number;
  projected_losses: number;
  locked_count: number;
  remaining_count: number;
}

export interface CompareResult {
  team_id: number;
  school_name: string | null;
  scenario_a: ScenarioResult;
  scenario_b: ScenarioResult;
  rating_delta: number;
  rank_delta: number;
  playoff_delta: number;
}

export async function calculateScenario(
  teamId: number,
  lockedOutcomes: { game_id: number; winner_team_id: number }[],
  sport: string = "Football",
  seasonYear: number = 2025,
  weekNumber: number = 11,
): Promise<ScenarioResult> {
  return apiFetch("/api/v1/scenarios/calculate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      team_id: teamId,
      locked_outcomes: lockedOutcomes,
      sport: sport,
      season_year: seasonYear,
      week_number: weekNumber,
    }),
  });
}

export async function calculateBestCase(
  teamId: number, sport: string = "Football", seasonYear: number = 2025, weekNumber: number = 11,
): Promise<ScenarioResult> {
  return apiFetch("/api/v1/scenarios/best-case", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ team_id: teamId, sport, season_year: seasonYear, week_number: weekNumber }),
  });
}

export async function calculateWorstCase(
  teamId: number, sport: string = "Football", seasonYear: number = 2025, weekNumber: number = 11,
): Promise<ScenarioResult> {
  return apiFetch("/api/v1/scenarios/worst-case", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ team_id: teamId, sport, season_year: seasonYear, week_number: weekNumber }),
  });
}
