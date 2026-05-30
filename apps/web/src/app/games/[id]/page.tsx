"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  fetchGame,
  fetchGameImpact,
  fetchGameForecast,
  Game,
  GameImpact,
  GameForecast,
} from "@/lib/api";
import ShareButton from "@/components/ShareButton";
import WinProbabilityWithCI from "@/components/WinProbabilityWithCI";

export default function GameDetailPage() {
  const params = useParams();
  const gameId = Number(params.id);

  const [game, setGame] = useState<Game | null>(null);
  const [impacts, setImpacts] = useState<GameImpact[]>([]);
  const [forecast, setForecast] = useState<GameForecast | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!gameId) return;
    setLoading(true);
    Promise.all([
      fetchGame(gameId),
      fetchGameImpact(gameId),
      fetchGameForecast(gameId).catch(() => null),
    ])
      .then(([g, i, f]) => {
        setGame(g);
        setImpacts(i);
        setForecast(f);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [gameId]);

  if (loading) return <main className="mx-auto max-w-5xl px-4 py-8"><p className="text-steel-gray">Loading...</p></main>;
  if (error || !game) return <main className="mx-auto max-w-5xl px-4 py-8"><p className="text-crimson">Error: {error || "Game not found"}</p></main>;

  const isFinal = game.status === "final";
  const homeWon = isFinal && game.home_score !== null && game.away_score !== null && game.home_score > game.away_score;
  const awayWon = isFinal && game.home_score !== null && game.away_score !== null && game.away_score > game.home_score;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      {/* Game Header */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-steel-gray uppercase tracking-wide">
          {game.is_playoff ? "Playoff" : game.is_district ? "District" : "Non-District"}
          {game.week_number && ` \u00B7 Week ${game.week_number}`}
          {game.game_date && ` \u00B7 ${new Date(game.game_date + "T00:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })}`}
        </span>
        <ShareButton
          title={`${game.home_team_name} vs ${game.away_team_name} | PrepRank`}
          text={`${game.home_team_name} vs ${game.away_team_name} on PrepRank`}
          url={`${typeof window !== "undefined" ? window.location.origin : ""}/games/${gameId}`}
        />
      </div>

      <div className="rounded-lg border border-steel-gray/30 p-6 mb-8">
        <div className="text-center mb-1">
          <span className={`text-xs font-bold uppercase ${isFinal ? "text-steel-gray" : "text-green-500"}`}>
            {game.status}
          </span>
        </div>

        <div className="flex items-center justify-center gap-8 md:gap-16">
          {/* Home Team */}
          <div className="text-center flex-1">
            <Link href={`/teams/${game.home_team_id}`} className="hover:text-crimson transition-colors">
              <div className="text-xl md:text-2xl font-bold" style={{ fontFamily: "var(--font-display)" }}>
                {game.home_team_name || `Team #${game.home_team_id}`}
              </div>
            </Link>
            <div className="text-xs text-steel-gray mt-1">HOME</div>
            <div className={`text-5xl md:text-6xl font-bold mt-2 ${homeWon ? "text-white" : "text-steel-gray"}`} style={{ fontFamily: "var(--font-display)" }}>
              {game.home_score ?? "-"}
            </div>
          </div>

          <div className="text-3xl text-steel-gray font-bold">VS</div>

          {/* Away Team */}
          <div className="text-center flex-1">
            <Link href={`/teams/${game.away_team_id}`} className="hover:text-crimson transition-colors">
              <div className="text-xl md:text-2xl font-bold" style={{ fontFamily: "var(--font-display)" }}>
                {game.away_team_name || `Team #${game.away_team_id}`}
              </div>
            </Link>
            <div className="text-xs text-steel-gray mt-1">AWAY</div>
            <div className={`text-5xl md:text-6xl font-bold mt-2 ${awayWon ? "text-white" : "text-steel-gray"}`} style={{ fontFamily: "var(--font-display)" }}>
              {game.away_score ?? "-"}
            </div>
          </div>
        </div>
      </div>

      {/* Win Probability (Phase 3.3.2) */}
      {!isFinal && forecast && (
        <section className="mb-8">
          <h2
            className="text-xl font-bold mb-4"
            style={{ fontFamily: "var(--font-display)" }}
          >
            WIN PROBABILITY
          </h2>
          <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-6">
            <WinProbabilityWithCI
              homeTeamName={game.home_team_name || `Team #${game.home_team_id}`}
              awayTeamName={game.away_team_name || `Team #${game.away_team_id}`}
              forecast={forecast.forecast}
              forecastUnavailableReason={forecast.forecast_unavailable_reason}
              sourceDataCaveat={forecast.source_data_caveat}
              variant="expanded"
            />
          </div>
        </section>
      )}

      {/* Impact Analysis */}
      {impacts.length > 0 && (
        <section>
          <h2
            className="text-xl font-bold mb-4"
            style={{ fontFamily: "var(--font-display)" }}
          >
            WHAT&apos;S AT STAKE
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-steel-gray text-steel-gray uppercase tracking-wide">
                  <th className="px-3 py-2">Team</th>
                  <th className="px-3 py-2 text-center">Rating if Home Wins</th>
                  <th className="px-3 py-2 text-center">Rating if Away Wins</th>
                  <th className="px-3 py-2 text-center">Rank if Home</th>
                  <th className="px-3 py-2 text-center">Rank if Away</th>
                  <th className="px-3 py-2 text-center">Playoff% if Home</th>
                  <th className="px-3 py-2 text-center">Playoff% if Away</th>
                </tr>
              </thead>
              <tbody>
                {impacts.map((imp) => (
                  <tr key={imp.affected_team_id} className="border-b border-steel-gray/20 hover:bg-charcoal/50">
                    <td className="px-3 py-2 font-semibold">{imp.school_name}</td>
                    <td className="px-3 py-2 text-center font-mono">{imp.rating_if_home_wins.toFixed(2)}</td>
                    <td className="px-3 py-2 text-center font-mono">{imp.rating_if_away_wins.toFixed(2)}</td>
                    <td className="px-3 py-2 text-center">{imp.rank_if_home_wins}</td>
                    <td className="px-3 py-2 text-center">{imp.rank_if_away_wins}</td>
                    <td className="px-3 py-2 text-center">{imp.playoff_prob_if_home_wins.toFixed(1)}%</td>
                    <td className="px-3 py-2 text-center">{imp.playoff_prob_if_away_wins.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}
