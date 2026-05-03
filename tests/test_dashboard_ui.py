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
    expected = """if (match.finalized_at) return "FINALIZED";
  if (match.capture_phase) return match.capture_phase;"""

    assert expected in page
    assert expected in match_page
