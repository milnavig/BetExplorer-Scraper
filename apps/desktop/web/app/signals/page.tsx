"use client";

import {
  Activity,
  CalendarDays,
  Clock3,
  Database,
  Download,
  Filter,
  Play,
  RefreshCcw,
  Search,
  Table2,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Loader2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type SignalTab = "all" | "exact_odds" | "neighbor_odds" | "one_draw";
type SignalScope = "active" | "archive";
type SignalSort = "quality" | "kickoff_asc" | "kickoff_desc" | "sample_desc";

type HistoricalSignal = {
  id: string;
  match_id: string;
  event_id: string;
  league: string | null;
  home_team: string;
  away_team: string;
  kickoff_time: string | null;
  bookmaker: string;
  normalized_bookmaker: string;
  dataset: string;
  signal_type: string;
  current_home_odds: number;
  current_draw_odds: number;
  current_away_odds: number;
  similarity_score: number;
  signal_rank: number;
  sample_size: number;
  home_win_pct: number;
  draw_pct: number;
  away_win_pct: number;
  over_0_5_pct: number;
  over_1_5_pct: number;
  over_2_5_pct: number;
  btts_pct: number;
  double_chance_1x_pct: number;
  double_chance_x2_pct: number;
  double_chance_12_pct: number;
  historical_scores: string[];
};

type HistoricalImportStatus = {
  records: number;
  files: number;
  warnings: number;
  last_import: string | null;
  root_exists: boolean;
};

type SignalDay = {
  date: string;
  matches: number;
  signals: number;
};

type ArchiveDateResult = {
  date: string;
  discovered: number;
  captured: number;
  complete: number;
  failed: number;
  results_captured: number;
  archived: number;
  signals: number;
  matches_evaluated: number;
};

type CaptureProgress = {
  running: boolean;
  trigger: string | null;
  phase: string | null;
  discovered: number;
  due: number;
  queued: number;
  active: number;
  completed: number;
  captured: number;
  failed: number;
  results_captured: number;
  results_checked: number;
  current_event_id: string | null;
  last_error: string | null;
};

type ApiStatus = {
  capture_progress: CaptureProgress;
};

type SignalGroup = {
  id: string;
  match_id: string;
  league: string | null;
  home_team: string;
  away_team: string;
  kickoff_time: string | null;
  signals: HistoricalSignal[];
  bestSignal: HistoricalSignal;
  signalTypes: string[];
  datasets: string[];
  historicalScores: string[];
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

function archiveSignalsPath(date: string, sort: SignalSort) {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  params.set("sort", sort);
  return `/api/signals?${params.toString()}`;
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<HistoricalSignal[]>([]);
  const [status, setStatus] = useState<HistoricalImportStatus | null>(null);
  const [query, setQuery] = useState("");
  const [activeTab, setActiveTab] = useState<SignalTab>("all");
  const [scope, setScope] = useState<SignalScope>("active");
  const [signalDays, setSignalDays] = useState<SignalDay[]>([]);
  const [archiveSignalDate, setArchiveSignalDate] = useState("");
  const [archiveSort, setArchiveSort] = useState<SignalSort>("quality");
  const [archiveDate, setArchiveDate] = useState(() => todayDateSlug());
  const [archiveResult, setArchiveResult] = useState<ArchiveDateResult | null>(null);
  const [archiveProgress, setArchiveProgress] = useState<CaptureProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isBackfilling, setIsBackfilling] = useState(false);
  const [isRecomputing, setIsRecomputing] = useState(false);
  const operationBusy = isBackfilling || isRecomputing;

  const load = async (
    nextScope = scope,
    nextArchiveDate = archiveSignalDate,
    nextArchiveSort = archiveSort,
  ) => {
    setError(null);
    setIsLoading(true);
    const signalPath =
      nextScope === "active"
        ? "/api/signals?actionable_only=true"
        : archiveSignalsPath(nextArchiveDate, nextArchiveSort);
    try {
      const [nextSignals, nextStatus, nextSignalDays] = await Promise.all([
        api<HistoricalSignal[]>(signalPath),
        api<HistoricalImportStatus>("/api/historical/import-status"),
        api<SignalDay[]>("/api/signal-days"),
      ]);
      setSignalDays(nextSignalDays);
      if (nextScope === "archive" && !nextArchiveDate && nextSignalDays.length > 0) {
        setArchiveSignalDate(nextSignalDays[nextSignalDays.length - 1].date);
        return;
      }
      setSignals(nextSignals);
      setStatus(nextStatus);
    } catch (nextError) {
      setError(
        nextError instanceof Error ? nextError.message : "Failed to load signals",
      );
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load(scope, archiveSignalDate, archiveSort);
  }, [scope, archiveSignalDate, archiveSort]);

  useEffect(() => {
    if (!isBackfilling) return;
    let cancelled = false;
    const loadProgress = async () => {
      try {
        const nextStatus = await api<ApiStatus>("/api/status");
        if (!cancelled) setArchiveProgress(nextStatus.capture_progress);
      } catch {
        if (!cancelled) {
          setArchiveProgress((current) =>
            current ? { ...current, last_error: "Progress update failed" } : current,
          );
        }
      }
    };
    void loadProgress();
    const timer = window.setInterval(loadProgress, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [isBackfilling]);

  const archiveDay = signalDays.find((day) => day.date === archiveSignalDate);
  const previousArchiveDate = adjacentSignalDate(signalDays, archiveSignalDate, -1);
  const nextArchiveDate = adjacentSignalDate(signalDays, archiveSignalDate, 1);

  const groups = useMemo(() => groupSignals(signals), [signals]);
  const counts = useMemo(() => signalCounts(groups), [groups]);
  const visibleGroups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return groups.filter((group) => {
      const tabOk =
        activeTab === "all" || group.signalTypes.includes(activeTab);
      const queryOk =
        !needle ||
        [
          group.home_team,
          group.away_team,
          group.league,
          group.datasets.join(" "),
          group.signalTypes.join(" "),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(needle);
      return tabOk && queryOk;
    });
  }, [activeTab, groups, query]);

  const recompute = async () => {
    setError(null);
    setIsRecomputing(true);
    setBusyLabel("Recomputing signals and updating played-match archive");
    try {
      await api("/api/signals/recompute", {
        method: "POST",
        body: JSON.stringify({ archive_played: true }),
      });
      await load(scope, archiveSignalDate, archiveSort);
    } catch (nextError) {
      setError(
        nextError instanceof Error ? nextError.message : "Signal recompute failed",
      );
    } finally {
      setIsRecomputing(false);
      setBusyLabel(null);
    }
  };

  const archiveSelectedDate = async () => {
    setError(null);
    setIsBackfilling(true);
    setBusyLabel(`Backfilling BetExplorer football archive for ${archiveDate}`);
    setArchiveResult(null);
    setArchiveProgress(initialArchiveProgress());
    try {
      const result = await api<ArchiveDateResult>("/api/archive/date", {
        method: "POST",
        body: JSON.stringify({ date: archiveDate }),
      });
      setArchiveResult(result);
      setArchiveProgress((current) => completeArchiveProgress(current, result));
      setArchiveSignalDate(result.date);
      await load(scope, result.date, archiveSort);
    } catch (nextError) {
      setError(
        nextError instanceof Error ? nextError.message : "Date archive failed",
      );
      setArchiveProgress((current) =>
        current
          ? {
              ...current,
              running: false,
              last_error:
                nextError instanceof Error ? nextError.message : "Date archive failed",
            }
          : current,
      );
    } finally {
      setIsBackfilling(false);
      setBusyLabel(null);
    }
  };

  const updateBackfillDate = (value: string) => {
    setArchiveDate(value);
    setArchiveResult(null);
    setArchiveProgress(null);
  };

  return (
    <main className={operationBusy ? "shell is-pending" : "shell"}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">BE</span>
          <div>
            <h1>BetExplorer Monitor</h1>
          </div>
        </div>
        <nav className="nav">
          <a href="/">
            <Activity size={15} />
            Overview
          </a>
          <a href="/match">
            <Table2 size={15} />
            Match page
          </a>
          <a href="/#odds">
            <Database size={15} />
            Odds
          </a>
          <a className="active" href="/signals">
            <Activity size={15} />
            Signals
          </a>
          <a href="/#attempts">
            <Clock3 size={15} />
            Attempts
          </a>
          <a href="/#exports">
            <Download size={15} />
            Exports
          </a>
        </nav>
      </aside>

      <section className="signals-page signal-monitor-page">
        <header className="signals-monitor-topbar">
          <div>
            <h1>Signal monitor</h1>
            <p>
              {visibleGroups.length} visible · {groups.length} matched matches ·{" "}
              {status
                ? `${status.records} historical records from ${status.files} DOCX files / archived matches`
                : "loading historical database"}
            </p>
          </div>
          <div className="signal-actions">
            <button
              type="button"
              className={scope === "active" ? "scope-button active" : "scope-button"}
              onClick={() => setScope("active")}
            >
              <CalendarDays size={15} />
              Actionable
            </button>
            <button
              type="button"
              className={scope === "archive" ? "scope-button active" : "scope-button"}
              onClick={() => setScope("archive")}
            >
              Historical archive
            </button>
          <button type="button" onClick={recompute} disabled={operationBusy} aria-busy={isRecomputing}>
            {busyLabel?.startsWith("Recomputing") ? <Loader2 className="spin" size={16} /> : <RefreshCcw size={16} />}
            {busyLabel?.startsWith("Recomputing") ? "Recomputing" : "Recompute"}
          </button>
        </div>
      </header>

      {error ? <div className="error">{error}</div> : null}
        {busyLabel ? (
          <div className="busy-banner" role="status">
            <Loader2 className="spin" size={16} />
            <strong>Working</strong>
            <span>{busyLabel}. The API is busy with this job, not offline.</span>
          </div>
        ) : null}
        {scope === "archive" ? (
          <>
            <section className="archive-toolbar">
              <div className="archive-day-picker">
                <button
                  type="button"
                  disabled={!previousArchiveDate || isLoading}
                  onClick={() => previousArchiveDate && setArchiveSignalDate(previousArchiveDate)}
                  title="Previous day with signals"
                >
                  <ChevronLeft size={16} />
                </button>
                <label>
                  <CalendarDays size={15} />
                  <input
                    type="date"
                    value={archiveSignalDate}
                    onChange={(event) => setArchiveSignalDate(event.target.value)}
                  />
                </label>
                <button
                  type="button"
                  disabled={!nextArchiveDate || isLoading}
                  onClick={() => nextArchiveDate && setArchiveSignalDate(nextArchiveDate)}
                  title="Next day with signals"
                >
                  <ChevronRight size={16} />
                </button>
                <span>
                  {archiveDay
                    ? `${archiveDay.matches} matches · ${archiveDay.signals} signals`
                    : "No signals on selected date"}
                </span>
              </div>
              <label className="archive-sort-control">
                <ArrowUpDown size={15} />
                <select
                  value={archiveSort}
                  onChange={(event) => setArchiveSort(event.target.value as SignalSort)}
                >
                  <option value="quality">Best match first</option>
                  <option value="kickoff_asc">Kickoff time</option>
                  <option value="kickoff_desc">Latest kickoff</option>
                  <option value="sample_desc">Sample size</option>
                </select>
              </label>
            </section>

            <section className="archive-date-panel">
              <div>
                <h3>Backfill historical date</h3>
                <p>
                  Optional admin tool for old dates that were not monitored live.
                  Current monitored matches are archived automatically after final
                  score capture.
                </p>
              </div>
              <label>
                <CalendarDays size={15} />
                <input
                  type="date"
                  value={archiveDate}
                  onChange={(event) => updateBackfillDate(event.target.value)}
                />
              </label>
              <button type="button" onClick={archiveSelectedDate} disabled={operationBusy || !archiveDate}>
                {isBackfilling ? <Loader2 className="spin" size={15} /> : <Play size={15} />}
                {isBackfilling ? "Backfilling" : "Backfill date"}
              </button>
              <ArchiveProgressBar
                progress={archiveProgress}
                result={archiveResult}
                isRunning={isBackfilling}
              />
              {archiveResult ? (
                <div className="archive-result">
                  <span>date <strong>{archiveResult.date}</strong></span>
                  <span>found <strong>{archiveResult.discovered}</strong></span>
                  <span>captured <strong>{archiveResult.captured}</strong></span>
                  <span>complete <strong>{archiveResult.complete}</strong></span>
                  <span>archived <strong>{archiveResult.archived}</strong></span>
                  <span>signals <strong>{archiveResult.signals}</strong></span>
                </div>
              ) : null}
              {archiveResult && archiveResult.signals === 0 ? (
                <p className="archive-empty-note">
                  Backfill found {archiveResult.discovered} matches for {archiveResult.date},
                  but no archive signals were created. Usually this means there were no
                  completed matches with final score plus both Bwin and Unibet final 1X2 odds.
                </p>
              ) : null}
            </section>
          </>
        ) : null}
      {isLoading ? <SignalRowsSkeleton /> : null}

        <section className="signal-control-row">
          <div className="signal-tabs" aria-label="Signal type filters">
            <SignalTabButton
              label="All signals"
              count={counts.all}
              active={activeTab === "all"}
              onClick={() => setActiveTab("all")}
            />
            <SignalTabButton
              label="Exact"
              count={counts.exact_odds}
              active={activeTab === "exact_odds"}
              onClick={() => setActiveTab("exact_odds")}
            />
            <SignalTabButton
              label="Nearby"
              count={counts.neighbor_odds}
              active={activeTab === "neighbor_odds"}
              onClick={() => setActiveTab("neighbor_odds")}
            />
            <SignalTabButton
              label="Draw-only"
              count={counts.one_draw}
              active={activeTab === "one_draw"}
              onClick={() => setActiveTab("one_draw")}
            />
          </div>
          <label className="search signals-search">
            <Search size={15} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search teams, league, dataset"
            />
          </label>
          <span className="signal-filter-note">
            <Filter size={14} />
            {scope === "archive" ? sortLabel(archiveSort) : "Sorted by match quality"}
          </span>
        </section>

        <section className="signal-table">
          <div className="signal-table-head">
            <span>Match</span>
            <span>Bwin 1-X-2</span>
            <span>Unibet 1-X-2</span>
            <span>Match type / Historical sample</span>
            <span>H · D · A</span>
            <span>O2.5 · BTTS</span>
          </div>
          {!isLoading && visibleGroups.slice(0, 160).map((group) => (
            <SignalRow group={group} key={group.id} />
          ))}
          {!isLoading && visibleGroups.length === 0 ? (
            <p className="empty">
              No actionable signals right now. Finished matches stay available
              in Archive and are still used for historical comparison.
            </p>
          ) : null}
        </section>
      </section>
    </main>
  );
}

function SignalRowsSkeleton() {
  return (
    <div className="signal-table skeleton-signal-table" aria-label="Loading signals">
      {Array.from({ length: 5 }).map((_, index) => (
        <div className="signal-row skeleton-signal-row" key={index}>
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
      ))}
    </div>
  );
}

function initialArchiveProgress(): CaptureProgress {
  return {
    running: true,
    trigger: "archive_date",
    phase: "archive_discovery",
    discovered: 0,
    due: 0,
    queued: 0,
    active: 0,
    completed: 0,
    captured: 0,
    failed: 0,
    results_captured: 0,
    results_checked: 0,
    current_event_id: null,
    last_error: null,
  };
}

function completeArchiveProgress(
  current: CaptureProgress | null,
  result: ArchiveDateResult,
): CaptureProgress {
  return {
    ...(current ?? initialArchiveProgress()),
    running: false,
    trigger: "archive_date",
    phase: "archive_complete",
    discovered: result.discovered,
    queued: result.discovered,
    completed: result.discovered,
    captured: result.captured,
    failed: result.failed,
    results_captured: result.results_captured,
    current_event_id: null,
    last_error: null,
  };
}

function ArchiveProgressBar({
  progress,
  result,
  isRunning,
}: {
  progress: CaptureProgress | null;
  result: ArchiveDateResult | null;
  isRunning: boolean;
}) {
  const total = Math.max(0, progress?.queued || progress?.discovered || result?.discovered || 0);
  const completed = Math.max(0, progress?.completed ?? (result ? result.discovered : 0));
  const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;
  const captured = progress?.captured ?? result?.captured ?? 0;
  const failed = progress?.failed ?? result?.failed ?? 0;
  const scores = progress?.results_captured ?? result?.results_captured ?? 0;
  const archived = result?.archived ?? 0;
  const phaseLabel = isRunning
    ? archivePhaseLabel(progress?.phase)
    : result
      ? "Last backfill complete"
      : "Ready to backfill selected date";
  const totalLabel =
    total > 0
      ? `${completed}/${total} matches`
      : isRunning
        ? "Preparing archive job"
        : "No backfill running";
  return (
    <div className="archive-progress" role="status" aria-live="polite">
      <div className="archive-progress-head">
        <strong>{phaseLabel}</strong>
        <span>{totalLabel}</span>
      </div>
      <div className="archive-progress-track" aria-label="Backfill progress">
        <span style={{ width: `${percent}%` }} />
      </div>
      <div className="archive-progress-meta">
        <span>Captured <strong>{captured}</strong></span>
        <span>Failed <strong>{failed}</strong></span>
        <span>Scores <strong>{scores}</strong></span>
        <span>Archived <strong>{archived}</strong></span>
        {progress?.current_event_id ? (
          <span title={progress.current_event_id}>Current <strong>{progress.current_event_id}</strong></span>
        ) : null}
      </div>
      {progress?.last_error ? <small>{progress.last_error}</small> : null}
    </div>
  );
}

function SignalTabButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" className={active ? "signal-tab active" : "signal-tab"} onClick={onClick}>
      {label}
      <span>{count}</span>
    </button>
  );
}

