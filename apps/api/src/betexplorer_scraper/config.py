from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    betexplorer_base_url: str = "https://www.betexplorer.com"
    betexplorer_timezone_offset: str = "+3"
    target_bookmakers: str = "Bwin,Unibet"
    capture_market: str = "1x2"
    upcoming_window_minutes: int = 30
    recently_started_window_minutes: int = 10
    max_match_age_after_kickoff_minutes: int = 10
    final_capture_poll_interval_seconds: int = 2
    discovery_poll_interval_seconds: int = 60
    discovery_days_ahead: int = 1
    scheduler_tick_seconds: int = 1
    max_concurrent_captures: int = 6
    max_retries_per_match: int = 3
    retry_delay_seconds: int = 1
    database_path: Path = Field(default=Path("data/betexplorer.duckdb"))
    export_dir: Path = Field(default=Path("data/exports"))
    raw_snapshot_dir: Path = Field(default=Path("data/raw_snapshots"))
    log_dir: Path = Field(default=Path("data/logs"))
    enable_browser_automation: bool = False

    @property
    def required_bookmakers(self) -> list[str]:
        return [item.strip() for item in self.target_bookmakers.split(",") if item.strip()]


def get_settings() -> Settings:
    settings = Settings()
    for path in (settings.export_dir, settings.raw_snapshot_dir, settings.log_dir, settings.database_path.parent):
        path.mkdir(parents=True, exist_ok=True)
    return settings
