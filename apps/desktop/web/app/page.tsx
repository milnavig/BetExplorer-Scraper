"use client";

import {
  Activity,
  AlertTriangle,
  Download,
  ExternalLink,
  Filter,
  Play,
  RefreshCcw,
  Search,
  Table2,
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState, useTransition } from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const REQUIRED_BOOKMAKERS = new Set(["bwin", "unibet"]);
const MATCH_RENDER_BATCH = 80;
const DASHBOARD_STATUS_REFRESH_MS = 5000;
const DASHBOARD_FULL_REFRESH_MS = 30000;

type Status = {
  running: boolean;
  matches: number;
  snapshots: number;
  snapshot_attempts: number;
  bookmaker_rows: number;
  bookmaker_row_attempts: number;
  complete_snapshots: number;
  partial_snapshots: number;
  failed_snapshots: number;
  due_matches: number;
  captured_matches: number;
  finalized_matches: number;
  missed_finalized_matches: number;
  capture_missed_matches: number;
  skipped_out_of_window_matches: number;
  result_captured_matches: number;
  last_capture: string | null;
  last_run: string | null;
  next_run: string | null;
  next_capture: string | null;
  betexplorer_timezone_offset: string;
  scheduler_tick_seconds: number;
  monitoring_capture_poll_interval_seconds: number;
  final_capture_poll_interval_seconds: number;
  final_capture_fast_window_minutes: number;
  discovery_poll_interval_seconds: number;
  upcoming_window_minutes: number;
  odds_capture_lookahead_hours: number;
  result_capture_lookback_hours: number;
  result_finish_grace_minutes: number;
  max_concurrent_captures: number;
  max_concurrent_markets_per_match: number;
  market_discovery_cache_seconds: number;
  scheduler: SchedulerRuntime;
  capture_progress: CaptureProgress;
};

type SchedulerRuntime = {
  enabled: boolean;
  running: boolean;
  started_at: string | null;
  cycle_started_at: string | null;
  next_run_at: string | null;
  last_error: string | null;
};

type CaptureProgress = {
  running: boolean;
  trigger: string | null;
  phase: string;
  started_at: string | null;
  finished_at: string | null;
  discovered: number;
  due: number;
  queued: number;
  active: number;
  completed: number;
  captured: number;
  failed: number;
  skipped: number;
  finalized: number;
  waiting: number;
  results_captured: number;
  results_checked: number;
  current_event_id: string | null;
  last_error: string | null;
  last_discovery_at: string | null;
  next_discovery_at: string | null;
};

type MatchRow = {
  id: string;
  event_id: string;
  league: string | null;
  home_team: string;
  away_team: string;
  kickoff_time: string | null;
  status: string;
  timing_status: string;
  source_url: string;
  live_score: string | null;
  capture_phase: string | null;
  next_capture_at: string | null;
  last_capture_at: string | null;
  finalized_at: string | null;
  result_captured_at: string | null;
  snapshot_id: string | null;
  quality_status: string | null;
  captured_at: string | null;
  final_snapshot_age_to_kickoff_seconds: number | null;
  bookmaker_count: number;
  has_bwin: boolean;
  has_unibet: boolean;
  attempt_count: number;
};

type BookmakerOdds = {
  id: string;
  snapshot_id: string;
  bookmaker: string;
  normalized_bookmaker: string;
  bookmaker_id: string | null;
  betexplorer_bookmaker_id: string | null;
  home_odds: number | null;
  draw_odds: number | null;
  away_odds: number | null;
  is_available: boolean;
  raw_row_text: string | null;
  raw_attributes_json: string | null;
  created_at: string;
  market: string;
  snapshot_captured_at: string | null;
  snapshot_quality_status: string | null;
};

type SnapshotRow = {
  id: string;
  match_id: string;
  event_id: string;
  captured_at: string;
  market: string;
  capture_type: string;
  quality_status: string;
  is_final_candidate: boolean;
  is_final: boolean;
  source_page_type: string;
  raw_payload_path: string | null;
  required_bookmakers_json: string;
  created_at: string;
  league?: string | null;
  home_team?: string | null;
  away_team?: string | null;
  bookmaker_count?: number;
  final_snapshot_age_to_kickoff_seconds?: number | null;
};

type AttemptRow = {
  id: string;
  match_id: string;
  event_id: string;
  source_url: string;
  attempt_number: number;
  status: string;
  error_message: string | null;
  required_found_json: string;
  started_at: string;
  finished_at: string;
  created_at: string;
  league?: string | null;
  home_team?: string | null;
  away_team?: string | null;
};

type MatchDetail = {
  match: MatchRow;
  snapshots: SnapshotRow[];
  bookmaker_odds: BookmakerOdds[];
  attempts: AttemptRow[];
};

type LogRow = {
  id: string;
  timestamp: string;
  level: string;
  module: string;
  event: string;
  event_id: string | null;
  details_json: string;
};

type BookmakerCoverage = {
  bookmaker: string;
  normalized_bookmaker: string;
  rows: number;
  matches: number;
  avg_home_odds: number | null;
  avg_draw_odds: number | null;
  avg_away_odds: number | null;
  last_seen: string | null;
};

type ExportFile = {
  filename: string;
  path: string;
  download_url: string;
  size_bytes: number;
  modified_at: string;
};

type ExportResult = {
  path: string;
  filename: string;
  download_url: string;
};

type ExportFormat = "csv" | "xlsx";
type ExportLayout = "wide" | "long";

type CaptureRunResult = {
  discovered: number;
  due: number;
  captured: number;
  failed: number;
  skipped: number;
  finalized: number;
  waiting: number;
  results_captured: number;
  results_checked: number;
};

type MatchFilter =
  | "all"
  | "with_odds"
  | "req_full"
  | "req_partial"
  | "req_missing"
  | "missing_bwin"
  | "missing_unibet"
  | "capture_miss"
  | "skipped_old"
  | "due"
  | "finalized"
  | "new";
type SortMode =
  | "capture_desc"
  | "kickoff_asc"
  | "bookmakers_desc"
  | "attempts_desc";
