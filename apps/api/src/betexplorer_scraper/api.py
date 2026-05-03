from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .clock import utc_now
from .capture import CaptureService
from .config import get_settings
from .database import Database
from .exporter import export_final_odds

settings = get_settings()
database = Database(settings.database_path, timezone_offset=settings.betexplorer_timezone_offset)
service = CaptureService(settings, database)

scheduler_task: asyncio.Task[None] | None = None
scheduler_started_at: datetime | None = None
scheduler_cycle_started_at: datetime | None = None
scheduler_next_run_at: datetime | None = None
scheduler_last_error: str | None = None


async def _api_scheduler_loop() -> None:
    global scheduler_cycle_started_at, scheduler_last_error, scheduler_next_run_at
    database.log("info", "scheduler", "api_scheduler_started")
    while True:
        try:
            scheduler_next_run_at = None
            scheduler_cycle_started_at = utc_now()
            await service.run_once(trigger="api_scheduler", force_discovery=False)
            scheduler_last_error = None
            scheduler_next_run_at = utc_now() + timedelta(seconds=settings.scheduler_tick_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            scheduler_last_error = str(exc)
            database.log("error", "scheduler", "api_scheduler_failed", details={"error": str(exc)})
        await asyncio.sleep(settings.scheduler_tick_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global scheduler_task, scheduler_started_at
    if settings.enable_api_scheduler:
        scheduler_started_at = utc_now()
        scheduler_task = asyncio.create_task(_api_scheduler_loop())
    try:
        yield
    finally:
        if scheduler_task:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
            database.log("info", "scheduler", "api_scheduler_stopped")


app = FastAPI(title="BetExplorer Final Odds API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000", "tauri://localhost"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExportRequest(BaseModel):
    date: str | None = None
    format: str = "csv"
    layout: str = "wide"


@app.get("/api/status")
def status() -> dict[str, object]:
    result = database.status()
    last_run = result.get("last_run")
    progress = service.progress_status()
    api_scheduler_running = bool(scheduler_task and not scheduler_task.done())
    if api_scheduler_running and progress.get("running"):
        result["next_run"] = None
    elif scheduler_next_run_at:
        result["next_run"] = scheduler_next_run_at.isoformat()
    else:
        result["next_run"] = (
            (datetime.fromisoformat(str(last_run)) + timedelta(seconds=settings.scheduler_tick_seconds)).isoformat()
            if last_run
            else None
        )
    result["running"] = api_scheduler_running or bool(progress.get("running"))
    result["scheduler"] = {
        "enabled": settings.enable_api_scheduler,
        "running": api_scheduler_running,
        "started_at": scheduler_started_at.isoformat() if scheduler_started_at else None,
        "cycle_started_at": scheduler_cycle_started_at.isoformat() if scheduler_cycle_started_at else None,
        "next_run_at": scheduler_next_run_at.isoformat() if scheduler_next_run_at else None,
        "last_error": scheduler_last_error,
    }
    result["capture_progress"] = progress
    result["betexplorer_timezone_offset"] = settings.betexplorer_timezone_offset
    result["scheduler_tick_seconds"] = settings.scheduler_tick_seconds
    result["monitoring_capture_poll_interval_seconds"] = settings.monitoring_capture_poll_interval_seconds
    result["final_capture_poll_interval_seconds"] = settings.final_capture_poll_interval_seconds
    result["final_capture_fast_window_minutes"] = settings.final_capture_fast_window_minutes
    result["finalize_after_kickoff_minutes"] = settings.finalize_after_kickoff_minutes
    result["discovery_poll_interval_seconds"] = settings.discovery_poll_interval_seconds
    result["upcoming_window_minutes"] = settings.upcoming_window_minutes
    result["odds_capture_lookahead_hours"] = settings.odds_capture_lookahead_hours
    result["result_capture_lookback_hours"] = settings.result_capture_lookback_hours
    result["result_finish_grace_minutes"] = settings.result_finish_grace_minutes
    result["max_concurrent_captures"] = settings.max_concurrent_captures
    result["max_concurrent_markets_per_match"] = settings.max_concurrent_markets_per_match
    result["market_discovery_cache_seconds"] = settings.market_discovery_cache_seconds
    result["next_capture"] = _fresh_next_capture(result.get("next_capture"))
    return result


def _fresh_next_capture(value: object) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    today = datetime.now().date()
    return parsed.isoformat() if parsed.date() >= today else None


@app.get("/api/matches")
def matches() -> list[dict[str, object]]:
    return database.list_matches()


@app.get("/api/matches/{match_id}")
def match_detail(match_id: str) -> dict[str, object]:
    detail = database.match_detail(match_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Match not found")
    return detail


@app.get("/api/snapshots")
def snapshots() -> list[dict[str, object]]:
    return database.list_snapshots()


@app.get("/api/attempts")
def attempts() -> list[dict[str, object]]:
    return database.list_attempts()


@app.get("/api/logs")
def logs() -> list[dict[str, object]]:
    return database.list_logs()


@app.get("/api/bookmakers")
def bookmakers() -> list[dict[str, object]]:
    return database.bookmaker_coverage()


@app.get("/api/exports")
def exports() -> list[dict[str, object]]:
    if not settings.export_dir.exists():
        return []
    files = []
    for path in sorted(settings.export_dir.glob("final_odds_*.*"), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.suffix.lower() not in {".csv", ".xlsx"}:
            continue
        stat = path.stat()
        files.append(
            {
                "filename": path.name,
                "path": str(path),
                "download_url": f"/api/exports/{path.name}",
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return files[:100]


@app.post("/api/capture/run-once")
async def capture_run_once() -> dict[str, int]:
    return await service.run_once()


@app.post("/api/exports/final-odds")
def export_final_odds_endpoint(request: ExportRequest) -> dict[str, str]:
    fmt = request.format.lower()
    layout = request.layout.lower()
    date_slug = request.date or utc_now().strftime("%Y-%m-%d")
    try:
        path = export_final_odds(
            database.final_snapshot_items(),
            settings.export_dir,
            date_slug,
            fmt,
            settings.betexplorer_timezone_offset,
            layout,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"path": str(path), "filename": path.name, "download_url": f"/api/exports/{path.name}"}


@app.get("/api/exports/{filename}")
def download_export(filename: str) -> FileResponse:
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="Invalid export filename")
    export_dir = settings.export_dir.resolve()
    path = (settings.export_dir / filename).resolve()
    if export_dir not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid export path")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Export not found")
    media_type = "text/csv" if path.suffix.lower() == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path, media_type=media_type, filename=path.name)