function SignalRow({ group }: { group: SignalGroup }) {
  const signal = group.bestSignal;
  const bwin = bookmakerOdds(group, "bwin");
  const unibet = bookmakerOdds(group, "unibet");
  const signalMeta = `${signalMatchLabel(group)} · ${group.datasets.join(" + ")}`;

  return (
    <article className={`signal-row ${signal.signal_type}`}>
      <div className="signal-match-cell">
        <div>
          <span className="signal-type">{signalTypeLabel(group)}</span>
          <span className={similarityBadgeClass(signal)}>
            {signalMatchBadge(group)}
          </span>
        </div>
        <strong>
          {group.home_team} - {group.away_team}
        </strong>
        <small>
          {group.league ?? "Unknown league"} · {formatDate(group.kickoff_time)}
        </small>
      </div>
      <OddsSet value={bwin} />
      <OddsSet value={unibet} />
      <div className="signal-confidence-cell">
        <strong>{signal.sample_size}</strong>
        <em>samples</em>
        <small title={signalMeta} tabIndex={0}>
          {signalMeta}
        </small>
      </div>
      <div className="signal-bars">
        <PercentBar label="H" value={signal.home_win_pct} />
        <PercentBar label="D" value={signal.draw_pct} />
        <PercentBar label="A" value={signal.away_win_pct} />
      </div>
      <div className="signal-quick-stats">
        <span>
          O2.5 <strong>{formatPct(signal.over_2_5_pct)}</strong>
        </span>
        <span>
          BTTS <strong>{formatPct(signal.btts_pct)}</strong>
        </span>
        <a href={`/match?id=${encodeURIComponent(group.match_id)}`} title="Open match">
          <ChevronRight size={16} />
        </a>
      </div>
    </article>
  );
}

