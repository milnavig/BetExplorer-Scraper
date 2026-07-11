from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dashboard_hides_poll_seconds_and_concurrency_metrics() -> None:
    page = read_repo_file("apps/desktop/web/app/page.tsx")
    match_page = read_repo_file("apps/desktop/web/app/match/page.tsx")

    assert 'label="Poll seconds"' not in page
    assert 'label="Concurrency"' not in page
    assert "Poll <strong>" not in match_page
    assert "Concurrency <strong>" not in match_page
    assert "Market concurrency" not in match_page


def test_dashboard_prefers_finalized_at_over_stale_finalizing_phase() -> None:
    page = read_repo_file("apps/desktop/web/app/page.tsx")
    match_page = read_repo_file("apps/desktop/web/app/match/page.tsx")
    expected_timing = """if (match.finalized_at) return "FINALIZED";
  if (match.capture_phase) return match.capture_phase;"""
    expected_phase = """function displayCapturePhase(match: MatchRow) {
  if (match.finalized_at) return "FINALIZED";"""

    assert expected_timing in page
    assert expected_timing in match_page
    assert expected_phase in page
    assert expected_phase in match_page
    assert 'label="Capture phase" value={displayCapturePhase(match)}' in match_page


def test_dashboard_dates_use_api_timezone_offset_not_hardcoded_kyiv() -> None:
    page = read_repo_file("apps/desktop/web/app/page.tsx")
    match_page = read_repo_file("apps/desktop/web/app/match/page.tsx")

    assert 'timeZone: "Europe/Kyiv"' not in page
    assert 'timeZone: "Europe/Kyiv"' not in match_page
    assert "betexplorer_timezone_offset" in page
    assert "betexplorer_timezone_offset" in match_page
    assert "formatTimezoneOffset" in page
    assert "formatTimezoneOffset" in match_page


def test_dashboard_bookmaker_strip_does_not_hide_loaded_bookmakers() -> None:
    page = read_repo_file("apps/desktop/web/app/page.tsx")

    assert "bookmakers.slice(0, 12)" not in page
    assert "bookmakers.map((bookmaker)" in page


def test_match_lists_render_incrementally_instead_of_mapping_every_row() -> None:
    page = read_repo_file("apps/desktop/web/app/page.tsx")
    match_page = read_repo_file("apps/desktop/web/app/match/page.tsx")

    assert "MATCH_RENDER_BATCH" in page
    assert "renderedMatches" in page
    assert "filteredMatches.map((match)" not in page
    assert "IntersectionObserver" in page
    assert "Load more matches" in page

    assert "MATCH_RENDER_BATCH" in match_page
    assert "renderedMatches" in match_page
    assert "visibleMatches.map((item)" not in match_page
    assert "IntersectionObserver" in match_page
    assert "Load more matches" in match_page


def test_dashboard_tooltips_explain_metrics_with_operational_context() -> None:
    page = read_repo_file("apps/desktop/web/app/page.tsx")

    expected_phrases = [
        "Total rows in the matches table",
        "Distinct matches that currently have at least one final odds snapshot",
        "Due captures is not a live-match count",
        "Finalized matches that have scrape attempts but still have zero final odds snapshots",
        "Distinct bookmaker names present in final odds rows",
        "Rows saved in the currently selected final snapshots",
        "This is separate from odds capture",
        'title={tooltipFor("Overview nav")}',
        'title={tooltipFor("Refresh data")}',
        'data-testid="download-menu-trigger"',
        'data-testid="import-docx-trigger"',
        'data-testid="import-zip-input"',
        "Import DOCX",
        "importHistoricalZip",
        'fetch(`${API_BASE}/api/historical/import-zip`',
        'accept=".zip,application/zip"',
    ]

    for phrase in expected_phrases:
        assert phrase in page
    assert "Import ZIP" not in page
    assert "importHistoricalDatabase" not in page
    assert 'data-testid="import-zip-trigger"' not in page


def test_dashboard_moves_historical_signals_to_separate_page() -> None:
    page = read_repo_file("apps/desktop/web/app/page.tsx")
    signals_page = read_repo_file("apps/desktop/web/app/signals/page.tsx")

    assert '<section className="panel signals-panel" id="signals">' not in page
    assert 'href="/signals"' in page

    expected_phrases = [
        "Signal monitor",
        "\"/api/signals?actionable_only=true\"",
        "api<HistoricalImportStatus>(\"/api/historical/import-status\")",
        "api(\"/api/signals/recompute\"",
        "similarityBadgeClass",
        "Actionable",
        "BTTS",
        "Sorted by match quality",
        "Match type / Historical sample",
        "Historical archive",
        "Backfill historical date",
        "Current monitored matches are archived automatically",
        "archiveSignalsPath",
        "api<SignalDay[]>(\"/api/signal-days\")",
        "Previous day with signals",
        "Best match first",
        "The API is busy with this job, not offline.",
        "datasetLabel",
        "samples",
        "ArchiveProgressBar",
        "api<ApiStatus>(\"/api/status\")",
        "Capturing final odds and scores",
        "completed / total",
        "date <strong>{archiveResult.date}</strong>",
        "no archive signals were created",
        "setArchiveResult(null)",
        "setArchiveProgress(null)",
    ]

    for phrase in expected_phrases:
        assert phrase in signals_page


