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
import { useEffect, useMemo, useRef, useState, useTransition } from "react";

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
  const [marketFilter, setMarketFilter] = useState("all_markets");
  const [requiredOnly, setRequiredOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [clientTimezone, setClientTimezone] = useState("-");
  const selectedIdRef = useRef<string | null>(null);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  const loadMatches = async () => {
    setError(null);
    const [nextMatches, nextStatus] = await Promise.all([api<MatchRow[]>("/api/matches"), api<Status>("/api/status")]);
    setMatches(nextMatches);
    setStatus(nextStatus);
    const params = new URLSearchParams(window.location.search);
    const requestedId = params.get("id");
    const currentSelectedId = selectedIdRef.current;
    const nextId =
      requestedId && nextMatches.some((match) => match.id === requestedId)
        ? requestedId
        : currentSelectedId && nextMatches.some((match) => match.id === currentSelectedId)
          ? currentSelectedId
          : nextMatches[0]?.id ?? null;
    selectedIdRef.current = nextId;
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
      const marketOk = marketFilter === "all_markets" || row.market === marketFilter;
      const queryOk =
        !query ||
        [
          row.market,
          marketLabel(row.market),
          marketLine(row),
          row.bookmaker,
          row.normalized_bookmaker,
          row.bookmaker_id,
          row.betexplorer_bookmaker_id
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query);
      return requiredOk && marketOk && queryOk;
    });
  }, [detail, marketFilter, oddsQuery, requiredOnly]);

  const match = detail?.match ?? matches.find((item) => item.id === selectedId) ?? null;
  const requiredRows = filteredOdds.filter((row) => REQUIRED_BOOKMAKERS.has(row.normalized_bookmaker));
  const marketCounts = useMemo(() => marketCountsFor(detail?.bookmaker_odds ?? []), [detail]);

  const refresh = () => {
    startTransition(async () => {
      await loadMatches();
      const currentSelectedId = selectedIdRef.current;
      if (currentSelectedId) setDetail(await api<MatchDetail>(`/api/matches/${currentSelectedId}`));
    });
  };

  const selectMatch = (id: string) => {
    selectedIdRef.current = id;
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
              <small>{formatScheduleDate(item.kickoff_time)} · {item.bookmaker_count} bookmakers · {item.attempt_count} tries</small>
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
          <span title={tooltipFor("Browser TZ")}>Browser TZ <strong>{clientTimezone}</strong></span>
          <span title={tooltipFor("BetExplorer TZ")}>BetExplorer TZ <strong>UTC{status?.betexplorer_timezone_offset ?? "-"}</strong></span>
          <span title={tooltipFor("Poll")}>Poll <strong>{status?.monitoring_capture_poll_interval_seconds ?? "-"}s / {status?.final_capture_poll_interval_seconds ?? "-"}s</strong></span>
          <span title={tooltipFor("Discovery")}>Discovery <strong>{status?.discovery_poll_interval_seconds ?? "-"}s</strong></span>
          <span title={tooltipFor("Heartbeat")}>Heartbeat <strong>{status?.scheduler_tick_seconds ?? "-"}s</strong></span>
          <span title={tooltipFor("Concurrency")}>Concurrency <strong>{status?.max_concurrent_captures ?? "-"}</strong></span>
          <span title={tooltipFor("Market concurrency")}>Markets <strong>{status?.max_concurrent_markets_per_match ?? "-"}</strong></span>
          <span title={tooltipFor("Window")}>Odds lookahead <strong>{status?.odds_capture_lookahead_hours ?? "-"}h</strong></span>
          <span title={tooltipFor("Results")}>Results <strong>{status?.result_capture_lookback_hours ?? "-"}h</strong></span>
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
              <Info label="Kickoff" value={formatScheduleDate(match.kickoff_time)} />
              <Info label="Status" value={match.status ?? "-"} />
              <Info label="Timing" value={displayTiming(match)} />
              <Info label="Capture phase" value={match.capture_phase ?? "DISCOVERED"} />
              <Info label="Next capture" value={formatScheduleDate(match.next_capture_at)} />
              <Info label="Last capture" value={formatUtcDate(match.last_capture_at)} />
              <Info label="Finalized" value={formatScheduleDate(match.finalized_at)} />
              <Info label="Result captured" value={formatUtcDate(match.result_captured_at)} />
              <Info label="Live score" value={match.live_score ?? "-"} />
              <Info label="Snapshot ID" value={match.snapshot_id ?? "-"} />
              <Info label="Snapshot captured" value={formatUtcDate(match.captured_at)} />
              <Info label="Final snapshot age" value={formatAgeToKickoff(match.final_snapshot_age_to_kickoff_seconds)} />
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
              <PanelHeader
                title="All bookmaker odds rows"
                subtitle={`${filteredOdds.length} visible of ${detail?.bookmaker_odds.length ?? 0} · ${marketCounts.map((item) => `${marketLabel(item.market)} ${item.count}`).join(" · ")}`}
              />
              <div className="toolbar table-toolbar">
                <label className="toggle">
                  <input type="checkbox" checked={requiredOnly} onChange={(event) => setRequiredOnly(event.target.checked)} />
                  Required only
                </label>
                <label className="select-filter" title="Filter bookmaker rows by market">
                  <Filter size={14} />
                  <select value={marketFilter} onChange={(event) => setMarketFilter(event.target.value)}>
                    <option value="all_markets">All markets</option>
                    {marketCounts.map((item) => (
                      <option key={item.market} value={item.market}>
                        {marketLabel(item.market)} ({item.count})
                      </option>
                    ))}
                  </select>
                </label>
                <label className="search">
                  <Filter size={15} />
                  <input value={oddsQuery} onChange={(event) => setOddsQuery(event.target.value)} placeholder="Filter market, bookmaker, IDs" />
                </label>
              </div>
              <div className="table-wrap full-table">
                <table>
                  <thead>
                    <tr>
                      <th>Bookmaker</th>
                      <th>Market</th>
                      <th>Line</th>
                      <th>Normalized</th>
                      <th>Bookmaker ID</th>
                      <th>BE ID</th>
                      <th>Prices</th>
                      <th>Available</th>
                      <th>Snapshot captured</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredOdds.map((row) => (
                      <tr key={row.id} className={REQUIRED_BOOKMAKERS.has(row.normalized_bookmaker) ? "required" : ""}>
                        <td>{row.bookmaker}</td>
                        <td>{marketLabel(row.market)}</td>
                        <td><span className="line-pill">{marketLine(row)}</span></td>
                        <td>{row.normalized_bookmaker}</td>
                        <td>{row.bookmaker_id ?? "-"}</td>
                        <td>{row.betexplorer_bookmaker_id ?? "-"}</td>
                        <td><PriceSet row={row} /></td>
                        <td>{row.is_available ? "yes" : "no"}</td>
                        <td>{formatUtcDate(row.snapshot_captured_at)}</td>
                        <td>{formatUtcDate(row.created_at)}</td>
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
                        <th title={tooltipFor("Odds rows")}>Odds rows</th>
                        <th>To kickoff</th>
                        <th>Required JSON</th>
                        <th>Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail?.snapshots ?? []).map((snapshot) => (
                        <tr key={snapshot.id}>
                          <td><code>{snapshot.id}</code></td>
                          <td>{formatUtcDate(snapshot.captured_at)}</td>
                          <td>{snapshot.market}</td>
                          <td>{snapshot.capture_type}</td>
                          <td><span className={`quality ${qualityClass(snapshot.quality_status)}`}>{qualityLabel(snapshot.quality_status)}</span></td>
                          <td>{snapshot.is_final_candidate ? "yes" : "no"}</td>
                          <td>{snapshot.is_final ? "yes" : "no"}</td>
                          <td>{snapshot.source_page_type}</td>
                          <td>{snapshot.bookmaker_count ?? "-"}</td>
                          <td>{formatAgeToKickoff(snapshot.final_snapshot_age_to_kickoff_seconds)}</td>
                          <td><code>{formatRequiredJson(snapshot.required_bookmakers_json)}</code></td>
                          <td>{formatUtcDate(snapshot.created_at)}</td>
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
                          <td>{formatUtcDate(attempt.started_at)}</td>
                          <td>{formatUtcDate(attempt.finished_at)}</td>
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
    <div className="panel-head compact-head" title={subtitle}>
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
    <div className="info-cell" title={`${tooltipFor(label)} Current value: ${value}`}>
      <span>{label}</span>
      <strong title={value}>{value}</strong>
    </div>
  );
}

function RequiredCard({ label, ok, rows }: { label: string; ok: boolean; rows: number }) {
  return (
    <div className={ok ? "required-card ok" : "required-card missing"} title={`${label} required bookmaker ${ok ? "is present" : "is missing"} in final odds rows.`}>
      <span>{label}</span>
      <strong>{ok ? "present" : "missing"}</strong>
      <small>{rows} odds rows</small>
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

function formatScheduleDate(value?: string | null) {
  return value
    ? new Intl.DateTimeFormat("en", {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Europe/Kyiv"
      }).format(parseLocalApiDate(value))
    : "-";
}

function formatUtcDate(value?: string | null) {
  return value
    ? new Intl.DateTimeFormat("en", {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Europe/Kyiv"
      }).format(parseUtcApiDate(value))
    : "-";
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
    dnb: "Draw No Bet"
  };
  return labels[(market ?? "").toLowerCase()] ?? (market ? market.toUpperCase() : "-");
}

function marketCountsFor(rows: BookmakerOdds[]) {
  const counts = new Map<string, number>();
  for (const row of rows) {
    counts.set(row.market, (counts.get(row.market) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([market, count]) => ({ market, count }))
    .sort((left, right) => marketSortValue(left.market) - marketSortValue(right.market));
}

function marketSortValue(market: string) {
  const order = ["1x2", "ou", "ah", "ha", "dc", "bts"];
  const index = order.indexOf(market.toLowerCase());
  return index === -1 ? order.length : index;
}

function marketLine(row: BookmakerOdds) {
  const attrs = parseRawAttributes(row.raw_attributes_json);
  const explicit = attrs.market_line ?? attrs.line ?? attrs.handicap ?? attrs.total;
  if (explicit != null && String(explicit).trim()) return String(explicit).trim();
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

function parseRawAttributes(value: string | null | undefined): Record<string, unknown> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
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

function tooltipFor(label: string) {
  const text: Record<string, string> = {
    "Browser TZ": "Timezone reported by this browser.",
    "BetExplorer TZ": "Timezone offset sent to BetExplorer via the my_timezone cookie.",
    Poll: "Odds polling cadence: normal capture window / final fast window.",
    Discovery: "How often the app refreshes the BetExplorer match list.",
    Heartbeat: "How often the scheduler loop wakes up.",
    Concurrency: "Maximum due matches captured in parallel.",
    "Market concurrency": "Maximum market endpoints captured in parallel inside one match.",
    Window: "Hours before kickoff when active odds capture begins.",
    Results: "How far back finished matches are checked for one-time result capture.",
    Kickoff: "BetExplorer kickoff time in the configured BetExplorer/client timezone.",
    Status: "Raw match status persisted from discovery/live enrichment.",
    Timing: "Timing classification relative to kickoff and live status.",
    "Capture phase": "Scheduler state for this match.",
    "Next capture": "Next scheduled odds request for this match.",
    "Last capture": "Most recent saved odds snapshot timestamp.",
    Finalized: "Time when the scheduler closed the capture window.",
    "Result captured": "Time when the final score/result was saved. This is separate from odds capture and only happens once per match.",
    "Live score": "Live/recent score from BetExplorer live-results enrichment.",
    "Snapshot ID": "Latest final snapshot id used for summary display.",
    "Snapshot captured": "Timestamp for the latest final snapshot.",
    "Final snapshot age": "How far the selected final snapshot is from kickoff. Positive means before kickoff; negative means after kickoff.",
    "Odds rows": "Bookmaker/line rows saved for this snapshot. Simple markets may have 2-3 rows; Asian Handicap and Over/Under can have many rows because every line is stored separately.",
    Bookmakers: "Bookmaker odds rows in final snapshots for this match. Modified markets like Asian Handicap and Over/Under can have many rows because each line is stored separately.",
    Attempts: "HTTP/parser attempts recorded for this match.",
    "Match row ID": "Local database id for this match row.",
    "Event ID": "BetExplorer/Flashscore event id.",
    "Source URL": "BetExplorer match page URL.",
    "Timing raw": "Raw timing_status stored in the database."
  };
  return text[label] ?? label;
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

function parseUtcApiDate(value: string) {
  return new Date(/[zZ]$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
}

function parseLocalApiDate(value: string) {
  return new Date(value);
}
