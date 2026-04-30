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
  Table2
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState, useTransition } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const REQUIRED_BOOKMAKERS = new Set(["bwin", "unibet"]);

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
  last_capture: string | null;
  last_run: string | null;
  next_run: string | null;
  next_capture: string | null;
  betexplorer_timezone_offset: string;
  scheduler_tick_seconds: number;
  final_capture_poll_interval_seconds: number;
  upcoming_window_minutes: number;
  max_concurrent_captures: number;
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
  snapshot_id: string | null;
  quality_status: string | null;
  captured_at: string | null;
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

type CaptureRunResult = {
  discovered: number;
  due: number;
  captured: number;
  failed: number;
  skipped: number;
  finalized: number;
  waiting: number;
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
type SortMode = "capture_desc" | "kickoff_asc" | "bookmakers_desc" | "attempts_desc";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }
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
  const [requiredOnly, setRequiredOnly] = useState(false);
  const [lastRun, setLastRun] = useState<CaptureRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [clientTimezone, setClientTimezone] = useState("-");

  const load = async () => {
    setError(null);
    try {
      const [nextStatus, nextMatches, nextSnapshots, nextAttempts, nextLogs, nextBookmakers, nextExports] =
        await Promise.all([
          api<Status>("/api/status"),
          api<MatchRow[]>("/api/matches"),
          api<SnapshotRow[]>("/api/snapshots"),
          api<AttemptRow[]>("/api/attempts"),
          api<LogRow[]>("/api/logs"),
          api<BookmakerCoverage[]>("/api/bookmakers"),
          api<ExportFile[]>("/api/exports")
        ]);
      setStatus(nextStatus);
      setMatches(nextMatches);
      setSnapshots(nextSnapshots);
      setAttempts(nextAttempts);
      setLogs(nextLogs);
      setBookmakers(nextBookmakers);
      setExports(nextExports);
      if ((!selectedId || !nextMatches.some((match) => match.id === selectedId)) && nextMatches.length > 0) {
        setSelectedId((nextMatches.find((match) => match.bookmaker_count > 0) ?? nextMatches[0]).id);
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to load API data");
    }
  };

  useEffect(() => {
    setClientTimezone(clientTimezoneLabel());
    void load();
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
      .catch((nextError) => setError(nextError instanceof Error ? nextError.message : "Failed to load match detail"));
    return () => {
      active = false;
    };
  }, [selectedId]);

  const filteredMatches = useMemo(() => {
    const query = matchQuery.trim().toLowerCase();
    const visible = matches.filter((match) => {
      const stateOk =
        matchFilter === "all" ||
        (matchFilter === "with_odds" && match.bookmaker_count > 0) ||
        (matchFilter === "req_full" && match.quality_status === "COMPLETE") ||
        (matchFilter === "req_partial" && match.quality_status === "PARTIAL") ||
        (matchFilter === "req_missing" && match.quality_status === "FAILED") ||
        (matchFilter === "missing_bwin" && match.bookmaker_count > 0 && !match.has_bwin) ||
        (matchFilter === "missing_unibet" && match.bookmaker_count > 0 && !match.has_unibet) ||
        (matchFilter === "capture_miss" && Boolean(match.finalized_at) && match.bookmaker_count === 0 && match.attempt_count > 0) ||
        (matchFilter === "skipped_old" && Boolean(match.finalized_at) && match.bookmaker_count === 0 && match.attempt_count === 0) ||
        (matchFilter === "due" && Boolean(match.next_capture_at)) ||
        (matchFilter === "finalized" && Boolean(match.finalized_at)) ||
        (matchFilter === "new" && !match.quality_status);
      const queryOk =
        !query ||
        [match.league, match.home_team, match.away_team, match.event_id, qualityLabel(match.quality_status), displayTiming(match)]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query);
      return stateOk && queryOk;
    });
    return visible.sort((left, right) => {
      if (sortMode === "kickoff_asc") return timestamp(left.kickoff_time) - timestamp(right.kickoff_time);
      if (sortMode === "bookmakers_desc") return right.bookmaker_count - left.bookmaker_count;
      if (sortMode === "attempts_desc") return right.attempt_count - left.attempt_count;
      return timestamp(right.captured_at) - timestamp(left.captured_at);
    });
  }, [matches, matchFilter, matchQuery, sortMode]);

  const filteredBookmakers = useMemo(() => {
    const rows = detail?.bookmaker_odds ?? [];
    const query = bookmakerQuery.trim().toLowerCase();
    return rows.filter((row) => {
      const requiredOk = !requiredOnly || REQUIRED_BOOKMAKERS.has(row.normalized_bookmaker);
      const queryOk =
        !query ||
        [row.bookmaker, row.normalized_bookmaker, row.bookmaker_id, row.betexplorer_bookmaker_id, row.raw_row_text]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query);
      return requiredOk && queryOk;
    });
  }, [bookmakerQuery, detail, requiredOnly]);

  const selectedMatch = detail?.match ?? matches.find((match) => match.id === selectedId) ?? null;
  const latestExport = exports[0];

  const runCapture = () => {
    startTransition(async () => {
      setError(null);
      try {
        const result = await api<CaptureRunResult>("/api/capture/run-once", { method: "POST" });
        setLastRun(result);
        await load();
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : "Capture failed");
      }
    });
  };

  const exportOdds = (format: "csv" | "xlsx") => {
    startTransition(async () => {
      setError(null);
      try {
        const result = await api<ExportResult>("/api/exports/final-odds", {
          method: "POST",
          body: JSON.stringify({ format })
        });
        window.location.assign(`${API_BASE}${result.download_url}`);
        await load();
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : "Export failed");
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
            <p>API-first 1X2 capture</p>
          </div>
        </div>
        <nav className="nav">
          <a href="#overview">Overview</a>
          <a href="#matches">Matches</a>
          <a href="#detail">Detail</a>
          <a href={selectedMatch ? `/match?id=${encodeURIComponent(selectedMatch.id)}` : "#detail"}>Match page</a>
          <a href="#odds">Odds</a>
          <a href="#attempts">Attempts</a>
          <a href="#exports">Exports</a>
        </nav>
        <div className="side-note">
          <span>Last run</span>
          <strong>{formatDate(status?.last_run)}</strong>
          <small>Next run {formatDate(status?.next_run)}</small>
          <small>Next capture {formatDate(status?.next_capture)}</small>
          <small>Last odds {formatDate(status?.last_capture)}</small>
          <small>Browser TZ {clientTimezone}</small>
          <small>BetExplorer TZ UTC{status?.betexplorer_timezone_offset ?? "-"}</small>
          <small>{latestExport ? `Latest export ${latestExport.filename}` : "No exports yet"}</small>
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
            <button onClick={() => void load()} disabled={isPending} title="Refresh data">
              <RefreshCcw className="refresh-icon" size={16} />
              Refresh
            </button>
            <button onClick={runCapture} disabled={isPending} title="Run one capture cycle">
              <Play size={16} />
              Run once
            </button>
            <button onClick={() => exportOdds("csv")} disabled={isPending} title="Export CSV">
              <Download size={16} />
              CSV
            </button>
            <button onClick={() => exportOdds("xlsx")} disabled={isPending} title="Export Excel">
              <Download size={16} />
              XLSX
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
          </div>
        ) : null}

        <section className="metrics" id="overview">
          <Metric label="Matches" value={status?.matches} />
          <Metric label="Captured" value={status?.captured_matches} tone="good" />
          <Metric label="Capture miss" value={status?.capture_missed_matches} tone="bad" />
          <Metric label="Skipped old" value={status?.skipped_out_of_window_matches} />
          <Metric label="Due now" value={status?.due_matches} tone="warn" />
          <Metric label="Final snapshots" value={status?.snapshots} />
          <Metric label="Attempts" value={status?.snapshot_attempts} />
          <Metric label="Bookmaker rows" value={status?.bookmaker_rows} />
          <Metric label="Row attempts" value={status?.bookmaker_row_attempts} />
          <Metric label="Req complete" value={status?.complete_snapshots} tone="good" />
          <Metric label="Req partial" value={status?.partial_snapshots} tone="warn" />
          <Metric label="Req missing" value={status?.failed_snapshots} tone="bad" />
          <Metric label="Bookmakers" value={bookmakers.length} />
          <Metric label="Poll seconds" value={status?.final_capture_poll_interval_seconds} />
          <Metric label="Concurrency" value={status?.max_concurrent_captures} />
        </section>

        <section className="coverage-strip">
          {bookmakers.slice(0, 12).map((bookmaker) => (
            <div className={REQUIRED_BOOKMAKERS.has(bookmaker.normalized_bookmaker) ? "coverage required" : "coverage"} key={bookmaker.normalized_bookmaker}>
              <span>{bookmaker.bookmaker}</span>
              <strong>{bookmaker.matches}</strong>
              <small>{formatDate(bookmaker.last_seen)}</small>
            </div>
          ))}
        </section>

        <section className="split">
          <div className="panel" id="matches">
            <div className="panel-head">
              <div>
                <h3>Matches</h3>
                <p>{filteredMatches.length} visible of {matches.length}</p>
              </div>
              <label className="search">
                <Search size={15} />
                <input value={matchQuery} onChange={(event) => setMatchQuery(event.target.value)} placeholder="Search teams, league, event" />
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
                  "new"
                ]}
              />
              <SelectFilter
                value={sortMode}
                onChange={(value) => setSortMode(value as SortMode)}
                options={["capture_desc", "kickoff_asc", "bookmakers_desc", "attempts_desc"]}
              />
            </div>
            <div className="match-list">
              {filteredMatches.map((match) => (
                <button
                  key={match.id}
                  className={match.id === selectedId ? "match-row selected" : "match-row"}
                  onClick={() => setSelectedId(match.id)}
                >
                  <span className={`quality ${qualityClass(match.quality_status)}`}>{qualityLabel(match.quality_status)}</span>
                  <span>
                    <strong>{match.home_team}</strong>
                    <small>{match.away_team}</small>
                  </span>
                  <span>
                    <em>{match.league ?? "Unknown league"}</em>
                    <small>{formatDate(match.kickoff_time)} · {match.capture_phase ?? "DISCOVERED"} · {match.attempt_count} tries</small>
                  </span>
                  <span className="required-pair">
                    <Badge label="B" active={match.has_bwin} />
                    <Badge label="U" active={match.has_unibet} />
                  </span>
                  <span className="count">{match.bookmaker_count}</span>
                </button>
              ))}
              {filteredMatches.length === 0 ? <p className="empty">No matches match the current filters.</p> : null}
            </div>
          </div>

          <div className="panel detail-panel" id="detail">
            <div className="panel-head">
              <div>
                <h3>Selected match</h3>
                <p>{selectedMatch ? selectedMatch.event_id : "No match selected"}</p>
              </div>
              <div className="toolbar">
                {selectedMatch ? (
                  <>
                    <a className="icon-link" href={`/match?id=${encodeURIComponent(selectedMatch.id)}`} title="Open full local match page">
                      <Table2 size={16} />
                      Full page
                    </a>
                    <a className="icon-link" href={selectedMatch.source_url} target="_blank" rel="noreferrer" title="Open BetExplorer match">
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
                    <strong>{selectedMatch.home_team} - {selectedMatch.away_team}</strong>
                    <small>{selectedMatch.league ?? "Unknown league"}</small>
                  </div>
                  <span className={`quality large ${qualityClass(selectedMatch.quality_status)}`}>{qualityLabel(selectedMatch.quality_status)}</span>
                </div>

                <div className="info-grid">
                  <Info label="Kickoff" value={formatDate(selectedMatch.kickoff_time)} />
                  <Info label="Capture phase" value={selectedMatch.capture_phase ?? "DISCOVERED"} />
                  <Info label="Timing" value={displayTiming(selectedMatch)} />
                  <Info label="Bookmakers" value={String(selectedMatch.bookmaker_count)} />
                  <Info label="Required" value={requiredAvailability(selectedMatch)} />
                  <Info label="Attempts" value={String(selectedMatch.attempt_count)} />
                  <Info label="Next capture" value={formatDate(selectedMatch.next_capture_at)} />
                  <Info label="Last capture" value={formatDate(selectedMatch.last_capture_at)} />
                  <Info label="Finalized" value={formatDate(selectedMatch.finalized_at)} />
                  <Info label="Live score" value={selectedMatch.live_score ?? "-"} />
                </div>

                <div className="section-stack">
                  <MiniTable title="Snapshots" icon={<Table2 size={15} />}>
                    <thead>
                      <tr>
                        <th>Captured</th>
                        <th>Quality</th>
                        <th>Final</th>
                        <th>Rows</th>
                        <th>Raw payload</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail?.snapshots ?? []).map((snapshot) => (
                        <tr key={snapshot.id}>
                          <td>{formatDate(snapshot.captured_at)}</td>
                          <td><span className={`quality ${qualityClass(snapshot.quality_status)}`}>{qualityLabel(snapshot.quality_status)}</span></td>
                          <td>{snapshot.is_final ? "yes" : "no"}</td>
                          <td>{snapshot.bookmaker_count ?? "-"}</td>
                          <td><code>{snapshot.raw_payload_path ?? "-"}</code></td>
                        </tr>
                      ))}
                    </tbody>
                  </MiniTable>

                  <MiniTable title="Match attempts" icon={<Activity size={15} />}>
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
                          <td><span className={`quality ${qualityClass(attempt.status)}`}>{qualityLabel(attempt.status)}</span></td>
                          <td>{formatDate(attempt.started_at)}</td>
                          <td><code>{formatRequiredJson(attempt.required_found_json)}</code></td>
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
              <p>{detail ? `${filteredBookmakers.length} visible of ${detail.bookmaker_odds.length}` : "Select a match"}</p>
            </div>
            <div className="toolbar">
              <label className="toggle">
                <input type="checkbox" checked={requiredOnly} onChange={(event) => setRequiredOnly(event.target.checked)} />
                Required only
              </label>
              <label className="search">
                <Filter size={15} />
                <input value={bookmakerQuery} onChange={(event) => setBookmakerQuery(event.target.value)} placeholder="Filter bookmakers, IDs, raw text" />
              </label>
            </div>
          </div>
          <div className="table-wrap tall">
            <table>
              <thead>
                <tr>
                  <th>Bookmaker</th>
                  <th>Bookmaker ID</th>
                  <th>BE ID</th>
                  <th>1</th>
                  <th>X</th>
                  <th>2</th>
                  <th>Status</th>
                  <th>Snapshot</th>
                  <th>Raw row</th>
                </tr>
              </thead>
              <tbody>
                {filteredBookmakers.map((row) => (
                  <tr key={row.id} className={REQUIRED_BOOKMAKERS.has(row.normalized_bookmaker) ? "required" : ""}>
                    <td>{row.bookmaker}</td>
                    <td>{row.bookmaker_id ?? "-"}</td>
                    <td>{row.betexplorer_bookmaker_id ?? "-"}</td>
                    <td className="odd">{formatOdd(row.home_odds)}</td>
                    <td className="odd">{formatOdd(row.draw_odds)}</td>
                    <td className="odd">{formatOdd(row.away_odds)}</td>
                    <td>{row.is_available ? "available" : "missing"}</td>
                    <td>{formatDate(row.snapshot_captured_at)}</td>
                    <td><code>{row.raw_row_text ?? "-"}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="tri-grid">
          <div className="panel" id="attempts">
            <PanelTitle title="Recent attempts" subtitle={`${attempts.length} loaded`} />
            <div className="compact-list">
              {attempts.slice(0, 18).map((attempt) => (
                <div className="compact-row" key={attempt.id}>
                  <span className={`quality ${qualityClass(attempt.status)}`}>{qualityLabel(attempt.status)}</span>
                  <strong>{attempt.home_team ?? attempt.event_id} {attempt.away_team ? `- ${attempt.away_team}` : ""}</strong>
                  <small>#{attempt.attempt_number} · {formatDate(attempt.started_at)}</small>
                  {attempt.error_message ? <code>{attempt.error_message}</code> : <code>{formatRequiredJson(attempt.required_found_json)}</code>}
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <PanelTitle title="Recent snapshots" subtitle={`${snapshots.length} loaded`} />
            <div className="compact-list">
              {snapshots.slice(0, 18).map((snapshot) => (
                <div className="compact-row" key={snapshot.id}>
                  <span className={`quality ${qualityClass(snapshot.quality_status)}`}>{qualityLabel(snapshot.quality_status)}</span>
                  <strong>{snapshot.home_team ?? snapshot.event_id} {snapshot.away_team ? `- ${snapshot.away_team}` : ""}</strong>
                  <small>{formatDate(snapshot.captured_at)} · {snapshot.market} · {snapshot.bookmaker_count ?? 0} rows</small>
                  <code>{snapshot.raw_payload_path ?? "-"}</code>
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
                  <small>{formatDate(log.timestamp)} · {log.event_id ?? "-"}</small>
                  <code>{log.details_json}</code>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="dual-grid" id="exports">
          <div className="panel">
            <PanelTitle title="Bookmaker coverage" subtitle={`${bookmakers.length} final-market bookmakers`} />
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
                    <tr key={bookmaker.normalized_bookmaker} className={REQUIRED_BOOKMAKERS.has(bookmaker.normalized_bookmaker) ? "required" : ""}>
                      <td>{bookmaker.bookmaker}</td>
                      <td>{bookmaker.matches}</td>
                      <td>{bookmaker.rows}</td>
                      <td>{formatOdd(bookmaker.avg_home_odds)}</td>
                      <td>{formatOdd(bookmaker.avg_draw_odds)}</td>
                      <td>{formatOdd(bookmaker.avg_away_odds)}</td>
                      <td>{formatDate(bookmaker.last_seen)}</td>
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
                <a href={`${API_BASE}${file.download_url}`} className="export-row" key={file.filename}>
                  <Download size={15} />
                  <span>
                    <strong>{file.filename}</strong>
                    <small>{formatBytes(file.size_bytes)} · {formatDate(file.modified_at)}</small>
                  </span>
                </a>
              ))}
              {exports.length === 0 ? <p className="empty">No export files yet.</p> : null}
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}

function Metric({ label, value, tone }: { label: string; value?: number; tone?: "good" | "warn" | "bad" }) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value ?? 0}</strong>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="info-cell">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Badge({ label, active }: { label: string; active: boolean }) {
  return <span className={active ? "mini-badge active" : "mini-badge"}>{label}</span>;
}

function SelectFilter({ value, onChange, options }: { value: string; onChange: (value: string) => void; options: string[] }) {
  return (
    <label className="select-filter">
      <Filter size={14} />
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>{filterLabel(option)}</option>
        ))}
      </select>
    </label>
  );
}

function PanelTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="panel-head compact-head">
      <div>
        <h3>{title}</h3>
        <p>{subtitle}</p>
      </div>
      <AlertTriangle size={15} />
    </div>
  );
}

