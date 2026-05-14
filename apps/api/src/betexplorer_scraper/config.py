from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True)

    betexplorer_base_url: str = "https://www.betexplorer.com"
    betexplorer_timezone_offset: str = "+3"
    target_bookmakers: str = "Bwin,Unibet"
    capture_market: str = "all"
    upcoming_window_minutes: int = 30
    odds_capture_lookahead_hours: int = 6
    result_capture_lookback_hours: int = 24
    result_finish_grace_minutes: int = 120
    result_check_retry_seconds: int = 3600
    result_backfill_batch_size: int = 200
    recently_started_window_minutes: int = 10
    finalize_after_kickoff_minutes: int = Field(
        default=5,
        validation_alias=AliasChoices("FINALIZE_AFTER_KICKOFF_MINUTES", "MAX_MATCH_AGE_AFTER_KICKOFF_MINUTES"),
    )
    monitoring_capture_poll_interval_seconds: int = 120
    final_capture_poll_interval_seconds: int = 20
    final_capture_fast_window_minutes: int = 3
    discovery_poll_interval_seconds: int = 60
    discovery_days_ahead: int = 1
    scheduler_tick_seconds: int = 10
    enable_api_scheduler: bool = True
    max_concurrent_captures: int = 6
    max_concurrent_markets_per_match: int = 3
    market_discovery_cache_seconds: int = 600
    max_retries_per_match: int = 3
    retry_delay_seconds: int = 1
    database_path: Path = Field(default=Path("data/betexplorer.duckdb"))
    export_dir: Path = Field(default=Path("data/exports"))
    raw_snapshot_dir: Path = Field(default=Path("data/raw_snapshots"))
    log_dir: Path = Field(default=Path("data/logs"))
    historical_database_root: Path = Field(default=Path("SAMPLE_DATABASE"))
    enable_browser_automation: bool = False

    @property
    def required_bookmakers(self) -> list[str]:
        return [item.strip() for item in self.target_bookmakers.split(",") if item.strip()]

    @property
    def max_match_age_after_kickoff_minutes(self) -> int:
        return self.finalize_after_kickoff_minutes


def get_settings() -> Settings:
    settings = Settings()
    for path in (settings.export_dir, settings.raw_snapshot_dir, settings.log_dir, settings.database_path.parent):
        path.mkdir(parents=True, exist_ok=True)
    return settings