function OddsSet({ value }: { value: string }) {
  return <div className="signal-odds-set">{value}</div>;
}

function PercentBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="percent-bar">
      <span>{label}</span>
      <i>
        <b style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </i>
      <strong>{formatPct(value)}</strong>
    </div>
  );
}

function groupSignals(signals: HistoricalSignal[]): SignalGroup[] {
  const map = new Map<string, HistoricalSignal[]>();
  for (const signal of signals) {
    const current = map.get(signal.match_id) ?? [];
    current.push(signal);
    map.set(signal.match_id, current);
  }
  return [...map.entries()]
    .map(([matchId, groupSignals]) => {
      const bestSignal = groupSignals.reduce((best, signal) =>
        compareSignals(signal, best) < 0 ? signal : best,
      );
      return {
        id: matchId,
        match_id: matchId,
        league: bestSignal.league,
        home_team: bestSignal.home_team,
        away_team: bestSignal.away_team,
        kickoff_time: bestSignal.kickoff_time,
        signals: groupSignals,
        bestSignal,
        signalTypes: uniqueSorted(groupSignals.map((signal) => signal.signal_type)),
        datasets: uniqueSorted(groupSignals.map((signal) => signal.dataset)),
        historicalScores: uniqueSorted(
          groupSignals.flatMap((signal) => signal.historical_scores),
        ),
      };
    })
    .sort((left, right) => compareSignals(left.bestSignal, right.bestSignal));
}

