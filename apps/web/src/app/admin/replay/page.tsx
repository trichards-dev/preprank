"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import RankingsTable from "@/components/RankingsTable";
import GameCard from "@/components/GameCard";
import { fetchRankings, fetchGames } from "@/lib/api";
import type { RankedTeam, Game } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import taskBank from "./task_bank.json";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

const SPORTS = [
  "Football",
  "Volleyball",
  "Boys Basketball",
  "Girls Basketball",
  "Baseball",
  "Softball",
  "Boys Soccer",
  "Girls Soccer",
] as const;

const SPORT_NAME_TO_ID: Record<string, number> = {
  Football: 1,
  Volleyball: 2,
  "Boys Basketball": 5,
  "Girls Basketball": 6,
  Baseball: 11,
  Softball: 12,
  "Boys Soccer": 13,
  "Girls Soccer": 14,
};

const SPORT_SCOPE: Record<string, string> = {
  Football: "football",
  Volleyball: "volleyball",
  "Boys Basketball": "boys-basketball",
  "Girls Basketball": "girls-basketball",
  Baseball: "baseball",
  Softball: "softball",
  "Boys Soccer": "boys-soccer",
  "Girls Soccer": "girls-soccer",
};

const SEASONS = [2025, 2024, 2023, 2022, 2021] as const;

interface Task {
  id: string;
  scope: string;
  text: string;
}

const TASKS = taskBank as Task[];

function pickRandomTask(sportName: string): Task {
  const scope = SPORT_SCOPE[sportName];
  const candidates = TASKS.filter((t) => t.scope === "general" || t.scope === scope);
  const pool = candidates.length > 0 ? candidates : TASKS;
  return pool[Math.floor(Math.random() * pool.length)];
}

