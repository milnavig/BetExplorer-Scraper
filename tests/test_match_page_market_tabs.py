from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_match_page_renders_prominent_market_tabs_for_all_markets() -> None:
    page = (ROOT / "apps/desktop/web/app/match/page.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "apps/desktop/web/app/globals.css").read_text(encoding="utf-8")

    assert 'className="market-tabs"' in page
    assert 'className={marketFilter === "all_markets" ? "market-tab active" : "market-tab"}' in page
    assert "marketCounts.map((item) => (" in page
    assert "setMarketFilter(item.market)" in page
    assert ".market-tabs" in styles
    assert ".market-tab.active" in styles


def test_match_page_table_groups_rows_by_market_inside_tbody() -> None:
    page = (ROOT / "apps/desktop/web/app/match/page.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "apps/desktop/web/app/globals.css").read_text(encoding="utf-8")

    assert "renderedGroupedOddsRows.map" in page
    assert 'className="market-group-row"' in page
    assert "colSpan={10}" in page
    assert "groupOddsRows(filteredOdds)" in page
    assert ".market-group-row td" in styles


def test_match_page_renders_historical_signals_for_selected_match() -> None:
    page = (ROOT / "apps/desktop/web/app/match/page.tsx").read_text(encoding="utf-8")

    expected_phrases = [
        "type HistoricalSignal",
        "const [signals, setSignals]",
        "api<HistoricalSignal[]>(`/api/signals/${selectedId}`)",
        "Odds intelligence panel",
        "oddsReadinessMessage",
        "What are we comparing?",
        "Compared with historical database",
        "Matched by",
        "Match rule",
        "Historical outcome stats from",
        "Percentages are calculated from historical matches",
        "Example historical full-time scores",
        "Scores shown here come from this selected signal only",
        "View all matched scores",
        "Signal strength",
        "SignalSummaryCard",
        "OutcomeBars",
        "Why matched",
        "Current odds",
        "Historical average",
        "Similarity",
        "Waiting for Unibet final 1X2 odds",
        "No historical match for current Bwin/Unibet odds",
        "signalGroupBookmakerOdds(signals, \"bwin\")",
        "signalGroupBookmakerOdds(signals, \"unibet\")",
        "Home Win %",
        "BTTS",
        "Double Chance",
    ]

    for phrase in expected_phrases:
        assert phrase in page
    assert "ScoreExamples scores={uniqueSorted(signals.flatMap" not in page


def test_match_page_labels_one_draw_similarity_as_draw_only_not_full_confidence() -> None:
    page = (ROOT / "apps/desktop/web/app/match/page.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "apps/desktop/web/app/globals.css").read_text(encoding="utf-8")

    assert 'signal.signal_type === "one_draw"' in page
    assert 'return "One Draw 5/6";' in page
    assert "<span className={similarityBadgeClass(signal)}>{signalSimilarityBadge(signal)}</span>" in page
    assert 'if (signal.signal_type === "one_draw") return "similarity-badge draw-only";' in page
    assert ".similarity-badge.draw-only" in styles