def test_dashboard_renders_actionable_signal_feed() -> None:
    signals_page = read_repo_file("apps/desktop/web/app/signals/page.tsx")
    styles = read_repo_file("apps/desktop/web/app/globals.css")

    expected_phrases = [
        "visibleGroups.slice(0, 160).map",
        "groupSignals(signals)",
        "bookmakerOdds(group, \"bwin\")",
        "bookmakerOdds(group, \"unibet\")",
        "current_home_odds",
    ]

    for phrase in expected_phrases:
        assert phrase in signals_page
    assert ".similarity-badge" in styles
    assert ".signal-row" in styles
    assert ".signal-table-head" in styles


def test_dashboard_labels_one_draw_similarity_as_draw_only_not_full_confidence() -> None:
    page = read_repo_file("apps/desktop/web/app/match/page.tsx")
    styles = read_repo_file("apps/desktop/web/app/globals.css")

    assert 'signal.signal_type === "one_draw"' in page
    assert 'return "5 of 6 odds";' in page
    assert 'if (signal.signal_type === "one_draw") return "similarity-badge draw-only";' in page
    assert ".similarity-badge.draw-only" in styles


def test_dashboard_uses_chunked_match_acquisition_and_render_derender_hints() -> None:
    page = read_repo_file("apps/desktop/web/app/page.tsx")
    css = read_repo_file("apps/desktop/web/app/globals.css")

    expected_phrases = [
        "type MatchPageResult",
        "MATCH_PAGE_SIZE",
        "matchesPagePath",
        "loadMatchesPage",
        "api<MatchPageResult>(matchesPagePath",
        "hasMoreServerMatches",
        "isLoadingMatches",
    ]

    for phrase in expected_phrases:
        assert phrase in page
    assert "content-visibility: auto" in css
    assert "contain-intrinsic-size" in css


def test_dashboard_defaults_match_list_to_kickoff_time_and_selected_signals() -> None:
    page = read_repo_file("apps/desktop/web/app/page.tsx")
    api = read_repo_file("apps/api/src/betexplorer_scraper/api.py")
    database = read_repo_file("apps/api/src/betexplorer_scraper/database.py")

    assert 'useState<SortMode>("kickoff_asc")' in page
    assert "SelectedSignalPanel" in page
    assert "Historical similarity" in page
    assert "Current final pre-match odds compared with Odds and Gebruikbare odds" in page
    assert 'from_date: str = ""' in api
    assert "CAST(kickoff_time AS DATE) >= ?" in database


def test_match_page_preserves_deep_link_selection_before_loading_day_list() -> None:
    match_page = read_repo_file("apps/desktop/web/app/match/page.tsx")

    expected_phrases = [
        "didInitialLoadRef",
        "requestedDetail?.match ?? null",
        "requestedMatch &&",
        "setDetail(requestedDetail)",
        "if (!didInitialLoadRef.current) return;",
    ]

    for phrase in expected_phrases:
        assert phrase in match_page


def test_dashboard_polling_splits_fast_status_from_heavy_full_refresh() -> None:
    page = read_repo_file("apps/desktop/web/app/page.tsx")

    assert "DASHBOARD_STATUS_REFRESH_MS" in page
    assert "DASHBOARD_FULL_REFRESH_MS" in page
    assert "loadStatusOnly" in page
    assert "loadDashboardData" in page
    assert "setInterval(() => void load(), 5000)" not in page
    assert "api<MatchPageResult>(matchesPagePath(0))" in page


def test_selected_match_odds_rows_render_incrementally() -> None:
    page = read_repo_file("apps/desktop/web/app/page.tsx")
    match_page = read_repo_file("apps/desktop/web/app/match/page.tsx")

    assert "ODDS_RENDER_BATCH" in page
    assert "renderedBookmakers" in page
    assert "filteredBookmakers.map((row)" not in page
    assert "oddsListMoreRef" in page
    assert "Load more odds rows" in page
    assert "detailCacheRef" in page
    assert "signalCacheRef" in page
    assert 'api<HistoricalSignal[]>(`/api/signals/${selectedId}`)' in page
    assert "Top scores from selected signal" in page
    assert "bestGroup.historical_scores.slice" not in page

    assert "ODDS_RENDER_BATCH" in match_page
    assert "renderedGroupedOddsRows" in match_page
    assert "groupedOddsRows.map((item)" not in match_page
    assert "oddsListMoreRef" in match_page
    assert "Load more odds rows" in match_page
    assert "setDetail(nextDetail);" in match_page
    assert "setSignals(nextSignals);" in match_page