function MiniTable({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <div className="mini-table">
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

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Kyiv"
  }).format(parseApiDate(value));
}

function formatOdd(value: number | null) {
  return value == null ? "-" : value.toFixed(2);
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
    due: "Due now",
    finalized: "Finalized",
    new: "No snapshot",
    capture_desc: "Latest capture",
    kickoff_asc: "Kickoff time",
    bookmakers_desc: "Most bookmakers",
    attempts_desc: "Most attempts"
  };
  return labels[value] ?? value;
}

function requiredAvailability(match: MatchRow) {
  return `Bwin:${match.has_bwin ? "yes" : "no"} Unibet:${match.has_unibet ? "yes" : "no"}`;
}

function displayTiming(match: MatchRow) {
  if (match.timing_status !== "UNKNOWN") return match.timing_status;
  if (match.capture_phase) return match.capture_phase;
  if (match.finalized_at) return "FINALIZED";
  if (match.next_capture_at) return "SCHEDULED";
  return "UNKNOWN";
}

function timestamp(value: string | null | undefined) {
  if (!value) return 0;
  const parsed = parseApiDate(value).getTime();
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
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone.replace("Kiev", "Kyiv");
  const offsetHours = -new Date().getTimezoneOffset() / 60;
  const offset = `${offsetHours >= 0 ? "+" : ""}${offsetHours}`;
  return `${zone} UTC${offset}`;
}

function parseApiDate(value: string) {
  return new Date(/[zZ]$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