function signalCounts(groups: SignalGroup[]) {
  return {
    all: groups.length,
    exact_odds: groups.filter((group) => group.signalTypes.includes("exact_odds")).length,
    neighbor_odds: groups.filter((group) => group.signalTypes.includes("neighbor_odds")).length,
    one_draw: groups.filter((group) => group.signalTypes.includes("one_draw")).length,
  };
}

function bookmakerOdds(group: SignalGroup, normalizedBookmaker: string) {
  const signal = group.signals.find(
    (item) => item.normalized_bookmaker === normalizedBookmaker,
  );
  if (!signal) return "-";
  return `${formatOdd(signal.current_home_odds)}  ${formatOdd(signal.current_draw_odds)}  ${formatOdd(signal.current_away_odds)}`;
}

function compareSignals(left: HistoricalSignal, right: HistoricalSignal) {
  const rank = (left.signal_rank ?? 99) - (right.signal_rank ?? 99);
  if (rank !== 0) return rank;
  const similarity = (right.similarity_score ?? 0) - (left.similarity_score ?? 0);
  if (similarity !== 0) return similarity;
  return right.sample_size - left.sample_size;
}

function signalTypeLabel(group: SignalGroup) {
  const signal = group.bestSignal;
  if (signal.signal_type === "exact_odds") return `${bookmakerSourceLabel(group, "exact_odds")} exact`;
  if (signal.signal_type === "neighbor_odds") return `${bookmakerSourceLabel(group, "neighbor_odds")} nearby`;
  if (signal.signal_type === "one_draw") return `${bookmakerSourceLabel(group, "one_draw")} draw-only`;
  return signal.signal_type;
}

