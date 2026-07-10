from __future__ import annotations

from pathlib import Path

from betexplorer_scraper.config import PROJECT_ROOT, get_settings


def test_get_settings_resolves_relative_paths_from_project_root(monkeypatch) -> None:
    monkeypatch.chdir(PROJECT_ROOT / "apps" / "api")

    settings = get_settings()

    assert settings.database_path == PROJECT_ROOT / "data" / "betexplorer.duckdb"
    assert settings.raw_snapshot_dir == PROJECT_ROOT / "data" / "raw_snapshots"
    assert settings.export_dir == PROJECT_ROOT / "data" / "exports"
    assert settings.log_dir == PROJECT_ROOT / "data" / "logs"
    assert settings.historical_database_root == PROJECT_ROOT / "SAMPLE_DATABASE"
    assert not str(settings.database_path).startswith(str(Path.cwd()))
