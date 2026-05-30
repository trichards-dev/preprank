import Link from "next/link";
import type { Game, GameForecast } from "@/lib/api";
import WinProbabilityWithCI from "@/components/WinProbabilityWithCI";

interface GameCardProps {
  game: Game;
  forecast?: GameForecast | null;
}

export default function GameCard({ game, forecast }: GameCardProps) {
  const isFinal = game.status === "final";
  const showForecast = !isFinal && forecast !== undefined;

  return (
    <Link
      href={`/games/${game.id}`}
      className="block rounded-lg border border-steel-gray/30 bg-charcoal p-4 transition-colors hover:border-crimson/50"
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs uppercase tracking-wide text-steel-gray">
          {game.is_playoff ? "Playoff" : game.is_district ? "District" : "Non-District"}
          {game.week_number && ` · Week ${game.week_number}`}
        </span>
        <span
          className={`text-xs font-bold uppercase ${isFinal ? "text-steel-gray" : "text-green-500"}`}
        >
          {game.status}
        </span>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="font-semibold truncate flex-1">
            {game.home_team_name || `Team #${game.home_team_id}`}
          </span>
          <span className={`font-mono font-bold text-lg ml-4 ${isFinal && game.home_score !== null && game.away_score !== null && game.home_score > game.away_score ? "text-white" : "text-steel-gray"}`}>
            {game.home_score ?? "-"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-semibold truncate flex-1">
            {game.away_team_name || `Team #${game.away_team_id}`}
          </span>
          <span className={`font-mono font-bold text-lg ml-4 ${isFinal && game.away_score !== null && game.home_score !== null && game.away_score > game.home_score ? "text-white" : "text-steel-gray"}`}>
            {game.away_score ?? "-"}
          </span>
        </div>
      </div>

      {showForecast && (
        <div className="mt-3 border-t border-steel-gray/20 pt-3">
          <WinProbabilityWithCI
            homeTeamName={game.home_team_name || `Team #${game.home_team_id}`}
            awayTeamName={game.away_team_name || `Team #${game.away_team_id}`}
            forecast={forecast?.forecast ?? null}
            forecastUnavailableReason={forecast?.forecast_unavailable_reason ?? null}
            sourceDataCaveat={forecast?.source_data_caveat ?? null}
            variant="compact"
            hideTeamNames
          />
        </div>
      )}

      {game.game_date && (
        <div className="mt-2 text-xs text-steel-gray">
          {new Date(game.game_date + "T00:00:00").toLocaleDateString("en-US", {
            weekday: "short",
            month: "short",
            day: "numeric",
          })}
        </div>
      )}
    </Link>
  );
}