function signalMatchBadge(group: SignalGroup) {
  const signal = group.bestSignal;
  if (signal.signal_type === "exact_odds") return "Exact odds";
  if (signal.signal_type === "neighbor_odds") return `Nearby ${formatPct(signal.similarity_score)}`;
  if (signal.signal_type === "one_draw") return "Draw-only";
  return formatPct(signal.similarity_score);
}

function signalMatchLabel(group: SignalGroup) {
  const signal = group.bestSignal;
  const source = bookmakerSourceLabel(group, signal.signal_type);
  if (signal.signal_type === "exact_odds") return `${source} exact 1X2`;
  if (signal.signal_type === "neighbor_odds") return `${source} nearby ${formatPct(signal.similarity_score)}`;
  if (signal.signal_type === "one_draw") return `${source} draw odds pattern`;
  return `${source} ${signal.signal_type}`;
}

function bookmakerSourceLabel(group: SignalGroup, signalType: string) {
  const bookmakers = uniqueSorted(
    group.signals
      .filter((signal) => signal.signal_type === signalType)
      .map((signal) => signal.normalized_bookmaker),
  );
  const labels = bookmakers.map(bookmakerDisplayName);
  if (labels.length === 0) return bookmakerDisplayName(group.bestSignal.normalized_bookmaker);
  if (labels.length === 1) return labels[0];
  return labels.join(" + ");
}

