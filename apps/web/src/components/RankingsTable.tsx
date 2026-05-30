"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import type { RankedTeam } from "@/lib/api";

interface RankingsTableProps {
  rankings: RankedTeam[];
  playoffSpots?: number;
}

type SortKey = "rank" | "school_name" | "power_rating" | "strength_factor" | "division";

export default function RankingsTable({ rankings, playoffSpots = 8 }: RankingsTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [sortAsc, setSortAsc] = useState(true);
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    let data = rankings;
    if (search) {
      const q = search.toLowerCase();
      data = data.filter((r) => r.school_name.toLowerCase().includes(q));
    }
    const sorted = [...data].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "school_name") {
        cmp = a.school_name.localeCompare(b.school_name);
      } else {
        const av = a[sortKey] ?? 0;
        const bv = b[sortKey] ?? 0;
        cmp = (av as number) - (bv as number);
      }
      return sortAsc ? cmp : -cmp;
    });
    return sorted;
  }, [rankings, sortKey, sortAsc, search]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(key === "school_name");
    }
  }

  const headerClass = "px-3 py-3 cursor-pointer select-none hover:text-white transition-colors";

  return (
    <div>
      <input
        type="text"
        placeholder="Search schools..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="mb-4 w-full max-w-sm rounded border border-steel-gray bg-charcoal px-3 py-2 text-white placeholder-steel-gray focus:border-crimson focus:outline-none"
      />

      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-steel-gray text-sm uppercase tracking-wide text-steel-gray">
              <th className={`${headerClass} w-16`} onClick={() => toggleSort("rank")}>
                Rank {sortKey === "rank" && (sortAsc ? "↑" : "↓")}
              </th>
              <th className={headerClass} onClick={() => toggleSort("school_name")}>
                School {sortKey === "school_name" && (sortAsc ? "↑" : "↓")}
              </th>
              <th className={`${headerClass} w-20`} onClick={() => toggleSort("division")}>
                Div {sortKey === "division" && (sortAsc ? "↑" : "↓")}
              </th>
              <th className={`${headerClass} w-24`}>Class</th>
              <th className={`${headerClass} w-24 text-right`} onClick={() => toggleSort("power_rating")}>
                Rating {sortKey === "power_rating" && (sortAsc ? "↑" : "↓")}
              </th>
              <th className={`${headerClass} w-20 text-right`} onClick={() => toggleSort("strength_factor")}>
                SoS {sortKey === "strength_factor" && (sortAsc ? "↑" : "↓")}
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr
                key={r.team_id}
                className={`border-b transition-colors hover:bg-charcoal/50 ${
                  r.rank <= playoffSpots
                    ? "border-crimson/20"
                    : "border-steel-gray/20"
                }`}
              >
                <td className={`px-3 py-3 font-bold ${r.rank <= playoffSpots ? "text-crimson" : "text-steel-gray"}`}>
                  {r.rank}
                </td>
                <td className="px-3 py-3">
                  <Link href={`/teams/${r.team_id}`} className="font-semibold hover:text-crimson transition-colors">
                    {r.school_name}
                  </Link>
                </td>
                <td className="px-3 py-3 text-steel-gray">{r.division ?? "—"}</td>
                <td className="px-3 py-3 text-steel-gray">{r.classification ?? "—"}</td>
                <td className="px-3 py-3 text-right font-mono">{r.power_rating.toFixed(2)}</td>
                <td className="px-3 py-3 text-right font-mono text-steel-gray">
                  {r.strength_factor?.toFixed(2) ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <p className="mt-4 text-center text-steel-gray">No results found.</p>
        )}
      </div>
    </div>
  );
}
