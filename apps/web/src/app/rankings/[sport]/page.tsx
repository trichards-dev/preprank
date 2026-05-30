"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { fetchLatestWeek, fetchRankings, RankedTeam } from "@/lib/api";
import { sportNameFromSlug } from "@/lib/sports";
import RankingsTable from "@/components/RankingsTable";

const DIVISIONS = [
  { value: "", label: "All Divisions" },
  { value: "I", label: "Division I (5A)" },
  { value: "II", label: "Division II (4A)" },
  { value: "III", label: "Division III (3A)" },
  { value: "IV", label: "Division IV (2A)" },
  { value: "V", label: "Division V (1A)" },
];

const SEASON_YEAR = 2025;

export default function RankingsSportPage() {
  const params = useParams();
  const slug = params.sport as string;
  const sportName = sportNameFromSlug(slug);

  const [allRankings, setAllRankings] = useState<RankedTeam[]>([]);
  const [latestWeek, setLatestWeek] = useState<number | null>(null);
  const [noSeasonData, setNoSeasonData] = useState(false);
  const [division, setDivision] = useState("");
  const [selectStatus, setSelectStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sportName) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setNoSeasonData(false);

    (async () => {
      try {
        const { latest_week } = await fetchLatestWeek(sportName, SEASON_YEAR);
        if (cancelled) return;
        if (latest_week === null) {
          setNoSeasonData(true);
          setAllRankings([]);
          setLatestWeek(null);
          return;
        }
        setLatestWeek(latest_week);
        const rankings = await fetchRankings(
          sportName,
          SEASON_YEAR,
          latest_week,
          division || undefined,
        );
        if (cancelled) return;
        setAllRankings(rankings);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        // 404 from /latest-week → unknown sport at the API. Same empty
        // UX as a valid sport with no current-season data.
        if (msg.includes("404")) {
          setNoSeasonData(true);
          setAllRankings([]);
          setLatestWeek(null);
          return;
        }
        setError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [sportName, division]);

  // Client-side filter for select status, then re-rank sequentially
  const rankings = (() => {
    let filtered = allRankings;
    if (selectStatus) {
      filtered = allRankings.filter((r) => r.select_status === selectStatus);
    }
    return filtered.map((r, i) => ({ ...r, rank: i + 1 }));
  })();

  if (!sportName) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-8">
        <p className="text-crimson">Unknown sport: {slug}</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1
        className="mb-6 text-4xl font-bold tracking-tight"
        style={{ fontFamily: "var(--font-display)" }}
      >
        <span className="text-white">{sportName.toUpperCase()}</span>
        <span className="text-crimson"> RANKINGS</span>
      </h1>

      <div className="mb-6 flex items-center gap-4 flex-wrap">
        <select
          value={division}
          onChange={(e) => setDivision(e.target.value)}
          className="rounded border border-steel-gray bg-charcoal px-3 py-2 text-white focus:border-crimson focus:outline-none"
        >
          {DIVISIONS.map((d) => (
            <option key={d.value} value={d.value}>{d.label}</option>
          ))}
        </select>
        <select
          value={selectStatus}
          onChange={(e) => setSelectStatus(e.target.value)}
          className="rounded border border-steel-gray bg-charcoal px-3 py-2 text-white focus:border-crimson focus:outline-none"
        >
          <option value="">All Schools</option>
          <option value="Select">Select</option>
          <option value="Non-Select">Non-Select</option>
        </select>
        <span className="text-steel-gray text-sm">
          {SEASON_YEAR} Season
          {latestWeek !== null && ` · Week ${latestWeek}`}
          {rankings.length > 0 && ` · ${rankings.length} teams`}
        </span>
      </div>

      {loading && <p className="text-steel-gray">Loading rankings...</p>}
      {error && <p className="text-crimson">Error: {error}</p>}
      {!loading && !error && noSeasonData && (
        <p className="text-steel-gray">
          No rankings yet &mdash; {sportName} {SEASON_YEAR} hasn&apos;t started.
        </p>
      )}
      {!loading && !error && !noSeasonData && <RankingsTable rankings={rankings} />}
    </main>
  );
}