function bookmakerDisplayName(value: string) {
  if (value === "bwin") return "Bwin";
  if (value === "unibet") return "Unibet";
  return value;
}

function similarityBadgeClass(signal: HistoricalSignal) {
  if (signal.signal_type === "one_draw") return "similarity-badge draw-only";
  const score = signal.similarity_score ?? 0;
  if (score >= 95) return "similarity-badge strong";
  if (score >= 70) return "similarity-badge medium";
  return "similarity-badge weak";
}

function archivePhaseLabel(phase: string | null | undefined) {
  const labels: Record<string, string> = {
    archive_discovery: "Discovering archive matches",
    archive_capturing: "Capturing final odds and scores",
    archive_complete: "Backfill complete",
    error: "Backfill error",
  };
  return labels[phase ?? ""] ?? "Preparing archive job";
}

function uniqueSorted(values: string[]) {
  return [...new Set(values.filter(Boolean))].sort();
}

function adjacentSignalDate(days: SignalDay[], selectedDate: string, direction: -1 | 1) {
  const sorted = [...days].sort((left, right) => left.date.localeCompare(right.date));
  if (!selectedDate && sorted.length > 0) {
    return direction < 0 ? sorted[sorted.length - 1].date : sorted[0].date;
  }
  const index = sorted.findIndex((day) => day.date === selectedDate);
  if (index === -1) return null;
  return sorted[index + direction]?.date ?? null;
}

function sortLabel(sort: SignalSort) {
  const labels: Record<SignalSort, string> = {
    quality: "Sorted by match quality",
    kickoff_asc: "Sorted by kickoff time",
    kickoff_desc: "Sorted by latest kickoff",
    sample_desc: "Sorted by sample size",
  };
  return labels[sort];
}

function todayDateSlug() {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function formatOdd(value: number | null) {
  return value == null ? "-" : value.toFixed(2);
}

function formatPct(value: number | null | undefined) {
  return value == null ? "-" : `${value.toFixed(1)}%`;
}

function formatDate(value: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