type ProgressState = {
  label: string;
  value: number;
  detail: string;
  tone?: "good" | "warn" | "bad" | "idle";
};
type SchedulerState = {
  className: "active" | "idle" | "stale";
  label: string;
  detail: string;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export default function Dashboard() {
  const [status, setStatus] = useState<Status | null>(null);
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotRow[]>([]);
  const [attempts, setAttempts] = useState<AttemptRow[]>([]);
  const [logs, setLogs] = useState<LogRow[]>([]);
  const [bookmakers, setBookmakers] = useState<BookmakerCoverage[]>([]);
  const [exports, setExports] = useState<ExportFile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MatchDetail | null>(null);
  const [matchQuery, setMatchQuery] = useState("");
  const [bookmakerQuery, setBookmakerQuery] = useState("");
  const [matchFilter, setMatchFilter] = useState<MatchFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("capture_desc");
  const [marketFilter, setMarketFilter] = useState("all_markets");
  const [requiredOnly, setRequiredOnly] = useState(false);
  const [lastRun, setLastRun] = useState<CaptureRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [clientTimezone, setClientTimezone] = useState("-");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const selectedIdRef = useRef<string | null>(null);
  const matchListMoreRef = useRef<HTMLDivElement | null>(null);
  const [matchRenderLimit, setMatchRenderLimit] = useState(MATCH_RENDER_BATCH);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  const applyDashboardData = (
    nextStatus: Status,
    nextMatches: MatchRow[],
    nextSnapshots: SnapshotRow[],
    nextAttempts: AttemptRow[],
    nextLogs: LogRow[],
    nextBookmakers: BookmakerCoverage[],
    nextExports: ExportFile[],
  ) => {
    startTransition(() => {
      setStatus(nextStatus);
      setMatches(nextMatches);
      setSnapshots(nextSnapshots);
      setAttempts(nextAttempts);
      setLogs(nextLogs);
      setBookmakers(nextBookmakers);
      setExports(nextExports);
      const currentSelectedId = selectedIdRef.current;
      if (
        (!currentSelectedId ||
          !nextMatches.some((match) => match.id === currentSelectedId)) &&
        nextMatches.length > 0
      ) {
        const nextSelectedId = (
          nextMatches.find((match) => match.bookmaker_count > 0) ??
          nextMatches[0]
        ).id;
        selectedIdRef.current = nextSelectedId;
        setSelectedId(nextSelectedId);
      }
    });
  };

  const loadDashboardData = async () => {
    setError(null);
    try {
      const [
        nextStatus,
        nextMatches,
        nextSnapshots,
        nextAttempts,
        nextLogs,
        nextBookmakers,
        nextExports,
      ] = await Promise.all([
        api<Status>("/api/status"),
        api<MatchRow[]>("/api/matches"),
        api<SnapshotRow[]>("/api/snapshots"),
        api<AttemptRow[]>("/api/attempts"),
        api<LogRow[]>("/api/logs"),
        api<BookmakerCoverage[]>("/api/bookmakers"),
        api<ExportFile[]>("/api/exports"),
      ]);
      applyDashboardData(
        nextStatus,
        nextMatches,
        nextSnapshots,
        nextAttempts,
        nextLogs,
        nextBookmakers,
        nextExports,
      );
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Failed to load API data",
      );
    }
  };

  const loadStatusOnly = async () => {
    try {
      const nextStatus = await api<Status>("/api/status");
      startTransition(() => setStatus(nextStatus));
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Failed to load API status",
      );
    }
  };

  useEffect(() => {
    setClientTimezone(clientTimezoneLabel());
    void loadDashboardData();
    const clock = window.setInterval(() => setNowMs(Date.now()), 1000);
    const statusRefresh = window.setInterval(
      () => void loadStatusOnly(),
      DASHBOARD_STATUS_REFRESH_MS,
    );
    const fullRefresh = window.setInterval(
      () => void loadDashboardData(),
      DASHBOARD_FULL_REFRESH_MS,
    );
    return () => {
      window.clearInterval(clock);
      window.clearInterval(statusRefresh);
      window.clearInterval(fullRefresh);
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let active = true;
    api<MatchDetail>(`/api/matches/${selectedId}`)
      .then((nextDetail) => {
        if (active) setDetail(nextDetail);
      })
      .catch((nextError) =>
        setError(
          nextError instanceof Error
            ? nextError.message
            : "Failed to load match detail",
        ),
      );
    return () => {
      active = false;
    };
  }, [selectedId]);

  const timezoneOffset = status?.betexplorer_timezone_offset ?? "+0";

  const filteredMatches = useMemo(() => {
    const query = matchQuery.trim().toLowerCase();
    const visible = matches.filter((match) => {
      const stateOk =
        matchFilter === "all" ||
        (matchFilter === "with_odds" && match.bookmaker_count > 0) ||
        (matchFilter === "req_full" && match.quality_status === "COMPLETE") ||
        (matchFilter === "req_partial" && match.quality_status === "PARTIAL") ||
        (matchFilter === "req_missing" && match.quality_status === "FAILED") ||
        (matchFilter === "missing_bwin" &&
          match.bookmaker_count > 0 &&
          !match.has_bwin) ||
        (matchFilter === "missing_unibet" &&
          match.bookmaker_count > 0 &&
          !match.has_unibet) ||
        (matchFilter === "capture_miss" &&
          Boolean(match.finalized_at) &&
          match.bookmaker_count === 0 &&
          match.attempt_count > 0) ||
        (matchFilter === "skipped_old" &&
          Boolean(match.finalized_at) &&
          match.bookmaker_count === 0 &&
          match.attempt_count === 0) ||
        (matchFilter === "due" && Boolean(match.next_capture_at)) ||
        (matchFilter === "finalized" && Boolean(match.finalized_at)) ||
        (matchFilter === "new" && !match.quality_status);
      const queryOk =
        !query ||
        [
          match.league,
          match.home_team,
          match.away_team,
          match.event_id,
          qualityLabel(match.quality_status),
          displayTiming(match),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query);
      return stateOk && queryOk;
    });
    return visible.sort((left, right) => {
      if (sortMode === "kickoff_asc")
        return (
          timestamp(left.kickoff_time, timezoneOffset) -
          timestamp(right.kickoff_time, timezoneOffset)
        );
      if (sortMode === "bookmakers_desc")
        return right.bookmaker_count - left.bookmaker_count;
      if (sortMode === "attempts_desc")
        return right.attempt_count - left.attempt_count;
      return (
        timestamp(right.captured_at, timezoneOffset) -
        timestamp(left.captured_at, timezoneOffset)
      );
    });
  }, [matches, matchFilter, matchQuery, sortMode, timezoneOffset]);

  const filteredBookmakers = useMemo(() => {
    const rows = detail?.bookmaker_odds ?? [];
    const query = bookmakerQuery.trim().toLowerCase();
    return rows.filter((row) => {
      const requiredOk =
        !requiredOnly || REQUIRED_BOOKMAKERS.has(row.normalized_bookmaker);
      const marketOk =
        marketFilter === "all_markets" || row.market === marketFilter;
      const queryOk =
        !query ||
        [
          row.market,
          marketLabel(row.market),
          marketLine(row),
          row.bookmaker,
          row.normalized_bookmaker,
          row.bookmaker_id,
          row.betexplorer_bookmaker_id,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query);
      return requiredOk && marketOk && queryOk;
    });
  }, [bookmakerQuery, detail, marketFilter, requiredOnly]);

  useEffect(() => {
    setMatchRenderLimit(MATCH_RENDER_BATCH);
  }, [matchFilter, matchQuery, sortMode]);

  const renderedMatches = useMemo(
    () => filteredMatches.slice(0, matchRenderLimit),
    [filteredMatches, matchRenderLimit],
  );
  const hasMoreMatches = renderedMatches.length < filteredMatches.length;
  const loadMoreMatches = () =>
    setMatchRenderLimit((value) =>
      Math.min(value + MATCH_RENDER_BATCH, filteredMatches.length),
    );

  useEffect(() => {
    const node = matchListMoreRef.current;
    if (!node || !hasMoreMatches || !("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadMoreMatches();
      },
      { rootMargin: "320px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [filteredMatches.length, hasMoreMatches]);

  const marketCounts = useMemo(
    () => marketCountsFor(detail?.bookmaker_odds ?? []),
    [detail],
  );

  const selectedMatch =
    detail?.match ?? matches.find((match) => match.id === selectedId) ?? null;
  const latestExport = exports[0];
  const progressItems = useMemo(
    () => buildProgress(status, selectedMatch, nowMs, timezoneOffset),
    [nowMs, selectedMatch, status, timezoneOffset],
  );
  const schedulerStateValue = useMemo(
    () => schedulerState(status, nowMs),
    [nowMs, status],
  );
  const formatSchedule = (
    value: string | null | undefined,
    withSeconds = false,
  ) => formatScheduleDate(value, timezoneOffset, withSeconds);
  const formatUtc = (value: string | null | undefined, withSeconds = false) =>
    formatUtcDate(value, timezoneOffset, withSeconds);

  const runCapture = () => {
    startTransition(async () => {
      setError(null);
      try {
        const result = await api<CaptureRunResult>("/api/capture/run-once", {
          method: "POST",
        });
        setLastRun(result);
        await loadDashboardData();
      } catch (nextError) {
        setError(
          nextError instanceof Error ? nextError.message : "Capture failed",
        );
      }
    });
  };

  const exportOdds = (format: ExportFormat, layout: ExportLayout = "wide") => {
    startTransition(async () => {
      setError(null);
      try {
        const result = await api<ExportResult>("/api/exports/final-odds", {
          method: "POST",
          body: JSON.stringify({ format, layout }),
        });
        window.location.assign(`${API_BASE}${result.download_url}`);
        await loadDashboardData();
      } catch (nextError) {
        setError(
          nextError instanceof Error ? nextError.message : "Export failed",
        );
      }
    });
  };

  return (
    <main className={isPending ? "shell is-pending" : "shell"}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">BE</span>
          <div>
            <h1>BetExplorer Monitor</h1>
          </div>
        </div>
        <nav className="nav">
          <a href="#overview" title={tooltipFor("Overview nav")}>
            Overview
          </a>
          {/* <a href="#matches" title={tooltipFor("Matches nav")}>Matches</a> */}
          {/* <a href="#detail" title={tooltipFor("Detail nav")}>Detail</a> */}
          <a
            href={
              selectedMatch
                ? `/match?id=${encodeURIComponent(selectedMatch.id)}`
                : "#detail"
            }
            title={tooltipFor("Match page nav")}
          >
            Match page
          </a>
          <a href="#odds" title={tooltipFor("Odds nav")}>
            Odds
          </a>
          <a href="#attempts" title={tooltipFor("Attempts nav")}>
            Attempts
          </a>
          <a href="#exports" title={tooltipFor("Exports nav")}>
            Exports
          </a>
        </nav>
        <div className="side-note">
          <span>Last run</span>
          <strong title={tooltipFor("Last run")}>
            {formatUtc(status?.last_run, true)}
          </strong>
          <small title={tooltipFor("Next run")}>
            Next run{" "}
            {status?.capture_progress?.running
              ? "after current cycle"
              : formatUtc(status?.next_run, true)}
          </small>
          <small title={tooltipFor("Next capture")}>
            Next capture {formatSchedule(status?.next_capture, true)}
          </small>
          <small title={tooltipFor("Last odds")}>
            Last odds {formatUtc(status?.last_capture, true)}
          </small>
          <small title={tooltipFor("Discovery")}>
            Discovery{" "}
            {formatSchedule(status?.capture_progress?.next_discovery_at, true)}
          </small>
          <small title={tooltipFor("Browser TZ")}>
            Browser TZ {clientTimezone}
          </small>
          <small title={tooltipFor("BetExplorer TZ")}>
            BetExplorer TZ UTC{status?.betexplorer_timezone_offset ?? "-"}
          </small>
          <small title={tooltipFor("Result capture")}>
            Results {status?.result_captured_matches ?? 0} /{" "}
            {status?.result_capture_lookback_hours ?? "-"}h lookback
          </small>
          <small>
            {latestExport
              ? `Latest export ${latestExport.filename}`
              : "No exports yet"}
          </small>
          <span
            className={`scheduler-state ${schedulerStateValue.className}`}
            title={schedulerStateValue.detail}
          >
            {schedulerStateValue.label}
          </span>
          <div className="side-progress">
            {progressItems.map((item) => (
              <ProgressBar key={item.label} {...item} />
            ))}
          </div>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyeline">Local API: {API_BASE}</p>
            <h2>
              <span className="live-dot" />
              Monitoring console
            </h2>
          </div>
          <div className="actions">
            <button
              onClick={() => void loadDashboardData()}
              disabled={isPending}
              title={tooltipFor("Refresh data")}
            >
              <RefreshCcw className="refresh-icon" size={16} />
              Refresh
            </button>
            <button
              onClick={runCapture}
              disabled={isPending}
              title={tooltipFor("Run once")}
            >
              <Play size={16} />
              Run once
            </button>
            <button
              onClick={() => exportOdds("csv", "wide")}
              disabled={isPending}
              title={tooltipFor("Export CSV")}
            >
              <Download size={16} />
              CSV
            </button>
            <button
              onClick={() => exportOdds("csv", "long")}
              disabled={isPending}
              title={tooltipFor("Export long CSV")}
            >
              <Download size={16} />
              Long CSV
            </button>
            <button
              onClick={() => exportOdds("xlsx", "wide")}
              disabled={isPending}
              title={tooltipFor("Export XLSX")}
            >
              <Download size={16} />
              XLSX
            </button>
            <button
              onClick={() => exportOdds("xlsx", "long")}
              disabled={isPending}
              title={tooltipFor("Export long XLSX")}
            >
              <Download size={16} />
              Long XLSX
            </button>
          </div>
        </header>

        {error ? <div className="error">{error}</div> : null}
        {lastRun ? (
          <div className={lastRun.due > 0 ? "run-result active" : "run-result"}>
            <strong>Run once</strong>
            <span>discovered {lastRun.discovered}</span>
            <span>due {lastRun.due}</span>
            <span>captured {lastRun.captured}</span>
            <span>failed {lastRun.failed}</span>
            <span>skipped {lastRun.skipped}</span>
            <span>finalized {lastRun.finalized}</span>
            <span>waiting {lastRun.waiting}</span>
            <span>results {lastRun.results_captured}</span>
            <span>result checks {lastRun.results_checked}</span>
          </div>
        ) : null}

        <section className="metrics" id="overview">
          <Metric label="Matches" value={status?.matches} />
          <Metric
            label="Captured"
            value={status?.captured_matches}
            tone="good"
          />
          <Metric
            label="Capture miss"
            value={status?.capture_missed_matches}
            tone="bad"
          />
          <Metric
            label="Skipped old"
            value={status?.skipped_out_of_window_matches}
          />
          <Metric
            label="Due captures"
            value={status?.due_matches}
            tone="warn"
          />
          <Metric label="Results" value={status?.result_captured_matches} />
          <Metric label="Final snapshots" value={status?.snapshots} />
          <Metric label="Attempts" value={status?.snapshot_attempts} />
          <Metric label="Bookmaker rows" value={status?.bookmaker_rows} />
          <Metric label="Row attempts" value={status?.bookmaker_row_attempts} />
          <Metric
            label="Req complete"
            value={status?.complete_snapshots}
            tone="good"
          />
          <Metric
            label="Req partial"
            value={status?.partial_snapshots}
            tone="warn"
          />
          <Metric
            label="Req missing"
            value={status?.failed_snapshots}
            tone="bad"
          />
          <Metric label="Bookmakers" value={bookmakers.length} />
        </section>

        <section className="coverage-strip">
          {bookmakers.map((bookmaker) => (
            <div
              className={
                REQUIRED_BOOKMAKERS.has(bookmaker.normalized_bookmaker)
                  ? "coverage required"
                  : "coverage"
              }
              key={bookmaker.normalized_bookmaker}
              title={`${bookmaker.bookmaker}: seen in ${bookmaker.matches} matches and ${bookmaker.rows} final odds rows.`}
            >
              <span>{bookmaker.bookmaker}</span>
              <strong>{bookmaker.matches}</strong>
              <small>{formatUtc(bookmaker.last_seen)}</small>
            </div>
          ))}
        </section>

        <section className="split">
          <div className="panel" id="matches">
            <div className="panel-head">
              <div>
                <h3>Matches</h3>
                <p>
                  {filteredMatches.length} visible of {matches.length}
                </p>
              </div>
              <label className="search" title={tooltipFor("Match search")}>
                <Search size={15} />
                <input
                  value={matchQuery}
                  onChange={(event) => setMatchQuery(event.target.value)}
                  placeholder="Search teams, league, event"
                />
              </label>
            </div>
            <div className="filters">
              <SelectFilter
                value={matchFilter}
                onChange={(value) => setMatchFilter(value as MatchFilter)}
                options={[
                  "all",
                  "with_odds",
                  "req_full",
                  "req_partial",
                  "req_missing",
                  "missing_bwin",
                  "missing_unibet",
                  "capture_miss",
                  "skipped_old",
                  "due",
                  "finalized",
                  "new",
                ]}
              />
              <SelectFilter
                value={sortMode}
                onChange={(value) => setSortMode(value as SortMode)}
                options={[
                  "capture_desc",
                  "kickoff_asc",
                  "bookmakers_desc",
                  "attempts_desc",
                ]}
              />
            </div>
            <div className="match-list">
              {renderedMatches.map((match) => (
                <button
                  key={match.id}
                  className={
                    match.id === selectedId ? "match-row selected" : "match-row"
                  }
                  onClick={() => {
                    selectedIdRef.current = match.id;
                    setSelectedId(match.id);
                  }}
                >
                  <span
                    className={`quality ${qualityClass(match.quality_status)}`}
                  >
                    {qualityLabel(match.quality_status)}
                  </span>
                  <span>
                    <strong>{match.home_team}</strong>
                    <small>{match.away_team}</small>
                  </span>
                  <span>
                    <em>{match.league ?? "Unknown league"}</em>
                    <small>
                      {formatSchedule(match.kickoff_time)} ·{" "}
                      {displayCapturePhase(match)} · {match.attempt_count} tries
                    </small>
                  </span>
                  <span className="required-pair">
                    <Badge label="B" active={match.has_bwin} />
                    <Badge label="U" active={match.has_unibet} />
                  </span>
                  <span className="count">{match.bookmaker_count}</span>
                </button>
              ))}
              {filteredMatches.length === 0 ? (
                <p className="empty">No matches match the current filters.</p>
              ) : null}
              {filteredMatches.length > 0 ? (
                <div className="list-footer" ref={matchListMoreRef}>
                  <span>
                    Showing {renderedMatches.length} of {filteredMatches.length}
                  </span>
                  {hasMoreMatches ? (
                    <button
                      type="button"
                      onClick={loadMoreMatches}
                      title={tooltipFor("Load more matches")}
                    >
                      Load more matches
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>

          <div className="panel detail-panel" id="detail">
            <div className="panel-head">
              <div>
                <h3>Selected match</h3>
                <p>
                  {selectedMatch ? selectedMatch.event_id : "No match selected"}
                </p>
              </div>
              <div className="toolbar">
                {selectedMatch ? (
                  <>
                    <a
                      className="icon-link"
                      href={`/match?id=${encodeURIComponent(selectedMatch.id)}`}
                      title="Open full local match page"
                    >
                      <Table2 size={16} />
                      Full page
                    </a>
                    <a
                      className="icon-link"
                      href={selectedMatch.source_url}
                      target="_blank"
                      rel="noreferrer"
                      title="Open BetExplorer match"
                    >
                      <ExternalLink size={16} />
                    </a>
                  </>
                ) : null}
              </div>
            </div>

            {selectedMatch ? (
              <>
                <div className="match-title">
                  <div>
                    <strong>
                      {selectedMatch.home_team} - {selectedMatch.away_team}
                    </strong>
                    <small>{selectedMatch.league ?? "Unknown league"}</small>
                  </div>
                  <span
                    className={`quality large ${qualityClass(selectedMatch.quality_status)}`}
                  >
                    {qualityLabel(selectedMatch.quality_status)}
                  </span>
                </div>

                <div className="info-grid">
                  <Info
                    label="Kickoff"
                    value={formatSchedule(selectedMatch.kickoff_time)}
                  />
                  <Info
                    label="Capture phase"
                    value={displayCapturePhase(selectedMatch)}
                  />
                  <Info label="Timing" value={displayTiming(selectedMatch)} />
                  <Info
                    label="Bookmakers"
                    value={String(selectedMatch.bookmaker_count)}
                  />
                  <Info
                    label="Required"
                    value={requiredAvailability(selectedMatch)}
                  />
                  <Info
                    label="Attempts"
                    value={String(selectedMatch.attempt_count)}
                  />
                  <Info
                    label="Next capture"
                    value={formatSchedule(selectedMatch.next_capture_at)}
                  />
                  <Info
                    label="Last capture"
                    value={formatUtc(selectedMatch.last_capture_at)}
                  />
                  <Info
                    label="Final snapshot age"
                    value={formatAgeToKickoff(
                      selectedMatch.final_snapshot_age_to_kickoff_seconds,
                    )}
                  />
                  <Info
                    label="Finalized"
                    value={formatSchedule(selectedMatch.finalized_at)}
                  />
                  <Info
                    label="Result captured"
                    value={formatUtc(selectedMatch.result_captured_at)}
                  />
                  <Info
                    label="Live score"
                    value={selectedMatch.live_score ?? "-"}
                  />
                </div>

                <div className="section-stack">
                  <MiniTable title="Snapshots" icon={<Table2 size={15} />}>
                    <thead>
                      <tr>
                        <th>Captured</th>
                        <th>Quality</th>
                        <th>Final</th>
                        <th title={tooltipFor("Odds rows")}>Odds rows</th>
                        <th>To kickoff</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail?.snapshots ?? []).map((snapshot) => (
                        <tr key={snapshot.id}>
                          <td>{formatUtc(snapshot.captured_at)}</td>
                          <td>
                            <span
                              className={`quality ${qualityClass(snapshot.quality_status)}`}
                            >
                              {qualityLabel(snapshot.quality_status)}
                            </span>
                          </td>
                          <td>{snapshot.is_final ? "yes" : "no"}</td>
                          <td>{snapshot.bookmaker_count ?? "-"}</td>
                          <td>
                            {formatAgeToKickoff(
                              snapshot.final_snapshot_age_to_kickoff_seconds,
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </MiniTable>

                  <MiniTable
                    title="Match attempts"
                    icon={<Activity size={15} />}
                  >
                    <thead>
                      <tr>
                        <th>Attempt</th>
                        <th>Status</th>
                        <th>Started</th>
                        <th>Required</th>
                        <th>Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail?.attempts ?? []).map((attempt) => (
                        <tr key={attempt.id}>
                          <td>{attempt.attempt_number}</td>
                          <td>
                            <span
                              className={`quality ${qualityClass(attempt.status)}`}
                            >
                              {qualityLabel(attempt.status)}
                            </span>
                          </td>
                          <td>{formatUtc(attempt.started_at)}</td>
                          <td>
                            <code>
                              {formatRequiredJson(attempt.required_found_json)}
                            </code>
                          </td>
                          <td>{attempt.error_message ?? "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </MiniTable>
                </div>
              </>
            ) : (
              <p className="empty">No match selected.</p>
            )}
          </div>
        </section>

        <section className="panel" id="odds">
          <div className="panel-head">
            <div>
              <h3>Bookmaker odds</h3>
              <p>
                {detail
                  ? `${filteredBookmakers.length} visible of ${detail.bookmaker_odds.length} · ${marketCounts.map((item) => `${marketLabel(item.market)} ${item.count}`).join(" · ")}`
                  : "Select a match"}
              </p>
            </div>
            <div className="toolbar">
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={requiredOnly}
                  onChange={(event) => setRequiredOnly(event.target.checked)}
                />
                Required only
              </label>
              <label
                className="select-filter"
                title="Filter bookmaker rows by market"
              >
                <Filter size={14} />
                <select
                  value={marketFilter}
                  onChange={(event) => setMarketFilter(event.target.value)}
                >
                  <option value="all_markets">All markets</option>
                  {marketCounts.map((item) => (
                    <option key={item.market} value={item.market}>
                      {marketLabel(item.market)} ({item.count})
                    </option>
                  ))}
                </select>
              </label>
              <label className="search" title={tooltipFor("Bookmaker search")}>
                <Filter size={15} />
                <input
                  value={bookmakerQuery}
                  onChange={(event) => setBookmakerQuery(event.target.value)}
                  placeholder="Filter market, bookmakers, IDs"
                />
              </label>
            </div>
          </div>
          <div className="table-wrap tall">
            <table>
              <thead>
                <tr>
                  <th>Bookmaker</th>
                  <th>Market</th>
                  <th>Line</th>
                  <th>Bookmaker ID</th>
                  <th>BE ID</th>
                  <th>Prices</th>
                  <th>Status</th>
                  <th>Snapshot</th>
                </tr>
              </thead>
              <tbody>
                {filteredBookmakers.map((row) => (
                  <tr
                    key={row.id}
                    className={
                      REQUIRED_BOOKMAKERS.has(row.normalized_bookmaker)
                        ? "required"
                        : ""
                    }
                  >
                    <td>{row.bookmaker}</td>
                    <td>{marketLabel(row.market)}</td>
                    <td>
                      <span className="line-pill">{marketLine(row)}</span>
                    </td>
                    <td>{row.bookmaker_id ?? "-"}</td>
                    <td>{row.betexplorer_bookmaker_id ?? "-"}</td>
                    <td>
                      <PriceSet row={row} />
                    </td>
                    <td>{row.is_available ? "available" : "missing"}</td>
                    <td>{formatUtc(row.snapshot_captured_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="tri-grid">
          <div className="panel" id="attempts">
            <PanelTitle
              title="Recent attempts"
              subtitle={`${attempts.length} loaded`}
            />
            <div className="compact-list">
              {attempts.slice(0, 18).map((attempt) => (
                <div className="compact-row" key={attempt.id}>
                  <span className={`quality ${qualityClass(attempt.status)}`}>
                    {qualityLabel(attempt.status)}
                  </span>
                  <strong>
                    {attempt.home_team ?? attempt.event_id}{" "}
                    {attempt.away_team ? `- ${attempt.away_team}` : ""}
                  </strong>
                  <small>
                    #{attempt.attempt_number} · {formatUtc(attempt.started_at)}
                  </small>
                  {attempt.error_message ? (
                    <code>{attempt.error_message}</code>
                  ) : (
                    <code>
                      {formatRequiredJson(attempt.required_found_json)}
                    </code>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <PanelTitle
              title="Recent snapshots"
              subtitle={`${snapshots.length} loaded`}
            />
            <div className="compact-list">
              {snapshots.slice(0, 18).map((snapshot) => (
                <div className="compact-row" key={snapshot.id}>
                  <span
                    className={`quality ${qualityClass(snapshot.quality_status)}`}
                  >
                    {qualityLabel(snapshot.quality_status)}
                  </span>
                  <strong>
                    {snapshot.home_team ?? snapshot.event_id}{" "}
                    {snapshot.away_team ? `- ${snapshot.away_team}` : ""}
                  </strong>
                  <small>
                    {formatUtc(snapshot.captured_at)} · {snapshot.market} ·{" "}
                    {snapshot.bookmaker_count ?? 0} rows
                  </small>
                  <small>
                    To kickoff{" "}
                    {formatAgeToKickoff(
                      snapshot.final_snapshot_age_to_kickoff_seconds,
                    )}
                  </small>
                </div>
              ))}
            </div>
          </div>

          <div className="panel logs">
            <PanelTitle title="Logs" subtitle={`${logs.length} loaded`} />
            <div className="compact-list">
              {logs.slice(0, 18).map((log) => (
                <div className="compact-row" key={log.id}>
                  <span className={log.level}>{log.level}</span>
                  <strong>{log.event}</strong>
                  <small>
                    {formatUtc(log.timestamp)} · {log.event_id ?? "-"}
                  </small>
                  <code>{log.details_json}</code>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="dual-grid" id="exports">
          <div className="panel">
            <PanelTitle
              title="Bookmaker coverage"
              subtitle={`${bookmakers.length} final-market bookmakers`}
            />
            <div className="table-wrap medium">
              <table>
                <thead>
                  <tr>
                    <th>Bookmaker</th>
                    <th>Matches</th>
                    <th>Rows</th>
                    <th>Avg 1</th>
                    <th>Avg X</th>
                    <th>Avg 2</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {bookmakers.map((bookmaker) => (
                    <tr
                      key={bookmaker.normalized_bookmaker}
                      className={
                        REQUIRED_BOOKMAKERS.has(bookmaker.normalized_bookmaker)
                          ? "required"
                          : ""
                      }
                    >
                      <td>{bookmaker.bookmaker}</td>
                      <td>{bookmaker.matches}</td>
                      <td>{bookmaker.rows}</td>
                      <td>{formatOdd(bookmaker.avg_home_odds)}</td>
                      <td>{formatOdd(bookmaker.avg_draw_odds)}</td>
                      <td>{formatOdd(bookmaker.avg_away_odds)}</td>
                      <td>{formatUtc(bookmaker.last_seen)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel">
            <PanelTitle title="Exports" subtitle={`${exports.length} files`} />
            <div className="export-list">
              {exports.map((file) => (
                <a
                  href={`${API_BASE}${file.download_url}`}
                  className="export-row"
                  key={file.filename}
                  title={`${tooltipFor("Export file")} ${file.filename}`}
                >
                  <Download size={15} />
                  <span>
                    <strong>{file.filename}</strong>
                    <small>
                      {formatBytes(file.size_bytes)} ·{" "}
                      {formatSchedule(file.modified_at)}
                    </small>
                  </span>
                </a>
              ))}
              {exports.length === 0 ? (
                <p className="empty">No export files yet.</p>
              ) : null}
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value?: number;
  tone?: "good" | "warn" | "bad";
}) {
  return (
    <div className={`metric ${tone ?? ""}`} title={tooltipFor(label)}>
      <span>{label}</span>
      <strong>{value ?? 0}</strong>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="info-cell"
      title={`${tooltipFor(label)} Current value: ${value}`}
    >
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Badge({ label, active }: { label: string; active: boolean }) {
  return (
    <span
      className={active ? "mini-badge active" : "mini-badge"}
      title={`${label === "B" ? "Bwin" : "Unibet"} required bookmaker ${active ? "is present" : "is missing"}`}
    >
      {label}
    </span>
  );
}

function SelectFilter({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
}) {
  return (
    <label className="select-filter" title={tooltipFor(value)}>
      <Filter size={14} />
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>
            {filterLabel(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function PanelTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div
      className="panel-head compact-head"
      title={`${tooltipFor(title)} ${subtitle}`}
    >
      <div>
        <h3>{title}</h3>
        <p>{subtitle}</p>
      </div>
      <AlertTriangle size={15} />
    </div>
  );
}

function MiniTable({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="mini-table" title={tooltipFor(title)}>
      <div className="mini-title">
        {icon}
        <strong>{title}</strong>
      </div>
      <div className="table-wrap mini">
        <table>{children}</table>
      </div>
    </div>
  );
}

function PriceSet({ row }: { row: BookmakerOdds }) {
  return (
    <div className="price-set">
      {priceItems(row).map((item) => (
        <span key={item.label} className="price-chip">
          <small>{item.label}</small>
          <strong>{item.value}</strong>
        </span>
      ))}
    </div>
  );
}

function ProgressBar({ label, value, detail, tone }: ProgressState) {
  return (
    <div className="progress-line" title={`${label}: ${detail}`}>
      <div>
        <span>{label}</span>
        <small>{detail}</small>
      </div>
      <div className="progress-track">
        <span
          className={tone ?? ""}
          style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
        />
      </div>
    </div>
  );
}

function formatScheduleDate(
  value: string | null | undefined,
  timezoneOffset: string,
  withSeconds = false,
) {
  if (!value) return "-";
  return formatOffsetDate(
    parseOffsetLocalApiDate(value, timezoneOffset),
    timezoneOffset,
    withSeconds,
  );
}

function formatUtcDate(
  value: string | null | undefined,
  timezoneOffset: string,
  withSeconds = false,
) {
  if (!value) return "-";
  return formatOffsetDate(parseUtcApiDate(value), timezoneOffset, withSeconds);
}

function formatOffsetDate(
  date: Date,
  timezoneOffset: string,
  withSeconds = false,
) {
  const shifted = new Date(
    date.getTime() + parseTimezoneOffsetMs(timezoneOffset),
  );
  const options: Intl.DateTimeFormatOptions = {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  };
  if (withSeconds) options.second = "2-digit";
  return new Intl.DateTimeFormat("en", options).format(shifted);
}

function formatOdd(value: number | null) {
  return value == null ? "-" : value.toFixed(2);
}

function formatAgeToKickoff(value: number | null | undefined) {
  if (value == null) return "-";
  const prefix = value >= 0 ? "before" : "after";
  const abs = Math.abs(value);
  const minutes = Math.floor(abs / 60);
  const seconds = abs % 60;
  if (minutes < 1) return `${prefix} ${seconds}s`;
  if (minutes < 60) return `${prefix} ${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  return `${prefix} ${hours}h ${minutes % 60}m`;
}

function marketLabel(market: string | null | undefined) {
  const labels: Record<string, string> = {
    "1x2": "1X2",
    ou: "Over/Under",
    ah: "Asian Handicap",
    dc: "Double Chance",
    bts: "Both Teams To Score",
    dnb: "Draw No Bet",
  };
  return (
    labels[(market ?? "").toLowerCase()] ??
    (market ? market.toUpperCase() : "-")
  );
}

function marketCountsFor(rows: BookmakerOdds[]) {
  const counts = new Map<string, number>();
  for (const row of rows) {
    counts.set(row.market, (counts.get(row.market) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([market, count]) => ({ market, count }))
    .sort(
      (left, right) =>
        marketSortValue(left.market) - marketSortValue(right.market),
    );
}

function marketSortValue(market: string) {
  const order = ["1x2", "ou", "ah", "ha", "dc", "bts"];
  const index = order.indexOf(market.toLowerCase());
  return index === -1 ? order.length : index;
}

function marketLine(row: BookmakerOdds) {
  const attrs = parseRawAttributes(row.raw_attributes_json);
  const explicit =
    attrs.market_line ?? attrs.line ?? attrs.handicap ?? attrs.total;
  if (explicit != null && String(explicit).trim())
    return String(explicit).trim();
  const raw = (row.raw_row_text ?? "").trim();
  const bookmaker = row.bookmaker.trim();
  const withoutBookmaker = raw.toLowerCase().startsWith(bookmaker.toLowerCase())
    ? raw.slice(bookmaker.length).trim()
    : raw;
  const line = withoutBookmaker.match(/^[+-]?\d+(?:\.\d+)?/);
  return line ? line[0] : "-";
}

function priceItems(row: BookmakerOdds) {
  const market = row.market.toLowerCase();
  const labels =
    market === "ou"
      ? ["Over", "Under", ""]
      : market === "bts"
        ? ["Yes", "No", ""]
        : market === "dc"
          ? ["1X", "12", "X2"]
          : market === "ah"
            ? ["1", "2", ""]
            : ["1", "X", "2"];
  return [row.home_odds, row.draw_odds, row.away_odds]
    .map((value, index) => ({ label: labels[index], value: formatOdd(value) }))
    .filter((item) => item.label && item.value !== "-");
}

function parseRawAttributes(
  value: string | null | undefined,
): Record<string, unknown> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function qualityClass(value: string | null) {
  if (value === "COMPLETE") return "good";
  if (value === "PARTIAL") return "warn";
  if (value === "FAILED" || value === "ERROR") return "bad";
  return "";
}

function qualityLabel(value: string | null) {
  if (value === "COMPLETE") return "REQ FULL";
  if (value === "PARTIAL") return "REQ PARTIAL";
  if (value === "FAILED") return "REQ MISSING";
  if (value === "ERROR") return "ERROR";
  return "NO SNAPSHOT";
}

function filterLabel(value: string) {
  const labels: Record<string, string> = {
    all: "All matches",
    with_odds: "Has odds",
    req_full: "Required full",
    req_partial: "Required partial",
    req_missing: "Required missing",
    missing_bwin: "Missing Bwin",
    missing_unibet: "Missing Unibet",
    capture_miss: "Capture miss",
    skipped_old: "Skipped old",
    due: "Due captures",
    finalized: "Finalized",
    new: "No snapshot",
    capture_desc: "Latest capture",
    kickoff_asc: "Kickoff time",
    bookmakers_desc: "Most bookmakers",
    attempts_desc: "Most attempts",
  };
  return labels[value] ?? value;
}

function tooltipFor(label: string) {
  const text: Record<string, string> = {
    "Overview nav":
      "Jump to high-level health counters for the local database, scheduler queue, final snapshots, and bookmaker coverage.",
    "Matches nav":
      "Jump to the match list. Use the search, status filter, and sort selector to choose the match shown in the detail panel.",
    "Detail nav":
      "Jump to the selected match summary: schedule state, required bookmaker presence, snapshots, and attempts.",
    "Match page nav":
      "Open the full-screen detail page for the selected match. It shows every final bookmaker row grouped by market.",
    "Odds nav":
      "Jump to bookmaker odds rows for the selected match. These are final snapshot rows only.",
    "Attempts nav":
      "Jump to recent capture attempts, recent snapshots, and logs.",
    "Exports nav":
      "Jump to generated CSV/XLSX files and bookmaker coverage table.",
    "Match search":
      "Search the loaded match list by team, league, event id, quality label, or displayed scheduler/timing status.",
    "Bookmaker search":
      "Filter the selected match odds rows by market name, market line, bookmaker name, normalized bookmaker, or BetExplorer bookmaker id.",
    "Load more matches":
      "Render the next batch of matches in the list. The full dataset is already loaded; batching keeps the page responsive.",
    "Export file": "Download this generated export file from the local API:",
    "Refresh data":
      "Reload status, matches, snapshots, attempts, logs, bookmaker coverage, and export files from the local API. Does not run capture.",
    "Run once":
      "Manually run one scheduler/capture cycle now. The continuous API scheduler still runs independently when enabled.",
    "Export CSV":
      "Generate the wide CSV export: one row per final match/market snapshot, with required bookmaker odds flattened into columns.",
    "Export long CSV":
      "Generate the long CSV export: one row per bookmaker/market/line, with selection labels and odds in separate columns.",
    "Export XLSX":
      "Generate the wide Excel export with the same columns as the wide CSV.",
    "Export long XLSX":
      "Generate the long Excel export with the same rows as Long CSV.",
    Matches:
      "Total rows in the matches table. This includes discovered, scheduled, finalized, finished, and matches without odds.",
    Captured:
      "Distinct matches that currently have at least one final odds snapshot. A match can have many final snapshots when multiple markets are captured.",
    "Capture miss":
      "Finalized matches that have scrape attempts but still have zero final odds snapshots. Usually means BetExplorer returned no usable odds rows or parsing failed for all attempts.",
    "Skipped old":
      "Finalized matches with zero odds snapshots and zero scrape attempts. Usually means the match was discovered only after its configured capture window had already closed.",
    "Due captures":
      "Due captures is not a live-match count. It is non-finalized matches where next_capture_at is now or overdue; it can jump when discovery adds matches, kickoff times are corrected, or a scheduler cycle drains the queue.",
    Results:
      "Matches where the final score/result was saved. This is separate from odds capture and only happens once per match inside RESULT_CAPTURE_LOOKBACK_HOURS.",
    "Final snapshots":
      "Final odds snapshots currently selected for exports and summaries. With CAPTURE_MARKET=all, each match can have one final snapshot per market.",
    "Odds rows":
      "Bookmaker/line rows saved for this snapshot. Simple markets have fewer rows; Asian Handicap and Over/Under can have many rows because every line is stored separately.",
    Attempts:
      "Total HTTP/parser attempts recorded for odds capture. Retries and multiple markets increase this number.",
    "Bookmaker rows":
      "Rows saved in the currently selected final snapshots. This counts bookmaker/market/line rows, not distinct bookmakers.",
    "Row attempts":
      "All bookmaker odds rows saved across every attempt and every snapshot, including rows that are no longer final.",
    "Req complete":
      "Final snapshots where every required bookmaker from TARGET_BOOKMAKERS was found.",
    "Req partial":
      "Final snapshots where at least one required bookmaker was found, but not all required bookmakers were present.",
    "Req missing":
      "Final snapshots where none of the required bookmakers were found. Odds may still exist from other bookmakers.",
    Bookmakers:
      "Distinct bookmaker names present in final odds rows. The strip and table below list these names; the metric is not bookmaker rows.",
    "Poll seconds":
      "How often an in-window match is scheduled for another odds request.",
    Discovery:
      "Next full BetExplorer match-list refresh. Due captures can still run between discovery cycles from already scheduled matches.",
    Concurrency: "Maximum due matches captured in parallel.",
    "Last run":
      "Most recent completed scheduler cycle. If this is stale while the scheduler is enabled, the API scheduler may be stopped or blocked.",
    "Next run":
      "Expected next scheduler heartbeat based on SCHEDULER_TICK_SECONDS. During an active cycle, it updates after the cycle completes.",
    "Next capture":
      "Earliest next_capture_at among non-finalized matches. Empty means there is no currently scheduled odds capture.",
    "Last odds":
      "Most recent saved odds snapshot timestamp across all matches and markets.",
    "Final snapshot age":
      "How far the selected final snapshot is from kickoff. Positive means before kickoff; negative means after kickoff. Large 'after' values usually mean late backfill.",
    "Browser TZ":
      "Timezone reported by this browser. Displayed for diagnostics only; capture/export use BetExplorer TZ from the API config.",
    "BetExplorer TZ":
      "Timezone offset sent to BetExplorer via the my_timezone cookie and used by UI/export date formatting.",
    "Result capture":
      "Finished results captured once per match during RESULT_CAPTURE_LOOKBACK_HOURS. This is separate from odds capture and does not mean odds were captured.",
    Kickoff:
      "BetExplorer kickoff time in the configured BetExplorer timezone offset.",
    "Capture phase":
      "Scheduler state for this match. FINALIZED means the odds capture window is closed; FINALIZING means the match has started but is still inside the configured post-kickoff window.",
    Timing:
      "Raw timing classifier from kickoff/live-result data. It can say FINISHED even when capture phase explains the odds scheduler state.",
    Required:
      "Presence of required bookmakers in final odds rows for this selected match.",
    Finalized:
      "Time when the scheduler closed the odds capture window for this match.",
    "Result captured":
      "Time when the final score/result was saved. This is separate from odds capture and only happens once per match.",
    "Live score":
      "Live or final score from BetExplorer live-results/result enrichment. It does not imply required bookmakers were found.",
    Snapshots:
      "Saved odds snapshots for the selected match. Only snapshots marked final feed exports and the main match summary.",
    "Match attempts":
      "Capture attempts for the selected match, including retry status and required bookmaker presence for each attempt.",
    "Recent attempts":
      "Latest capture attempts across all matches. Use this to see parser/network failures and retry behavior.",
    "Recent snapshots":
      "Latest saved odds snapshots across all matches and markets. This is capped for display and sorted newest first.",
    Logs: "Recent application log events from the local database. Useful for capture errors, discovery failures, and scheduler status.",
    "Bookmaker coverage":
      "Distinct bookmakers found in final odds rows, with number of matches, total rows, average odds fields, and last seen time.",
    Exports:
      "Generated export files in EXPORT_DIR. Click a file to download it from the local API.",
    all: "Show every stored match, regardless of odds or scheduler state.",
    with_odds: "Only matches with at least one saved final bookmaker row.",
    req_full:
      "Only matches whose final snapshots include all required bookmakers.",
    req_partial:
      "Only matches where at least one required bookmaker is present but the set is incomplete.",
    req_missing:
      "Only matches where final snapshots exist but none of the required bookmakers were found.",
    missing_bwin:
      "Only matches where odds exist but Bwin is missing from final rows.",
    missing_unibet:
      "Only matches where odds exist but Unibet is missing from final rows.",
    capture_miss:
      "Finalized matches where at least one capture attempt ran but no final odds snapshot was saved.",
    skipped_old:
      "Finalized matches skipped because the capture window was already closed before any attempt ran.",
    due: "Only matches currently due or overdue for odds capture.",
    finalized: "Only matches whose odds capture window is closed.",
    new: "Discovered matches without any final snapshot yet.",
    capture_desc: "Sort by latest saved final snapshot first.",
    kickoff_asc:
      "Sort by kickoff time ascending in the configured BetExplorer timezone.",
    bookmakers_desc:
      "Sort by number of final bookmaker/line rows, highest first.",
    attempts_desc: "Sort by number of capture attempts, highest first.",
  };
  return text[label] ?? label;
}

function requiredAvailability(match: MatchRow) {
  return `Bwin:${match.has_bwin ? "yes" : "no"} Unibet:${match.has_unibet ? "yes" : "no"}`;
}

function displayTiming(match: MatchRow) {
  if (match.timing_status !== "UNKNOWN") return match.timing_status;
  if (match.finalized_at) return "FINALIZED";
  if (match.capture_phase) return match.capture_phase;
  if (match.next_capture_at) return "SCHEDULED";
  return "UNKNOWN";
}

function displayCapturePhase(match: MatchRow) {
  if (match.finalized_at) return "FINALIZED";
  return match.capture_phase ?? "DISCOVERED";
}

function timestamp(value: string | null | undefined, timezoneOffset = "+0") {
  if (!value) return 0;
  const parsed = parseLocalApiDate(value, timezoneOffset).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatRequiredJson(value: string | null) {
  if (!value) return "-";
  try {
    const parsed = JSON.parse(value) as Record<string, boolean>;
    return Object.entries(parsed)
      .map(([key, present]) => `${key}:${present ? "yes" : "no"}`)
      .join(" ");
  } catch {
    return value;
  }
}

function clientTimezoneLabel() {
  const zone = Intl.DateTimeFormat()
    .resolvedOptions()
    .timeZone.replace("Kiev", "Kyiv");
  const offsetHours = -new Date().getTimezoneOffset() / 60;
  const offset = `${offsetHours >= 0 ? "+" : ""}${offsetHours}`;
  return `${zone} UTC${offset}`;
}

function parseUtcApiDate(value: string) {
  return new Date(/[zZ]$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
}

function parseLocalApiDate(value: string, timezoneOffset = "+0") {
  return parseOffsetLocalApiDate(value, timezoneOffset);
}

function parseOffsetLocalApiDate(value: string, timezoneOffset: string) {
  if (/[zZ]$|[+-]\d\d:\d\d$/.test(value)) return new Date(value);
  return new Date(`${value}${formatTimezoneOffset(timezoneOffset)}`);
}

function parseTimezoneOffsetMs(value: string) {
  const match = value.trim().match(/^([+-])(\d{1,2})(?::?(\d{2}))?$/);
  if (!match) return 0;
  const sign = match[1] === "-" ? -1 : 1;
  const hours = Number(match[2]);
  const minutes = Number(match[3] ?? "0");
  return sign * (hours * 60 + minutes) * 60 * 1000;
}

function formatTimezoneOffset(value: string) {
  const offsetMs = parseTimezoneOffsetMs(value);
  const sign = offsetMs < 0 ? "-" : "+";
  const absoluteMinutes = Math.abs(offsetMs) / 60000;
  const hours = Math.floor(absoluteMinutes / 60);
  const minutes = absoluteMinutes % 60;
  return `${sign}${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function schedulerFresh(status: Status | null, nowMs: number) {
  if (!status?.last_run) return false;
  if (
    status.running ||
    status.scheduler?.running ||
    status.capture_progress?.running
  )
    return true;
  const allowedLag = Math.max(
    30000,
    (status.scheduler_tick_seconds ?? 10) * 4000,
  );
  return nowMs - parseUtcApiDate(status.last_run).getTime() < allowedLag;
}

function schedulerState(status: Status | null, nowMs: number): SchedulerState {
  if (status?.capture_progress?.running) {
    const progress = status.capture_progress;
    return {
      className: "active",
      label: `Capture ${progress.phase}`,
      detail: `${progress.completed}/${progress.queued} capture jobs completed. Active: ${progress.active}. Trigger: ${progress.trigger ?? "-"}`,
    };
  }
  if (status?.scheduler?.running) {
    return {
      className: "active",
      label: "Scheduler active",
      detail: `API scheduler is running. Tick interval: ${status.scheduler_tick_seconds}s.`,
    };
  }
  if (status?.scheduler && !status.scheduler.enabled) {
    return {
      className: "idle",
      label: "Scheduler disabled",
      detail:
        "ENABLE_API_SCHEDULER is false. Start scripts/run_live_capture.py for continuous capture.",
    };
  }
  if (!status?.last_run) {
    return {
      className: "idle",
      label: "Scheduler idle",
      detail: "No capture heartbeat has completed yet.",
    };
  }
  if (schedulerFresh(status, nowMs)) {
    return {
      className: "active",
      label: "Scheduler active",
      detail: `Heartbeat is fresh. Tick interval: ${status.scheduler_tick_seconds}s.`,
    };
  }
  const overdue = status.next_run
    ? relativeTime(parseUtcApiDate(status.next_run).getTime() - nowMs)
    : "unknown";
  if (status.due_matches > 0) {
    return {
      className: "stale",
      label: "Scheduler idle: due queue",
      detail: `${status.due_matches} match(es) are due, but no scheduler heartbeat has run (${overdue}). Run once is only a manual one-cycle capture.`,
    };
  }
  return {
    className: "idle",
    label: "Scheduler idle",
    detail: `No continuous scheduler heartbeat is running (${overdue}). Run once is only a manual one-cycle capture.`,
  };
}

function buildProgress(
  status: Status | null,
  match: MatchRow | null,
  nowMs: number,
  timezoneOffset: string,
): ProgressState[] {
  const items: ProgressState[] = [];
  const progress = status?.capture_progress;
  if (progress) {
    const hasQueue = progress.queued > 0;
    const value = progress.running
      ? hasQueue
        ? (progress.completed / progress.queued) * 100
        : phaseProgress(progress.phase)
      : progress.queued > 0
        ? 100
        : 0;
    items.push({
      label: progress.running
        ? `Capture ${progress.phase}`
        : "Last capture cycle",
      value,
      detail: hasQueue
        ? `${progress.completed}/${progress.queued} jobs, ${progress.captured} ok, ${progress.failed} failed`
        : `${progress.discovered} discovered, ${progress.due} due, ${progress.results_checked} result checks, ${progress.results_captured} results`,
      tone: progress.failed > 0 ? "warn" : progress.running ? "good" : "idle",
    });
  }
  if (status?.last_run && status.next_run) {
    const start = parseUtcApiDate(status.last_run).getTime();
    const end = parseUtcApiDate(status.next_run).getTime();
    items.push({
      label: "Next heartbeat",
      value: percentBetween(start, end, nowMs),
      detail: relativeTime(end - nowMs),
      tone:
        nowMs >
        end + Math.max(15000, (status.scheduler_tick_seconds ?? 10) * 1000)
          ? "bad"
          : "good",
    });
  }
  if (status?.next_capture) {
    const target = parseLocalApiDate(
      status.next_capture,
      timezoneOffset,
    ).getTime();
    items.push({
      label: "Global next capture",
      value: target <= nowMs ? 100 : 0,
      detail: target <= nowMs ? "due now" : relativeTime(target - nowMs),
      tone: target <= nowMs ? "warn" : "good",
    });
  }
  if (match?.kickoff_time) {
    const kickoff = parseLocalApiDate(
      match.kickoff_time,
      timezoneOffset,
    ).getTime();
    const activeWindowMinutes = Math.max(
      status?.upcoming_window_minutes ?? 30,
      (status?.odds_capture_lookahead_hours ?? 0) * 60,
    );
    const windowStart = kickoff - activeWindowMinutes * 60 * 1000;
    items.push({
      label: "Selected kickoff",
      value: percentBetween(windowStart, kickoff, nowMs),
      detail: kickoff <= nowMs ? "started" : relativeTime(kickoff - nowMs),
      tone: kickoff <= nowMs ? "warn" : "good",
    });
  }
  if (match?.next_capture_at) {
    const target = parseLocalApiDate(
      match.next_capture_at,
      timezoneOffset,
    ).getTime();
    items.push({
      label: "Selected capture",
      value: target <= nowMs ? 100 : 0,
      detail: target <= nowMs ? "due now" : relativeTime(target - nowMs),
      tone: target <= nowMs ? "warn" : "good",
    });
  }
  return items;
}

function phaseProgress(phase: string) {
  const values: Record<string, number> = {
    idle: 0,
    discovery: 15,
    due_scan: 40,
    live_results: 35,
    planning: 55,
    capturing: 75,
    completed: 100,
  };
  return values[phase] ?? 50;
}

function percentBetween(start: number, end: number, now: number) {
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start)
    return 0;
  return ((now - start) / (end - start)) * 100;
}

function relativeTime(ms: number) {
  const overdue = ms < 0;
  const abs = Math.abs(Math.round(ms / 1000));
  if (abs < 60) return overdue ? `overdue ${abs}s` : `${abs}s`;
  const minutes = Math.floor(abs / 60);
  const seconds = abs % 60;
  const value =
    minutes < 60
      ? `${minutes}m ${seconds}s`
      : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  if (overdue) return `overdue ${value}`;
  return value;
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
