"use client";

import {
  Activity,
  ArrowLeft,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
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
const MATCH_RENDER_BATCH = 80;
const MATCH_PAGE_SIZE = 120;
const ODDS_RENDER_BATCH = 160;
const DETAIL_TABLE_PREVIEW_ROWS = 80;

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

type MatchPageResult = {
  items: MatchRow[];
  total: number;
  offset: number;
  limit: number;
};

type MatchDay = {
  date: string;
  matches: number;
  due_or_scheduled: number;
  active: number;
};

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
  matched_odds_home: number | null;
  matched_odds_draw: number | null;
  matched_odds_away: number | null;
  odds_distance_home: number | null;
  odds_distance_draw: number | null;
  odds_distance_away: number | null;
  similarity_score: number;
  match_explanation: string;
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

type GroupedOddsRow =
  | { type: "market"; market: string; count: number }
  | { type: "odds"; row: BookmakerOdds };

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
  const [matchesTotal, setMatchesTotal] = useState(0);
  const [matchDays, setMatchDays] = useState<MatchDay[]>([]);
  const [selectedMatchDate, setSelectedMatchDate] = useState(() => todayDateSlug());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MatchDetail | null>(null);
  const [signals, setSignals] = useState<HistoricalSignal[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [matchQuery, setMatchQuery] = useState("");
  const [oddsQuery, setOddsQuery] = useState("");
  const [marketFilter, setMarketFilter] = useState("all_markets");
  const [requiredOnly, setRequiredOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [isLoadingMatches, setIsLoadingMatches] = useState(false);
  const [clientTimezone, setClientTimezone] = useState("-");
  const selectedIdRef = useRef<string | null>(null);
  const didInitialLoadRef = useRef(false);
  const matchListMoreRef = useRef<HTMLDivElement | null>(null);
  const oddsListMoreRef = useRef<HTMLDivElement | null>(null);
  const [matchRenderLimit, setMatchRenderLimit] = useState(MATCH_RENDER_BATCH);
  const [oddsRenderLimit, setOddsRenderLimit] = useState(ODDS_RENDER_BATCH);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  const matchesPagePath = (date: string, offset: number) => {
    const params = new URLSearchParams({
      q: matchQuery,
      filter: "all",
      sort: "kickoff_asc",
      date,
      offset: String(offset),
      limit: String(MATCH_PAGE_SIZE),
    });
    return `/api/matches-page?${params.toString()}`;
  };

  const applyMatchesPage = (
    nextPage: MatchPageResult,
    mode: "replace" | "append",
    requestedId?: string | null,
    requestedMatch?: MatchRow | null,
  ) => {
    const pageItems =
      mode === "replace" &&
      requestedMatch &&
      !nextPage.items.some((match) => match.id === requestedMatch.id)
        ? [requestedMatch, ...nextPage.items]
        : nextPage.items;
    const nextItems = uniqueMatchesById(pageItems);
    setMatches((current) =>
      mode === "append" ? uniqueMatchesById([...current, ...pageItems]) : nextItems,
    );
    setMatchesTotal(nextPage.total);
    if (mode !== "replace") return;
    setMatchRenderLimit(MATCH_RENDER_BATCH);
    const currentSelectedId = selectedIdRef.current;
    const nextId =
      requestedId && nextItems.some((match) => match.id === requestedId)
        ? requestedId
        : currentSelectedId && nextItems.some((match) => match.id === currentSelectedId)
          ? currentSelectedId
          : nextItems[0]?.id ?? null;
    selectedIdRef.current = nextId;
    setSelectedId(nextId);
  };

  const loadMatchesPage = async (
    date = selectedMatchDate,
    offset = 0,
    mode: "replace" | "append" = "replace",
    requestedId?: string | null,
    requestedMatch?: MatchRow | null,
  ) => {
    setIsLoadingMatches(true);
    try {
      const nextPage = await api<MatchPageResult>(matchesPagePath(date, offset));
      applyMatchesPage(nextPage, mode, requestedId, requestedMatch);
    } finally {
      setIsLoadingMatches(false);
    }
  };

  const loadMatches = async () => {
    setError(null);
    const params = new URLSearchParams(window.location.search);
    const requestedId = params.get("id");
    const [nextStatus, nextMatchDays, requestedDetail] = await Promise.all([
      api<Status>("/api/status"),
      api<MatchDay[]>("/api/match-days"),
      requestedId
        ? api<MatchDetail>(`/api/matches/${requestedId}`).catch(() => null)
        : Promise.resolve(null),
    ]);
    setStatus(nextStatus);
    setMatchDays(nextMatchDays);
    const requestedDate = requestedDetail?.match.kickoff_time?.slice(0, 10);
    const nextDate =
      requestedDate
        ? requestedDate
        : preferredMatchDate(nextMatchDays, todayDateSlug()) ?? todayDateSlug();
    if (requestedDetail) {
      selectedIdRef.current = requestedDetail.match.id;
      setSelectedId(requestedDetail.match.id);
      setDetail(requestedDetail);
    }
    setSelectedMatchDate(nextDate);
    await loadMatchesPage(nextDate, 0, "replace", requestedId, requestedDetail?.match ?? null);
    didInitialLoadRef.current = true;
  };

  useEffect(() => {
    setClientTimezone(clientTimezoneLabel());
    loadMatches().catch((nextError) => setError(nextError instanceof Error ? nextError.message : "Failed to load matches"));
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setSignals([]);
      return;
    }
    let active = true;
    Promise.all([
      api<MatchDetail>(`/api/matches/${selectedId}`),
      api<HistoricalSignal[]>(`/api/signals/${selectedId}`),
    ])
      .then(([nextDetail, nextSignals]) => {
        if (active) {
          startTransition(() => {
            setDetail(nextDetail);
            setSignals(nextSignals);
          });
        }
      })
      .catch((nextError) => setError(nextError instanceof Error ? nextError.message : "Failed to load match detail"));
    return () => {
      active = false;
    };
  }, [selectedId]);

  const visibleMatches = useMemo(() => matches, [matches]);

  useEffect(() => {
    setMatchRenderLimit(MATCH_RENDER_BATCH);
  }, [matchQuery, selectedMatchDate]);

  useEffect(() => {
    if (!didInitialLoadRef.current) return;
    if (matchDays.length === 0) return;
    void loadMatchesPage(selectedMatchDate, 0, "replace");
  }, [matchQuery, selectedMatchDate]);

  const renderedMatches = useMemo(
    () => visibleMatches.slice(0, matchRenderLimit),
    [matchRenderLimit, visibleMatches],
  );
  const hasMoreLoadedMatches = renderedMatches.length < visibleMatches.length;
  const hasMoreServerMatches = matches.length < matchesTotal;
  const hasMoreMatches = hasMoreLoadedMatches || hasMoreServerMatches;
  const loadMoreMatches = () => {
    if (hasMoreLoadedMatches) {
      setMatchRenderLimit((value) =>
        Math.min(value + MATCH_RENDER_BATCH, visibleMatches.length),
      );
      return;
    }
    if (hasMoreServerMatches && !isLoadingMatches) {
      void loadMatchesPage(selectedMatchDate, matches.length, "append");
    }
  };

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
  }, [hasMoreMatches, isLoadingMatches, matches.length, selectedMatchDate, visibleMatches.length]);

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
  const groupedOddsRows = useMemo(() => groupOddsRows(filteredOdds), [filteredOdds]);
  useEffect(() => {
    setOddsRenderLimit(ODDS_RENDER_BATCH);
  }, [marketFilter, oddsQuery, requiredOnly, selectedId]);

  const renderedGroupedOddsRows = useMemo(
    () => groupedOddsRows.slice(0, oddsRenderLimit),
    [groupedOddsRows, oddsRenderLimit],
  );
  const hasMoreOddsRows = renderedGroupedOddsRows.length < groupedOddsRows.length;
  const loadMoreOddsRows = () =>
    setOddsRenderLimit((value) =>
      Math.min(value + ODDS_RENDER_BATCH, groupedOddsRows.length),
    );

  useEffect(() => {
    const node = oddsListMoreRef.current;
    if (!node || !hasMoreOddsRows || !("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadMoreOddsRows();
      },
      { rootMargin: "320px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [groupedOddsRows.length, hasMoreOddsRows]);
  const timezoneOffset = status?.betexplorer_timezone_offset ?? "+0";
  const formatSchedule = (value?: string | null) => formatScheduleDate(value, timezoneOffset);
  const formatUtc = (value?: string | null) => formatUtcDate(value, timezoneOffset);

  useEffect(() => {
    if (marketFilter === "all_markets") return;
    if (!marketCounts.some((item) => item.market === marketFilter)) {
      setMarketFilter("all_markets");
    }
  }, [marketCounts, marketFilter]);

  const refresh = () => {
    startTransition(async () => {
      await loadMatches();
      const currentSelectedId = selectedIdRef.current;
      if (currentSelectedId) {
        const [nextDetail, nextSignals] = await Promise.all([
          api<MatchDetail>(`/api/matches/${currentSelectedId}`),
          api<HistoricalSignal[]>(`/api/signals/${currentSelectedId}`),
        ]);
        setDetail(nextDetail);
        setSignals(nextSignals);
      }
    });
  };

  const selectMatch = (id: string) => {
    selectedIdRef.current = id;
    setDetail(null);
    setSignals([]);
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
          <p>{renderedMatches.length} rendered · {matches.length} loaded of {matchesTotal}</p>
        </div>
        <section className="side-day-selector" aria-label="match day selector">
          <button
            type="button"
            onClick={() => setSelectedMatchDate((value) => adjacentMatchDate(matchDays, value, -1) ?? value)}
            disabled={!adjacentMatchDate(matchDays, selectedMatchDate, -1)}
            title="Previous day with matches"
          >
            <ChevronLeft size={15} />
          </button>
          <div>
            <CalendarDays size={14} />
            <strong>{formatSelectedDay(selectedMatchDate)}</strong>
            <small>{selectedMatchDay(matchDays, selectedMatchDate)?.matches ?? 0}</small>
          </div>
          <button
            type="button"
            onClick={() => setSelectedMatchDate((value) => adjacentMatchDate(matchDays, value, 1) ?? value)}
            disabled={!adjacentMatchDate(matchDays, selectedMatchDate, 1)}
            title="Next day with matches"
          >
            <ChevronRight size={15} />
          </button>
        </section>
        <label className="search match-search">
          <Search size={15} />
          <input value={matchQuery} onChange={(event) => setMatchQuery(event.target.value)} placeholder="Search matches" />
        </label>
        <div className="match-picker">
          {renderedMatches.map((item) => (
            <button key={item.id} className={item.id === selectedId ? "picker-row selected" : "picker-row"} onClick={() => selectMatch(item.id)}>
              <span className={`quality ${qualityClass(item.quality_status)}`}>{qualityLabel(item.quality_status)}</span>
              <strong>{item.home_team} - {item.away_team}</strong>
              <small>{formatSchedule(item.kickoff_time)} · {item.bookmaker_count} bookmakers · {item.attempt_count} tries</small>
            </button>
          ))}
          {isLoadingMatches && renderedMatches.length === 0 ? <MatchListSkeleton /> : null}
          {visibleMatches.length > 0 ? (
            <div className="list-footer" ref={matchListMoreRef}>
              <span>
                  Showing {renderedMatches.length} rendered, {matches.length} loaded of {matchesTotal}
              </span>
              {hasMoreMatches ? (
                <button type="button" onClick={loadMoreMatches}>
                  Load more matches
                </button>
              ) : null}
            </div>
          ) : null}
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
          <span title={tooltipFor("Discovery")}>Discovery <strong>{status?.discovery_poll_interval_seconds ?? "-"}s</strong></span>
          <span title={tooltipFor("Heartbeat")}>Heartbeat <strong>{status?.scheduler_tick_seconds ?? "-"}s</strong></span>
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
              <Info label="Kickoff" value={formatSchedule(match.kickoff_time)} />
              <Info label="Status" value={match.status ?? "-"} />
              <Info label="Timing" value={displayTiming(match)} />
              <Info label="Capture phase" value={displayCapturePhase(match)} />
              <Info label="Next capture" value={formatSchedule(match.next_capture_at)} />
              <Info label="Last capture" value={formatUtc(match.last_capture_at)} />
              <Info label="Finalized" value={formatSchedule(match.finalized_at)} />
              <Info label="Result captured" value={formatUtc(match.result_captured_at)} />
              <Info label="Live score" value={match.live_score ?? "-"} />
              <Info label="Snapshot ID" value={match.snapshot_id ?? "-"} />
              <Info label="Snapshot captured" value={formatUtc(match.captured_at)} />
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

            <section className="panel signals-panel odds-intelligence-panel">
              <PanelHeader
                title="Odds intelligence panel"
                subtitle={oddsReadinessMessage(match, signals)}
              />
              <div className="signal-status">
                <span>Bwin <strong>{match.has_bwin ? "present" : "missing"}</strong></span>
                <span>Unibet <strong>{match.has_unibet ? "present" : "missing"}</strong></span>
                <span>Capture <strong>{displayCapturePhase(match)}</strong></span>
                <span>Final odds age <strong>{formatAgeToKickoff(match.final_snapshot_age_to_kickoff_seconds)}</strong></span>
              </div>
              <div className="intelligence-odds-grid">
                <OddsBookmakerCard bookmaker="Bwin" odds={signalGroupBookmakerOdds(signals, "bwin")} present={match.has_bwin} />
                <OddsBookmakerCard bookmaker="Unibet" odds={signalGroupBookmakerOdds(signals, "unibet")} present={match.has_unibet} />
              </div>
              {signals.length > 0 ? (
                <div className="match-signal-layout">
                  <ComparisonBrief signal={bestSignal(signals)} />
                  <SignalSummaryCard signal={bestSignal(signals)} />
                  <OutcomeBars signal={bestSignal(signals)} />
                  <div className="signal-stats secondary-signal-stats">
                    <Info label="Over 0.5" value={formatPct(bestSignal(signals).over_0_5_pct)} />
                    <Info label="Over 1.5" value={formatPct(bestSignal(signals).over_1_5_pct)} />
                    <Info label="Over 2.5" value={formatPct(bestSignal(signals).over_2_5_pct)} />
                    <Info label="BTTS" value={formatPct(bestSignal(signals).btts_pct)} />
                    <Info
                      label="Double Chance"
                      value={`1X ${formatPct(bestSignal(signals).double_chance_1x_pct)} · X2 ${formatPct(bestSignal(signals).double_chance_x2_pct)} · 12 ${formatPct(bestSignal(signals).double_chance_12_pct)}`}
                    />
                  </div>
                  <WhyMatched signal={bestSignal(signals)} />
                  <ScoreExamples signal={bestSignal(signals)} />
                </div>
              ) : (
                <p className="empty">{historicalEmptyMessage(match)}</p>
              )}
            </section>

            <section className="panel">
              <PanelHeader
                title="All bookmaker odds rows"
                subtitle={`${filteredOdds.length} visible of ${detail?.bookmaker_odds.length ?? 0} · ${marketCounts.map((item) => `${marketLabel(item.market)} ${item.count}`).join(" · ")}`}
              />
              <div className="market-tabs" aria-label="Market filters">
                <button
                  type="button"
                  className={marketFilter === "all_markets" ? "market-tab active" : "market-tab"}
                  onClick={() => setMarketFilter("all_markets")}
                >
                  <strong>All</strong>
                  <span>{detail?.bookmaker_odds.length ?? 0}</span>
                </button>
                {marketCounts.map((item) => (
                  <button
                    type="button"
                    key={item.market}
                    className={marketFilter === item.market ? "market-tab active" : "market-tab"}
                    onClick={() => setMarketFilter(item.market)}
                  >
                    <strong>{marketLabel(item.market)}</strong>
                    <span>{item.count}</span>
                  </button>
                ))}
              </div>
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
                    {renderedGroupedOddsRows.map((item) =>
                      item.type === "market" ? (
                        <tr key={`market-${item.market}`} className="market-group-row">
                          <td colSpan={10}>
                            <strong>{marketLabel(item.market)}</strong>
                            <span>{item.count} rows</span>
                          </td>
                        </tr>
                      ) : (
                        <tr key={item.row.id} className={REQUIRED_BOOKMAKERS.has(item.row.normalized_bookmaker) ? "required" : ""}>
                          <td>{item.row.bookmaker}</td>
                          <td>{marketLabel(item.row.market)}</td>
                          <td><span className="line-pill">{marketLine(item.row)}</span></td>
                          <td>{item.row.normalized_bookmaker}</td>
                          <td>{item.row.bookmaker_id ?? "-"}</td>
                          <td>{item.row.betexplorer_bookmaker_id ?? "-"}</td>
                          <td><PriceSet row={item.row} /></td>
                          <td>{item.row.is_available ? "yes" : "no"}</td>
                          <td>{formatUtc(item.row.snapshot_captured_at)}</td>
                          <td>{formatUtc(item.row.created_at)}</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
                {groupedOddsRows.length > 0 ? (
                  <div className="list-footer" ref={oddsListMoreRef}>
                    <span>
                      Showing {renderedGroupedOddsRows.length} of {groupedOddsRows.length} odds rows
                    </span>
                    {hasMoreOddsRows ? (
                      <button type="button" onClick={loadMoreOddsRows}>
                        Load more odds rows
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </section>

            <section className="dual-grid match-dual">
              <div className="panel">
                <PanelHeader title="Snapshots" subtitle={`${Math.min(detail?.snapshots.length ?? 0, DETAIL_TABLE_PREVIEW_ROWS)} shown of ${detail?.snapshots.length ?? 0} saved attempts`} />
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
                      {(detail?.snapshots ?? []).slice(0, DETAIL_TABLE_PREVIEW_ROWS).map((snapshot) => (
                        <tr key={snapshot.id}>
                          <td><code>{snapshot.id}</code></td>
                          <td>{formatUtc(snapshot.captured_at)}</td>
                          <td>{snapshot.market}</td>
                          <td>{snapshot.capture_type}</td>
                          <td><span className={`quality ${qualityClass(snapshot.quality_status)}`}>{qualityLabel(snapshot.quality_status)}</span></td>
                          <td>{snapshot.is_final_candidate ? "yes" : "no"}</td>
                          <td>{snapshot.is_final ? "yes" : "no"}</td>
                          <td>{snapshot.source_page_type}</td>
                          <td>{snapshot.bookmaker_count ?? "-"}</td>
                          <td>{formatAgeToKickoff(snapshot.final_snapshot_age_to_kickoff_seconds)}</td>
                          <td><code>{formatRequiredJson(snapshot.required_bookmakers_json)}</code></td>
                          <td>{formatUtc(snapshot.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {(detail?.snapshots.length ?? 0) > DETAIL_TABLE_PREVIEW_ROWS ? (
                    <div className="list-footer">
                      <span>Showing latest {DETAIL_TABLE_PREVIEW_ROWS} snapshots to keep the page responsive.</span>
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="panel">
                <PanelHeader title="Attempts" subtitle={`${Math.min(detail?.attempts.length ?? 0, DETAIL_TABLE_PREVIEW_ROWS)} shown of ${detail?.attempts.length ?? 0} HTTP/parser attempts`} />
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
                      {(detail?.attempts ?? []).slice(0, DETAIL_TABLE_PREVIEW_ROWS).map((attempt) => (
                        <tr key={attempt.id}>
                          <td><code>{attempt.id}</code></td>
                          <td>{attempt.attempt_number}</td>
                          <td><span className={`quality ${qualityClass(attempt.status)}`}>{qualityLabel(attempt.status)}</span></td>
                          <td>{formatUtc(attempt.started_at)}</td>
                          <td>{formatUtc(attempt.finished_at)}</td>
                          <td><code>{formatRequiredJson(attempt.required_found_json)}</code></td>
                          <td>{attempt.error_message ?? "-"}</td>
                          <td><code>{attempt.source_url}</code></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {(detail?.attempts.length ?? 0) > DETAIL_TABLE_PREVIEW_ROWS ? (
                    <div className="list-footer">
                      <span>Showing latest {DETAIL_TABLE_PREVIEW_ROWS} attempts to keep the page responsive.</span>
                    </div>
                  ) : null}
                </div>
              </div>
            </section>
          </>
        ) : (
          <div className="panel">
            <DetailSkeleton />
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

function MatchListSkeleton() {
  return (
    <div className="skeleton-stack" aria-label="Loading matches">
      {Array.from({ length: 6 }).map((_, index) => (
        <div className="skeleton-row dark" key={index}>
          <span />
          <strong />
          <small />
        </div>
      ))}
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="detail-skeleton" aria-label="Loading match detail">
      <div className="skeleton-title" />
      <div className="skeleton-grid">
        {Array.from({ length: 8 }).map((_, index) => (
          <span key={index} />
        ))}
      </div>
      <div className="skeleton-block" />
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

function OddsBookmakerCard({ bookmaker, odds, present }: { bookmaker: string; odds: string; present: boolean }) {
  const [home = "-", draw = "-", away = "-"] = odds === "-" ? ["-", "-", "-"] : odds.split(" / ");
  return (
    <div className={present ? "odds-bookmaker-card present" : "odds-bookmaker-card missing"}>
      <span>{bookmaker}</span>
      <div className="price-set large-prices">
        <span className="price-chip"><small>1</small><strong>{home}</strong></span>
        <span className="price-chip"><small>X</small><strong>{draw}</strong></span>
        <span className="price-chip"><small>2</small><strong>{away}</strong></span>
      </div>
    </div>
  );
}

function ComparisonBrief({ signal }: { signal: HistoricalSignal }) {
  return (
    <div className="comparison-brief">
      <div>
        <h4>What are we comparing?</h4>
        <p>
          Current match odds are compared with historical DOCX records that have
          the same or similar BetExplorer 1X2 odds pattern.
        </p>
      </div>
      <div className="comparison-brief-grid">
        <Info
          label="Compared with historical database"
          value={`${historicalDatasetLabel(signal.dataset)} · ${signal.sample_size} matches`}
        />
        <Info label="Matched by" value={matchBasisLabel(signal)} />
        <Info label="Current odds" value={`${formatOdd(signal.current_home_odds)} / ${formatOdd(signal.current_draw_odds)} / ${formatOdd(signal.current_away_odds)}`} />
        <Info label="Signal strength" value={signalStrengthLabel(signal)} />
      </div>
    </div>
  );
}

function SignalSummaryCard({ signal }: { signal: HistoricalSignal }) {
  return (
    <div className="signal-summary-card">
      <div>
        <span className={similarityBadgeClass(signal)}>{signalSimilarityBadge(signal)}</span>
        <h4>{signalTypeLabel(signal.signal_type)}</h4>
        <p>{signal.match_explanation}</p>
      </div>
      <div className="summary-metrics">
        <Info label="Matched by" value={matchBasisLabel(signal)} />
        <Info label="Signal strength" value={signalStrengthLabel(signal)} />
        <Info label="Sample" value={String(signal.sample_size)} />
        <Info label="Dataset" value={historicalDatasetLabel(signal.dataset)} />
      </div>
    </div>
  );
}

function OutcomeBars({ signal }: { signal: HistoricalSignal }) {
  return (
    <div className="outcome-bars">
      <div className="section-explainer">
        <h4>Historical outcome stats from {signal.sample_size} matched matches</h4>
        <p title="Percentages are calculated from historical matches in the DOCX database that matched this odds pattern.">
          Percentages are calculated from historical matches, not from the current match.
        </p>
      </div>
      <OutcomeBar label="Home Win %" value={signal.home_win_pct} />
      <OutcomeBar label="Draw %" value={signal.draw_pct} />
      <OutcomeBar label="Away Win %" value={signal.away_win_pct} />
    </div>
  );
}

function OutcomeBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="outcome-bar">
      <span>{label}</span>
      <strong>{formatPct(value)}</strong>
      <div><i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>
    </div>
  );
}

function WhyMatched({ signal }: { signal: HistoricalSignal }) {
  return (
    <div className="why-matched">
      <h4>Why matched</h4>
      <table>
        <thead>
          <tr>
            <th>Side</th>
            <th>Current odds</th>
            <th>Matched historical odds</th>
            <th>Difference</th>
            <th>Used for match</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>1</td><td>{formatOdd(signal.current_home_odds)}</td><td>{formatOdd(signal.matched_odds_home)}</td><td>{formatOdd(signal.odds_distance_home)}</td><td>{usedForMatch(signal, "home")}</td></tr>
          <tr><td>X</td><td>{formatOdd(signal.current_draw_odds)}</td><td>{formatOdd(signal.matched_odds_draw)}</td><td>{formatOdd(signal.odds_distance_draw)}</td><td>{usedForMatch(signal, "draw")}</td></tr>
          <tr><td>2</td><td>{formatOdd(signal.current_away_odds)}</td><td>{formatOdd(signal.matched_odds_away)}</td><td>{formatOdd(signal.odds_distance_away)}</td><td>{usedForMatch(signal, "away")}</td></tr>
        </tbody>
      </table>
    </div>
  );
}

function ScoreExamples({ signal }: { signal: HistoricalSignal }) {
  const scores = signal.historical_scores;
  return (
    <div className="score-examples">
      <div className="section-explainer">
        <h4>Example historical full-time scores</h4>
        <p>
          Scores shown here come from this selected signal only: {signal.dataset},{" "}
          {signal.sample_size} matched matches.
        </p>
      </div>
      <div className="score-strip">
        {scores.slice(0, 12).map((score, index) => (
          <span key={`${score}-${index}`}>{score}</span>
        ))}
      </div>
      {scores.length > 12 ? (
        <details>
          <summary>View all matched scores</summary>
          <div className="score-strip expanded">
            {scores.map((score, index) => (
              <span key={`all-${score}-${index}`}>{score}</span>
            ))}
          </div>
        </details>
      ) : (
        <button type="button" disabled title="All matched scores are already visible.">
          View all matched scores
        </button>
      )}
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

function formatScheduleDate(value: string | null | undefined, timezoneOffset: string) {
  if (!value) return "-";
  return formatOffsetDate(parseOffsetLocalApiDate(value, timezoneOffset), timezoneOffset);
}

function formatUtcDate(value: string | null | undefined, timezoneOffset: string) {
  if (!value) return "-";
  return formatOffsetDate(parseUtcApiDate(value), timezoneOffset);
}

function formatOffsetDate(date: Date, timezoneOffset: string) {
  const shifted = new Date(date.getTime() + parseTimezoneOffsetMs(timezoneOffset));
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(shifted);
}

function formatOdd(value: number | null) {
  return value == null ? "-" : value.toFixed(2);
}

function formatPct(value: number | null | undefined) {
  return value == null ? "-" : `${value.toFixed(1)}%`;
}

function bestSignal(signals: HistoricalSignal[]) {
  return signals.reduce((best, signal) =>
    compareSignals(signal, best) < 0 ? signal : best,
  );
}

function signalGroupBookmakerOdds(
  signals: HistoricalSignal[],
  normalizedBookmaker: string,
) {
  const signal = signals.find(
    (item) => item.normalized_bookmaker === normalizedBookmaker,
  );
  if (!signal) return "-";
  return `${formatOdd(signal.current_home_odds)} / ${formatOdd(signal.current_draw_odds)} / ${formatOdd(signal.current_away_odds)}`;
}

function uniqueSorted(values: string[]) {
  return [...new Set(values.filter(Boolean))].sort();
}

function compareSignals(left: HistoricalSignal, right: HistoricalSignal) {
  const rank = (left.signal_rank ?? 99) - (right.signal_rank ?? 99);
  if (rank !== 0) return rank;
  const similarity = (right.similarity_score ?? 0) - (left.similarity_score ?? 0);
  if (similarity !== 0) return similarity;
  return right.sample_size - left.sample_size;
}

function signalTypeLabel(value: string) {
  const labels: Record<string, string> = {
    exact_odds: "Exact 6 odds",
    neighbor_odds: "Nearby odds",
    one_draw: "One draw",
  };
  return labels[value] ?? value;
}

function matchBasisLabel(signal: HistoricalSignal) {
  if (signal.signal_type === "exact_odds") return "Bwin + Unibet exact 6 odds";
  if (signal.signal_type === "neighbor_odds") return "Full 1X2 nearby odds";
  if (signal.signal_type === "one_draw") return "One draw odd differs; other five odds match";
  return signal.match_explanation;
}

function signalStrengthLabel(signal: HistoricalSignal) {
  if (signal.signal_type === "exact_odds" && signal.sample_size >= 5) return "High";
  if (signal.signal_type === "neighbor_odds" && signal.similarity_score >= 70 && signal.sample_size >= 5) return "High";
  if (signal.sample_size >= 3) return "Medium";
  return "Low";
}

function usedForMatch(signal: HistoricalSignal, side: "home" | "draw" | "away") {
  return "Yes";
}

function similarityBadgeClass(signal: HistoricalSignal) {
  if (signal.signal_type === "one_draw") return "similarity-badge draw-only";
  const score = signal.similarity_score ?? 0;
  if (score >= 95) return "similarity-badge strong";
  if (score >= 70) return "similarity-badge medium";
  return "similarity-badge weak";
}

function todayDateSlug() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function preferredMatchDate(days: MatchDay[], targetDate: string) {
  if (days.length === 0) return targetDate;
  if (days.some((day) => day.date === targetDate)) return targetDate;
  const target = new Date(`${targetDate}T00:00:00`).getTime();
  return [...days]
    .sort((left, right) => {
      const leftTime = new Date(`${left.date}T00:00:00`).getTime();
      const rightTime = new Date(`${right.date}T00:00:00`).getTime();
      const leftFuture = leftTime >= target ? 0 : 1;
      const rightFuture = rightTime >= target ? 0 : 1;
      if (leftFuture !== rightFuture) return leftFuture - rightFuture;
      return Math.abs(leftTime - target) - Math.abs(rightTime - target);
    })[0]?.date;
}

function selectedMatchDay(days: MatchDay[], selectedDate: string) {
  return days.find((day) => day.date === selectedDate);
}

function uniqueMatchesById(matches: MatchRow[]) {
  const seen = new Set<string>();
  return matches.filter((match) => {
    if (seen.has(match.id)) return false;
    seen.add(match.id);
    return true;
  });
}

function adjacentMatchDate(days: MatchDay[], selectedDate: string, direction: -1 | 1) {
  const sorted = [...days].sort((left, right) => left.date.localeCompare(right.date));
  const index = sorted.findIndex((day) => day.date === selectedDate);
  if (index === -1) return null;
  return sorted[index + direction]?.date ?? null;
}

function formatSelectedDay(value: string) {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

function signalSimilarityBadge(signal: HistoricalSignal) {
  if (signal.signal_type === "exact_odds") return "Exact 6/6 odds";
  if (signal.signal_type === "neighbor_odds") return `Nearby ${formatPct(signal.similarity_score)}`;
  if (signal.signal_type === "one_draw") return "One Draw 5/6";
  return `Similarity ${formatPct(signal.similarity_score)}`;
}

function historicalDatasetLabel(dataset: string) {
  if (dataset === "Odds + Usable Odds") return "Merged Odds + Usable Odds";
  return dataset;
}

function oddsReadinessMessage(match: MatchRow, signals: HistoricalSignal[]) {
  if (!match.has_bwin) return "Waiting for Bwin final 1X2 odds";
  if (!match.has_unibet) return "Waiting for Unibet final 1X2 odds";
  if (signals.length === 0) return "No historical match for current Bwin/Unibet odds";
  return `${signals.length} historical signal rows ranked by similarity`;
}

function historicalEmptyMessage(match: MatchRow) {
  if (!match.has_bwin) return "Waiting for Bwin final 1X2 odds.";
  if (!match.has_unibet) return "Waiting for Unibet final 1X2 odds.";
  return "No historical match for current Bwin/Unibet odds.";
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

function groupOddsRows(rows: BookmakerOdds[]): GroupedOddsRow[] {
  const groups = new Map<string, BookmakerOdds[]>();
  for (const row of rows) {
    const group = groups.get(row.market) ?? [];
    group.push(row);
    groups.set(row.market, group);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => marketSortValue(left) - marketSortValue(right))
    .flatMap(([market, marketRows]) => [
      { type: "market" as const, market, count: marketRows.length },
      ...marketRows.map((row) => ({ type: "odds" as const, row })),
    ]);
}

function marketSortValue(market: string) {
  const order = ["ou", "ah", "ha", "dc", "bts", "1x2"];
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
    Discovery: "How often the app refreshes the BetExplorer match list.",
    Heartbeat: "How often the scheduler loop wakes up.",
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
  if (match.finalized_at) return "FINALIZED";
  if (match.capture_phase) return match.capture_phase;
  if (match.next_capture_at) return "SCHEDULED";
  return "UNKNOWN";
}

function displayCapturePhase(match: MatchRow) {
  if (match.finalized_at) return "FINALIZED";
  return match.capture_phase ?? "DISCOVERED";
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
