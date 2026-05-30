import WinProbabilityWithCI from "@/components/WinProbabilityWithCI";
import type { PickemGame, GameForecast } from "@/lib/api";

interface PostPickRevealCardProps {
  game: PickemGame;
  pickedTeamId: number;
  pickedTeamName: string | null;
  forecast: GameForecast | null;
}

function pickedSideLabel(game: PickemGame, pickedTeamId: number): string {
  if (game.home_team_id === pickedTeamId) return "HOME";
  if (game.away_team_id === pickedTeamId) return "AWAY";
  return "";
}

function modelPickedTeamId(game: PickemGame, forecast: GameForecast | null): number | null {
  if (!forecast?.forecast) return null;
  const homeProb = forecast.forecast.home_win_probability;
  if (homeProb === 50) return null;
  return homeProb > 50 ? game.home_team_id : game.away_team_id;
}

export default function PostPickRevealCard({
  game,
  pickedTeamId,
  pickedTeamName,
  forecast,
}: PostPickRevealCardProps) {
  const pickedTeam = pickedTeamName ?? `Team #${pickedTeamId}`;
  const pickedSide = pickedSideLabel(game, pickedTeamId);
  const modelPickTeamId = modelPickedTeamId(game, forecast);

  const canAssessAgreement = forecast?.forecast !== null && forecast?.forecast !== undefined && modelPickTeamId !== null;
  const agreed = canAssessAgreement && modelPickTeamId === pickedTeamId;

  return (
    <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">
          {game.home_team_name} vs {game.away_team_name}
        </div>
        {game.game_date && (
          <div className="font-body text-xs text-silver-print">
            {new Date(game.game_date + "T00:00:00").toLocaleDateString("en-US", {
              weekday: "short",
              month: "short",
              day: "numeric",
            })}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-steel-gray/30 bg-charcoal p-4">
          <div className="font-body text-xs uppercase tracking-wide text-silver-print mb-2">
            Your Pick
          </div>
          <div className="font-display text-2xl font-bold text-white">
            {pickedTeam}
          </div>
          {pickedSide && (
            <div className="mt-1 font-body text-xs text-silver-print">{pickedSide}</div>
          )}
        </div>

        <div className="rounded-lg border border-steel-gray/30 bg-charcoal p-4">
          <div className="font-body text-xs uppercase tracking-wide text-silver-print mb-2">
            PrepRank Predicts
          </div>
          <WinProbabilityWithCI
            homeTeamName={game.home_team_name || `Team #${game.home_team_id}`}
            awayTeamName={game.away_team_name || `Team #${game.away_team_id}`}
            forecast={forecast?.forecast ?? null}
            forecastUnavailableReason={forecast?.forecast_unavailable_reason ?? null}
            sourceDataCaveat={forecast?.source_data_caveat ?? null}
            variant="compact"
          />
        </div>
      </div>

      {canAssessAgreement && (
        <div className="mt-3 flex justify-center">
          <span
            className={`inline-flex items-center rounded-full px-3 py-1 font-body text-xs uppercase tracking-wide ${
              agreed
                ? "bg-crimson/20 text-white"
                : "bg-steel-gray/20 text-silver-print"
            }`}
          >
            {agreed ? "You agreed with PrepRank" : "You disagreed with PrepRank"}
          </span>
        </div>
      )}
    </div>
  );
}
