import type {
  ForecastBlock,
  ForecastUnavailableReason,
  SourceDataCaveat,
} from "@/lib/api";

type Variant = "compact" | "expanded";

interface WinProbabilityWithCIProps {
  homeTeamName: string;
  awayTeamName: string;
  forecast: ForecastBlock | null;
  forecastUnavailableReason?: ForecastUnavailableReason | null;
  sourceDataCaveat?: SourceDataCaveat | null;
  variant?: Variant;
  hideTeamNames?: boolean;
}

const UNAVAILABLE_REASON_PROSE: Record<ForecastUnavailableReason, string> = {
  INSUFFICIENT_PRIOR_DATA: "Insufficient prior data",
  RECENTLY_SCHEDULED: "Recently scheduled — model still warming up",
  SPORT_CALIBRATION_PENDING: "Sport calibration pending",
  COLD_START_TEAM: "One or both teams new to the model",
  OTHER: "Forecast unavailable",
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function ariaLabel(
  homeTeamName: string,
  awayTeamName: string,
  forecast: ForecastBlock,
): string {
  return `${homeTeamName} ${forecast.home_win_probability}% home win probability, ${forecast.confidence_tier_label} tier, confidence range ${forecast.home_win_probability_ci_low} to ${forecast.home_win_probability_ci_high} percent. ${awayTeamName} is the away team.`;
}

function TierChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-steel-gray/20 px-2.5 py-0.5 font-body text-xs uppercase tracking-wide text-silver-print">
      {label}
    </span>
  );
}

function CaveatBlock({ caveat }: { caveat: SourceDataCaveat }) {
  return (
    <div className="mt-2 flex items-start gap-1.5 font-body text-xs text-silver-print">
      <span aria-hidden="true" className="leading-none">ⓘ</span>
      <span>{caveat.prose}</span>
    </div>
  );
}

function ForecastBar({
  forecast,
  expanded,
}: {
  forecast: ForecastBlock;
  expanded: boolean;
}) {
  const p = forecast.home_win_probability;
  const ciLow = clamp(forecast.home_win_probability_ci_low, 0, 100);
  const ciHigh = clamp(forecast.home_win_probability_ci_high, 0, 100);
  const bandLeft = ciLow;
  const bandWidth = Math.max(0, ciHigh - ciLow);
  const fillWidth = clamp(p, 0, 100);
  const barHeight = expanded ? "h-3" : "h-2";

  return (
    <div
      className={`relative ${barHeight} w-full overflow-hidden rounded-full bg-steel-gray/20`}
    >
      <div
        className={`absolute left-0 top-0 ${barHeight} rounded-full bg-crimson transition-all`}
        style={{ width: `${fillWidth}%` }}
      />
      <div
        className={`absolute top-0 ${barHeight} bg-steel-gray/40 transition-all`}
        style={{ left: `${bandLeft}%`, width: `${bandWidth}%` }}
        aria-hidden="true"
      />
    </div>
  );
}

function ForecastUnavailable({
  reason,
}: {
  reason: ForecastUnavailableReason | null | undefined;
}) {
  const prose = reason ? UNAVAILABLE_REASON_PROSE[reason] : "Forecast unavailable";
  return (
    <div className="font-body text-xs text-silver-print">
      <div>Forecast unavailable for this game</div>
      <div className="mt-0.5">{prose}</div>
    </div>
  );
}

export default function WinProbabilityWithCI({
  homeTeamName,
  awayTeamName,
  forecast,
  forecastUnavailableReason = null,
  sourceDataCaveat = null,
  variant = "compact",
  hideTeamNames = false,
}: WinProbabilityWithCIProps) {
  const expanded = variant === "expanded";

  if (forecast === null) {
    if (hideTeamNames) {
      return (
        <div
          className="space-y-2"
          role="region"
          aria-label="Forecast unavailable"
        >
          <div className="flex items-center justify-center gap-2 py-1">
            <span className="font-display text-lg text-silver-print">?</span>
            <span className="font-body text-sm text-silver-print">vs</span>
            <span className="font-display text-lg text-silver-print">?</span>
          </div>
          <ForecastUnavailable reason={forecastUnavailableReason} />
        </div>
      );
    }
    return (
      <div
        className="space-y-2"
        role="region"
        aria-label="Forecast unavailable"
      >
        <div className="flex items-center justify-between">
          <span className="font-body text-sm">{homeTeamName}</span>
          <span className="font-display text-lg text-silver-print">?</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-body text-sm">{awayTeamName}</span>
          <span className="font-display text-lg text-silver-print">?</span>
        </div>
        <ForecastUnavailable reason={forecastUnavailableReason} />
      </div>
    );
  }

  const awayProb = clamp(100 - forecast.home_win_probability, 0, 100);

  if (hideTeamNames) {
    return (
      <div
        className="space-y-2"
        role="img"
        aria-label={ariaLabel(homeTeamName, awayTeamName, forecast)}
      >
        <div className="flex items-baseline justify-between">
          <span
            className={`font-display font-bold text-white ${expanded ? "text-2xl" : "text-lg"}`}
          >
            {forecast.home_win_probability}%
          </span>
          <span
            className={`font-display font-bold text-silver-print ${expanded ? "text-2xl" : "text-lg"}`}
          >
            {awayProb}%
          </span>
        </div>
        <ForecastBar forecast={forecast} expanded={expanded} />
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <TierChip label={forecast.confidence_tier_label} />
          {expanded && (
            <span className="font-body text-xs text-silver-print">
              {forecast.home_win_probability_ci_low}% — {forecast.home_win_probability_ci_high}%
            </span>
          )}
        </div>
        {sourceDataCaveat && <CaveatBlock caveat={sourceDataCaveat} />}
      </div>
    );
  }

  return (
    <div
      className="space-y-2"
      role="img"
      aria-label={ariaLabel(homeTeamName, awayTeamName, forecast)}
    >
      <div className="flex items-center justify-between">
        <span className="font-body text-sm font-semibold">{homeTeamName}</span>
        <span
          className={`font-display font-bold text-white ${expanded ? "text-2xl" : "text-lg"}`}
        >
          {forecast.home_win_probability}%
        </span>
      </div>
      <ForecastBar forecast={forecast} expanded={expanded} />
      <div className="flex items-center justify-between">
        <span className="font-body text-sm font-semibold">{awayTeamName}</span>
        <span
          className={`font-display font-bold text-silver-print ${expanded ? "text-2xl" : "text-lg"}`}
        >
          {awayProb}%
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <TierChip label={forecast.confidence_tier_label} />
        {expanded && (
          <span className="font-body text-xs text-silver-print">
            {forecast.home_win_probability_ci_low}% — {forecast.home_win_probability_ci_high}%
          </span>
        )}
      </div>
      {sourceDataCaveat && <CaveatBlock caveat={sourceDataCaveat} />}
    </div>
  );
}
