"use client";

import {
  Activity,
  ArrowLeft,
  Clock3,
  ExternalLink,
  Filter,
  RefreshCcw,
  Search,
  Table2
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState, useTransition } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const REQUIRED_BOOKMAKERS = new Set(["bwin", "unibet"]);

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
};

type MatchDetail = {
  match: MatchRow;
  snapshots: SnapshotRow[];
  bookmaker_odds: BookmakerOdds[];
  attempts: AttemptRow[];
};

type Status = {
  betexplorer_timezone_offset: string;
  scheduler_tick_seconds: number;
  final_capture_poll_interval_seconds: number;
  upcoming_window_minutes: number;
  max_concurrent_captures: number;
};

async function api<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { headers: { "Content-Type": "application/json" } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export default function MatchPage() {
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MatchDetail | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [matchQuery, setMatchQuery] = useState("");
  const [oddsQuery, setOddsQuery] = useState("");
  const [requiredOnly, setRequiredOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [clientTimezone, setClientTimezone] = useState("-");

  const loadMatches = async () => {
    setError(null);
    const [nextMatches, nextStatus] = await Promise.all([api<MatchRow[]>("/api/matches"), api<Status>("/api/status")]);
    setMatches(nextMatches);
    setStatus(nextStatus);
    const params = new URLSearchParams(window.location.search);
    const requestedId = params.get("id");
    const nextId = requestedId && nextMatches.some((match) => match.id === requestedId)
      ? requestedId
      : nextMatches[0]?.id ?? null;
    setSelectedId(nextId);
  };

  useEffect(() => {
    setClientTimezone(clientTimezoneLabel());
    loadMatches().catch((nextError) => setError(nextError instanceof Error ? nextError.message : "Failed to load matches"));
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

  const visibleMatches = useMemo(() => {
    const query = matchQuery.trim().toLowerCase();
    return matches.filter((match) => {
      if (!query) return true;
      return [match.event_id, match.league, match.home_team, match.away_team, match.capture_phase, match.quality_status]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [matchQuery, matches]);

  const filteredOdds = useMemo(() => {
    const query = oddsQuery.trim().toLowerCase();
    return (detail?.bookmaker_odds ?? []).filter((row) => {
      const requiredOk = !requiredOnly || REQUIRED_BOOKMAKERS.has(row.normalized_bookmaker);
      const queryOk =
        !query ||
        [
          row.bookmaker,
          row.normalized_bookmaker,
          row.bookmaker_id,
          row.betexplorer_bookmaker_id,
          row.raw_row_text,
          row.raw_attributes_json,
          row.snapshot_quality_status
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query);
      return requiredOk && queryOk;
    });
  }, [detail, oddsQuery, requiredOnly]);

  const match = detail?.match ?? matches.find((item) => item.id === selectedId) ?? null;
  const requiredRows = filteredOdds.filter((row) => REQUIRED_BOOKMAKERS.has(row.normalized_bookmaker));

  const refresh = () => {
    startTransition(async () => {
      await loadMatches();
      if (selectedId) setDetail(await api<MatchDetail>(`/api/matches/${selectedId}`));
    });
  };

  const selectMatch = (id: string) => {
    setSelectedId(id);
    window.history.replaceState(null, "", `/match?id=${encodeURIComponent(id)}`);
  };

  return (
    <main className={isPending ? "shell match-shell is-pending" : "shell match-shell"}>
      <aside className="sidebar match-sidebar">
        <a className="back-link" href="/">
          <ArrowLeft size={16} />
          Dashboard
        </a>
        <div className="match-side-head">
          <h1>Match detail</h1>
          <p>{visibleMatches.length} visible of {matches.length}</p>
        </div>
        <label className="search match-search">
          <Search size={15} />
          <input value={matchQuery} onChange={(event) => setMatchQuery(event.target.value)} placeholder="Search matches" />
        </label>
        <div className="match-picker">
          {visibleMatches.map((item) => (
            <button key={item.id} className={item.id === selectedId ? "picker-row selected" : "picker-row"} onClick={() => selectMatch(item.id)}>
              <span className={`quality ${qualityClass(item.quality_status)}`}>{qualityLabel(item.quality_status)}</span>
              <strong>{item.home_team} - {item.away_team}</strong>
              <small>{formatDate(item.kickoff_time)} · {item.bookmaker_count} bookmakers · {item.attempt_count} tries</small>
            </button>
          ))}
        </div>
      </aside>

      <section className="workspace match-workspace">
        <header className="topbar">
          <div>
            <p className="eyeline">Local API: {API_BASE}</p>
            <h2>
              <span className="live-dot" />
              Full match capture view
            </h2>
          </div>
          <div className="actions">
            <button onClick={refresh} disabled={isPending} title="Refresh match data">
              <RefreshCcw className="refresh-icon" size={16} />
              Refresh
            </button>
            {match ? (
              <a className="icon-link" href={match.source_url} target="_blank" rel="noreferrer" title="Open BetExplorer match">
                <ExternalLink size={16} />
                BetExplorer
              </a>
            ) : null}
          </div>
        </header>

        <section className="capture-config-strip">
          <span>Browser TZ <strong>{clientTimezone}</strong></span>
          <span>BetExplorer TZ <strong>UTC{status?.betexplorer_timezone_offset ?? "-"}</strong></span>
          <span>Poll <strong>{status?.final_capture_poll_interval_seconds ?? "-"}s</strong></span>
          <span>Heartbeat <strong>{status?.scheduler_tick_seconds ?? "-"}s</strong></span>
          <span>Concurrency <strong>{status?.max_concurrent_captures ?? "-"}</strong></span>
          <span>Window <strong>{status?.upcoming_window_minutes ?? "-"}m</strong></span>
        </section>

        {error ? <div className="error">{error}</div> : null}

        {match ? (
          <>
            <section className="match-hero panel">
              <div>
                <p className="eyeline">{match.event_id}</p>
                <h3>{match.home_team} - {match.away_team}</h3>
                <p>{match.league ?? "Unknown league"}</p>
              </div>
              <span className={`quality large ${qualityClass(match.quality_status)}`}>{qualityLabel(match.quality_status)}</span>
            </section>

            <section className="detail-metrics">
              <Info label="Kickoff" value={formatDate(match.kickoff_time)} />
              <Info label="Status" value={match.status ?? "-"} />
              <Info label="Timing" value={displayTiming(match)} />
              <Info label="Capture phase" value={match.capture_phase ?? "DISCOVERED"} />
              <Info label="Next capture" value={formatDate(match.next_capture_at)} />
              <Info label="Last capture" value={formatDate(match.last_capture_at)} />
              <Info label="Finalized" value={formatDate(match.finalized_at)} />
              <Info label="Live score" value={match.live_score ?? "-"} />
              <Info label="Snapshot ID" value={match.snapshot_id ?? "-"} />
              <Info label="Snapshot captured" value={formatDate(match.captured_at)} />
              <Info label="Bookmakers" value={String(match.bookmaker_count)} />
              <Info label="Attempts" value={String(match.attempt_count)} />
            </section>

            <section className="dual-grid match-dual">
              <div className="panel">
                <PanelTitle title="Required bookmaker coverage" subtitle="Quality gate state for this match" icon={<Clock3 size={15} />} />
                <div className="required-cards">
                  <RequiredCard label="Bwin" ok={match.has_bwin} rows={requiredRows.filter((row) => row.normalized_bookmaker === "bwin").length} />
                  <RequiredCard label="Unibet" ok={match.has_unibet} rows={requiredRows.filter((row) => row.normalized_bookmaker === "unibet").length} />
                </div>
              </div>
              <div className="panel">
                <PanelTitle title="Source fields" subtitle="Direct values persisted for the match" icon={<Table2 size={15} />} />
                <div className="kv-grid">
                  <Info label="Match row ID" value={match.id} />
                  <Info label="Event ID" value={match.event_id} />
                  <Info label="Source URL" value={match.source_url} />
                  <Info label="Timing raw" value={match.timing_status} />
                </div>
              </div>
            </section>

            <section className="panel">
              <PanelHeader title="All bookmaker odds rows" subtitle={`${filteredOdds.length} visible of ${detail?.bookmaker_odds.length ?? 0}`} />
              <div className="toolbar table-toolbar">
                <label className="toggle">
                  <input type="checkbox" checked={requiredOnly} onChange={(event) => setRequiredOnly(event.target.checked)} />
                  Required only
                </label>
                <label className="search">
                  <Filter size={15} />
                  <input value={oddsQuery} onChange={(event) => setOddsQuery(event.target.value)} placeholder="Filter bookmaker, IDs, raw fields" />
                </label>
              </div>
              <div className="table-wrap full-table">
                <table>
                  <thead>
                    <tr>
                      <th>Bookmaker</th>
                      <th>Normalized</th>
                      <th>Bookmaker ID</th>
                      <th>BE ID</th>
                      <th>1</th>
                      <th>X</th>
                      <th>2</th>
                      <th>Available</th>
                      <th>Snapshot quality</th>
                      <th>Snapshot captured</th>
                      <th>Created</th>
                      <th>Raw row</th>
                      <th>Raw attributes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredOdds.map((row) => (
                      <tr key={row.id} className={REQUIRED_BOOKMAKERS.has(row.normalized_bookmaker) ? "required" : ""}>
                        <td>{row.bookmaker}</td>
                        <td>{row.normalized_bookmaker}</td>
                        <td>{row.bookmaker_id ?? "-"}</td>
                        <td>{row.betexplorer_bookmaker_id ?? "-"}</td>
                        <td className="odd">{formatOdd(row.home_odds)}</td>
                        <td className="odd">{formatOdd(row.draw_odds)}</td>
                        <td className="odd">{formatOdd(row.away_odds)}</td>
                        <td>{row.is_available ? "yes" : "no"}</td>
                        <td><span className={`quality ${qualityClass(row.snapshot_quality_status)}`}>{qualityLabel(row.snapshot_quality_status)}</span></td>
                        <td>{formatDate(row.snapshot_captured_at)}</td>
                        <td>{formatDate(row.created_at)}</td>
                        <td><code>{row.raw_row_text ?? "-"}</code></td>
                        <td><code>{row.raw_attributes_json ?? "-"}</code></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="dual-grid match-dual">
              <div className="panel">
                <PanelHeader title="Snapshots" subtitle={`${detail?.snapshots.length ?? 0} saved attempts`} />
                <div className="table-wrap medium">
                  <table>
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>Captured</th>
                        <th>Market</th>
                        <th>Type</th>
                        <th>Quality</th>
                        <th>Final candidate</th>
                        <th>Final</th>
                        <th>Source page</th>
                        <th>Rows</th>
                        <th>Required JSON</th>
                        <th>Raw payload</th>
                        <th>Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail?.snapshots ?? []).map((snapshot) => (
                        <tr key={snapshot.id}>
                          <td><code>{snapshot.id}</code></td>
                          <td>{formatDate(snapshot.captured_at)}</td>
                          <td>{snapshot.market}</td>
                          <td>{snapshot.capture_type}</td>
                          <td><span className={`quality ${qualityClass(snapshot.quality_status)}`}>{qualityLabel(snapshot.quality_status)}</span></td>
                          <td>{snapshot.is_final_candidate ? "yes" : "no"}</td>
                          <td>{snapshot.is_final ? "yes" : "no"}</td>
                          <td>{snapshot.source_page_type}</td>
                          <td>{snapshot.bookmaker_count ?? "-"}</td>
                          <td><code>{formatRequiredJson(snapshot.required_bookmakers_json)}</code></td>
                          <td><code>{snapshot.raw_payload_path ?? "-"}</code></td>
                          <td>{formatDate(snapshot.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="panel">
                <PanelHeader title="Attempts" subtitle={`${detail?.attempts.length ?? 0} HTTP/parser attempts`} />
                <div className="table-wrap medium">
                  <table>
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>#</th>
                        <th>Status</th>
                        <th>Started</th>
                        <th>Finished</th>
                        <th>Required found</th>
                        <th>Error</th>
                        <th>Source URL</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail?.attempts ?? []).map((attempt) => (
                        <tr key={attempt.id}>
                          <td><code>{attempt.id}</code></td>
                          <td>{attempt.attempt_number}</td>
                          <td><span className={`quality ${qualityClass(attempt.status)}`}>{qualityLabel(attempt.status)}</span></td>
                          <td>{formatDate(attempt.started_at)}</td>
                          <td>{formatDate(attempt.finished_at)}</td>
                          <td><code>{formatRequiredJson(attempt.required_found_json)}</code></td>
                          <td>{attempt.error_message ?? "-"}</td>
                          <td><code>{attempt.source_url}</code></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          </>
        ) : (
          <div className="panel">
            <p className="empty">No match selected.</p>
          </div>
        )}
      </section>
    </main>
  );
}

function PanelHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="panel-head">
      <div>
        <h3>{title}</h3>
        <p>{subtitle}</p>
      </div>
    </div>
  );
}

function PanelTitle({ title, subtitle, icon }: { title: string; subtitle: string; icon: ReactNode }) {
  return (
    <div className="panel-head compact-head">
      <div>
        <h3>{title}</h3>
        <p>{subtitle}</p>
      </div>
      {icon}
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="info-cell">
      <span>{label}</span>
      <strong title={value}>{value}</strong>
    </div>
  );
}

function RequiredCard({ label, ok, rows }: { label: string; ok: boolean; rows: number }) {
  return (
    <div className={ok ? "required-card ok" : "required-card missing"}>
      <span>{label}</span>
      <strong>{ok ? "present" : "missing"}</strong>
      <small>{rows} odds rows</small>
    </div>
  );
}

function formatDate(value?: string | null) {
  return value
    ? new Intl.DateTimeFormat("en", {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Europe/Kyiv"
      }).format(parseApiDate(value))
    : "-";
}

function formatOdd(value: number | null) {
  return value == null ? "-" : value.toFixed(2);
}

function qualityClass(value?: string | null) {
  if (value === "COMPLETE") return "good";
  if (value === "PARTIAL") return "warn";
  if (value === "FAILED" || value === "ERROR") return "bad";
  return "";
}

function qualityLabel(value?: string | null) {
  if (value === "COMPLETE") return "REQ FULL";
  if (value === "PARTIAL") return "REQ PARTIAL";
  if (value === "FAILED") return "REQ MISSING";
  if (value === "ERROR") return "ERROR";
  return "NO SNAPSHOT";
}

function displayTiming(match: MatchRow) {
  if (match.timing_status !== "UNKNOWN") return match.timing_status;
  if (match.capture_phase) return match.capture_phase;
  if (match.finalized_at) return "FINALIZED";
  if (match.next_capture_at) return "SCHEDULED";
  return "UNKNOWN";
}

function formatRequiredJson(value?: string | null) {
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
