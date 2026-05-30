import Link from "next/link";
import type { PremiumDetail } from "@/lib/api";

interface ModelDetailsExpandProps {
  premiumDetail: PremiumDetail;
  sport: string;
  panelId: string;
  labelledById: string;
}

export default function ModelDetailsExpand({
  premiumDetail,
  sport,
  panelId,
  labelledById,
}: ModelDetailsExpandProps) {
  const reliability = premiumDetail.predicted_decile_reliability;
  const coefs = Object.entries(premiumDetail.model_coefficients);
  const displayDecile = premiumDetail.predicted_decile + 1;

  return (
    <div
      id={panelId}
      role="region"
      aria-labelledby={labelledById}
      className="mt-3 space-y-3 font-body"
    >
      <div>
        <div className="font-display text-[0.65rem] uppercase tracking-wide text-silver-print mb-1">
          Model coefficients · {sport}
        </div>
        <table className="w-full text-xs">
          <tbody>
            {coefs.map(([k, v]) => (
              <tr key={k} className="border-b border-steel-gray/15">
                <td className="py-1 text-silver-print truncate pr-2">{k}</td>
                <td className="py-1 text-right text-white font-mono whitespace-nowrap">
                  {v > 0 ? "+" : ""}
                  {v.toFixed(3)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded border border-steel-gray/20 p-2">
          <div className="font-display uppercase tracking-wide text-silver-print text-[0.65rem]">
            Home typical decile
          </div>
          <div className="mt-1 font-display text-lg text-white">
            {premiumDetail.home_typical_decile !== null
              ? `D${premiumDetail.home_typical_decile}`
              : "—"}
          </div>
        </div>
        <div className="rounded border border-steel-gray/20 p-2">
          <div className="font-display uppercase tracking-wide text-silver-print text-[0.65rem]">
            Away typical decile
          </div>
          <div className="mt-1 font-display text-lg text-white">
            {premiumDetail.away_typical_decile !== null
              ? `D${premiumDetail.away_typical_decile}`
              : "—"}
          </div>
        </div>
      </div>

      <div className="rounded border border-steel-gray/20 p-2 text-xs">
        <div className="font-display uppercase tracking-wide text-silver-print text-[0.65rem]">
          Predicted decile · D{displayDecile} reliability
        </div>
        {reliability ? (
          <div className="mt-1 grid grid-cols-4 gap-1 text-silver-print">
            <div>
              <div className="text-[0.6rem] uppercase">n</div>
              <div className="text-white font-mono">{reliability.n_games}</div>
            </div>
            <div>
              <div className="text-[0.6rem] uppercase">gap</div>
              <div className="text-white font-mono">{reliability.gap.toFixed(3)}</div>
            </div>
            <div>
              <div className="text-[0.6rem] uppercase">pred</div>
              <div className="text-white font-mono">
                {reliability.mean_predicted !== null
                  ? reliability.mean_predicted.toFixed(3)
                  : "—"}
              </div>
            </div>
            <div>
              <div className="text-[0.6rem] uppercase">obs</div>
              <div className="text-white font-mono">
                {reliability.mean_observed !== null
                  ? reliability.mean_observed.toFixed(3)
                  : "—"}
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-1 text-silver-print">Reliability data unavailable</div>
        )}
      </div>

      <Link
        href={premiumDetail.methodology_deep_link}
        className="inline-block text-xs text-crimson hover:underline font-body"
      >
        Read methodology for {sport} D{displayDecile} →
      </Link>
    </div>
  );
}