export default function ReplayQAPage() {
  const { getToken } = useAuth();

  // Form controls
  const [sportName, setSportName] = useState<string>("Football");
  const [season, setSeason] = useState<number>(2025);
  const [week, setWeek] = useState<number>(8);

  // Data loaded for replay
  const [loadedSport, setLoadedSport] = useState<string>("Football");
  const [loadedSeason, setLoadedSeason] = useState<number>(2025);
  const [loadedWeek, setLoadedWeek] = useState<number>(8);

  const [beforeRankings, setBeforeRankings] = useState<RankedTeam[]>([]);
  const [afterRankings, setAfterRankings] = useState<RankedTeam[]>([]);
  const [weekGames, setWeekGames] = useState<Game[]>([]);
  const [dataLoaded, setDataLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingData, setLoadingData] = useState(false);

  // Task + timer
  const [currentTask, setCurrentTask] = useState<Task | null>(null);
  const [timerStart, setTimerStart] = useState<number | null>(null);
  const [timerEnd, setTimerEnd] = useState<number | null>(null);
  const [now, setNow] = useState<number>(Date.now());

  // Feedback form
  const [completed, setCompleted] = useState<"yes" | "no" | "">("");
  const [bugFound, setBugFound] = useState(false);
  const [bugSeverity, setBugSeverity] = useState<number>(2);
  const [featureGap, setFeatureGap] = useState(false);
  const [featureGapText, setFeatureGapText] = useState("");
  const [feedbackOpen, setFeedbackOpen] = useState(true);
  const [submitState, setSubmitState] = useState<"idle" | "submitting" | "ok" | "err">("idle");
  const [submitMsg, setSubmitMsg] = useState<string>("");

  // Tick the clock once a second while the timer is running.
  useEffect(() => {
    if (timerStart === null || timerEnd !== null) return;
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, [timerStart, timerEnd]);

  const elapsedSeconds = useMemo(() => {
    if (timerStart === null) return 0;
    const stop = timerEnd ?? now;
    return Math.max(0, Math.round((stop - timerStart) / 1000));
  }, [timerStart, timerEnd, now]);

  const loadWeek = useCallback(async () => {
    setLoadingData(true);
    setLoadError(null);
    setDataLoaded(false);
    try {
      const [before, after, games] = await Promise.all([
        fetchRankings(sportName, season, week),
        fetchRankings(sportName, season, week + 1),
        fetchGames({ season_year: season, sport: sportName, week_number: week }),
      ]);
      setBeforeRankings(before);
      setAfterRankings(after);
      setWeekGames(games);
      setLoadedSport(sportName);
      setLoadedSeason(season);
      setLoadedWeek(week);
      setCurrentTask(pickRandomTask(sportName));
      setTimerStart(null);
      setTimerEnd(null);
      setCompleted("");
      setBugFound(false);
      setBugSeverity(2);
      setFeatureGap(false);
      setFeatureGapText("");
      setSubmitState("idle");
      setSubmitMsg("");
      setDataLoaded(true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load week data";
      setLoadError(msg);
    } finally {
      setLoadingData(false);
    }
  }, [sportName, season, week]);

  const startTimer = () => {
    setTimerStart(Date.now());
    setTimerEnd(null);
  };

  const stopTimer = () => {
    if (timerStart !== null && timerEnd === null) {
      setTimerEnd(Date.now());
    }
  };

  const submitSession = async () => {
    if (!currentTask) {
      setSubmitState("err");
      setSubmitMsg("Load a week first to pick a task.");
      return;
    }
    if (completed === "") {
      setSubmitState("err");
      setSubmitMsg("Mark the task as completed (yes/no) before submitting.");
      return;
    }
    setSubmitState("submitting");
    setSubmitMsg("");

    // Make sure we record a stable elapsed value at submit time.
    if (timerStart !== null && timerEnd === null) {
      stopTimer();
    }

    const payload = {
      sport_id: SPORT_NAME_TO_ID[loadedSport],
      season_year: loadedSeason,
      week_number: loadedWeek,
      task_text: currentTask.text,
      task_completed: completed === "yes",
      time_to_complete_seconds: timerStart !== null ? elapsedSeconds : null,
      bug_found: bugFound,
      bug_severity: bugFound ? bugSeverity : null,
      feature_gap_text: featureGap ? featureGapText.trim() || null : null,
      screenshot_url: null,
    };

    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}/api/v1/admin/replay/sessions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}${txt ? `: ${txt}` : ""}`);
      }
      setSubmitState("ok");
      setSubmitMsg("Saved. Loading a new task…");
      // Roll to a new task on success.
      setCurrentTask(pickRandomTask(loadedSport));
      setTimerStart(null);
      setTimerEnd(null);
      setCompleted("");
      setBugFound(false);
      setBugSeverity(2);
      setFeatureGap(false);
      setFeatureGapText("");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Submit failed";
      setSubmitState("err");
      setSubmitMsg(msg);
    }
  };

  const rerollTask = () => {
    if (!dataLoaded) return;
    setCurrentTask(pickRandomTask(loadedSport));
    setTimerStart(null);
    setTimerEnd(null);
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 text-white">
      <header className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold">Replay QA</h1>
          <p className="text-sm text-steel-gray">
            Admin-only. Step back to a historical week, run a task, and capture what worked / what didn&apos;t.
          </p>
        </div>
      </header>

      {/* Control bar */}
      <section className="mb-6 rounded-lg border border-steel-gray/30 bg-charcoal p-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-steel-gray">
            Sport
            <select
              value={sportName}
              onChange={(e) => setSportName(e.target.value)}
              className="rounded border border-steel-gray bg-charcoal px-2 py-2 text-sm text-white focus:border-crimson focus:outline-none"
            >
              {SPORTS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-steel-gray">
            Season
            <select
              value={season}
              onChange={(e) => setSeason(Number(e.target.value))}
              className="rounded border border-steel-gray bg-charcoal px-2 py-2 text-sm text-white focus:border-crimson focus:outline-none"
            >
              {SEASONS.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-steel-gray">
            Week
            <input
              type="number"
              min={1}
              max={20}
              value={week}
              onChange={(e) => setWeek(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
              className="rounded border border-steel-gray bg-charcoal px-2 py-2 text-sm text-white focus:border-crimson focus:outline-none"
            />
          </label>

          <div className="flex items-end">
            <button
              onClick={loadWeek}
              disabled={loadingData}
              className="w-full rounded bg-crimson px-4 py-2 text-sm font-semibold text-white hover:bg-crimson/80 disabled:opacity-50"
            >
              {loadingData ? "Loading…" : "Load Week"}
            </button>
          </div>
        </div>
        {loadError && (
          <p className="mt-3 text-sm text-red-400">Load error: {loadError}</p>
        )}
      </section>

      {/* Task panel */}
      <section className="mb-6 rounded-lg border border-steel-gray/30 bg-charcoal p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wide text-steel-gray">Task</div>
            {currentTask ? (
              <p className="text-sm md:text-base">{currentTask.text}</p>
            ) : (
              <p className="text-sm text-steel-gray">Load a week to get a task.</p>
            )}
            {currentTask && (
              <p className="mt-1 text-xs text-steel-gray">
                {currentTask.id} · scope: {currentTask.scope}
              </p>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="font-mono text-lg">{elapsedSeconds}s</div>
            <div className="flex gap-2">
              <button
                onClick={startTimer}
                disabled={!currentTask || (timerStart !== null && timerEnd === null)}
                className="rounded border border-crimson px-3 py-1 text-xs font-semibold text-crimson hover:bg-crimson/10 disabled:opacity-40"
              >
                {timerStart === null ? "Start" : "Restart"}
              </button>
              <button
                onClick={stopTimer}
                disabled={timerStart === null || timerEnd !== null}
                className="rounded border border-steel-gray px-3 py-1 text-xs font-semibold text-steel-gray hover:text-white disabled:opacity-40"
              >
                Stop
              </button>
              <button
                onClick={rerollTask}
                disabled={!dataLoaded}
                className="rounded border border-steel-gray px-3 py-1 text-xs font-semibold text-steel-gray hover:text-white disabled:opacity-40"
              >
                New task
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Two-pane replay */}
      {dataLoaded ? (
        <section className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="rounded-lg border border-steel-gray/30 bg-charcoal p-4">
            <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-steel-gray">
              What a user saw at Week {loadedWeek}
            </h2>
            <RankingsTable rankings={beforeRankings} />
            <div className="mt-4">
              <h3 className="mb-2 text-xs uppercase tracking-wide text-steel-gray">
                Week {loadedWeek} schedule (as known then)
              </h3>
              <div className="space-y-2">
                {weekGames.map((g) => {
                  const blind: Game = { ...g, home_score: null, away_score: null, status: "scheduled" };
                  return <GameCard key={`b-${g.id}`} game={blind} />;
                })}
                {weekGames.length === 0 && (
                  <p className="text-xs text-steel-gray">No games found for this week.</p>
                )}
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-steel-gray/30 bg-charcoal p-4">
            <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-steel-gray">
              Actual outcomes after Week {loadedWeek}
            </h2>
            <RankingsTable rankings={afterRankings} />
            <div className="mt-4">
              <h3 className="mb-2 text-xs uppercase tracking-wide text-steel-gray">
                Week {loadedWeek} results
              </h3>
              <div className="space-y-2">
                {weekGames.map((g) => (
                  <GameCard key={`a-${g.id}`} game={g} />
                ))}
                {weekGames.length === 0 && (
                  <p className="text-xs text-steel-gray">No games found for this week.</p>
                )}
              </div>
            </div>
          </div>
        </section>
      ) : (
        <p className="mb-6 text-sm text-steel-gray">
          Pick a sport/season/week and click <span className="text-white">Load Week</span> to begin.
        </p>
      )}

      {/* Feedback */}
      <section className="mb-12 rounded-lg border border-steel-gray/30 bg-charcoal">
        <button
          type="button"
          onClick={() => setFeedbackOpen((v) => !v)}
          className="flex w-full items-center justify-between px-4 py-3 text-left"
        >
          <span className="text-sm font-semibold uppercase tracking-wide">Feedback</span>
          <span className="text-xs text-steel-gray">{feedbackOpen ? "Hide" : "Show"}</span>
        </button>

        {feedbackOpen && (
          <div className="border-t border-steel-gray/30 px-4 py-4 space-y-4">
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-steel-gray">Completed?</div>
              <div className="flex gap-3">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="completed"
                    checked={completed === "yes"}
                    onChange={() => setCompleted("yes")}
                  />
                  Yes
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="completed"
                    checked={completed === "no"}
                    onChange={() => setCompleted("no")}
                  />
                  No
                </label>
              </div>
            </div>

            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-steel-gray">
                Time to complete (seconds)
              </div>
              <div className="font-mono text-sm">{timerStart === null ? "—" : elapsedSeconds}</div>
            </div>

            <div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={bugFound}
                  onChange={(e) => setBugFound(e.target.checked)}
                />
                Bug found
              </label>
              {bugFound && (
                <div className="mt-2 flex items-center gap-2">
                  <span className="text-xs uppercase tracking-wide text-steel-gray">Severity</span>
                  {[1, 2, 3, 4].map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setBugSeverity(s)}
                      className={`rounded border px-2 py-1 text-xs ${
                        bugSeverity === s
                          ? "border-crimson bg-crimson/20 text-white"
                          : "border-steel-gray text-steel-gray hover:text-white"
                      }`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={featureGap}
                  onChange={(e) => setFeatureGap(e.target.checked)}
                />
                Feature gap
              </label>
              {featureGap && (
                <textarea
                  value={featureGapText}
                  onChange={(e) => setFeatureGapText(e.target.value)}
                  rows={3}
                  placeholder="What was missing that would have made the task easier?"
                  className="mt-2 w-full rounded border border-steel-gray bg-charcoal px-2 py-2 text-sm text-white focus:border-crimson focus:outline-none"
                />
              )}
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={submitSession}
                disabled={submitState === "submitting" || !dataLoaded || !currentTask}
                className="rounded bg-crimson px-4 py-2 text-sm font-semibold text-white hover:bg-crimson/80 disabled:opacity-50"
              >
                {submitState === "submitting" ? "Submitting…" : "Submit"}
              </button>
              {submitState === "ok" && (
                <span className="text-sm text-green-400">{submitMsg}</span>
              )}
              {submitState === "err" && (
                <span className="text-sm text-red-400">{submitMsg}</span>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
