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

    assert "groupedOddsRows.map" in page
    assert 'className="market-group-row"' in page
    assert "colSpan={10}" in page
    assert "groupOddsRows(filteredOdds)" in page
    assert ".market-group-row td" in styles
