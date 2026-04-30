from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

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
database = Database(settings.database_path)
service = CaptureService(settings, database)

app = FastAPI(title="BetExplorer Final Odds API")
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


@app.get("/api/status")
def status() -> dict[str, object]:
    result = database.status()
    last_run = result.get("last_run")
    result["next_run"] = (
        (datetime.fromisoformat(str(last_run)) + timedelta(seconds=settings.scheduler_tick_seconds)).isoformat()
        if last_run
        else None
    )
    result["betexplorer_timezone_offset"] = settings.betexplorer_timezone_offset
    result["scheduler_tick_seconds"] = settings.scheduler_tick_seconds
    result["final_capture_poll_interval_seconds"] = settings.final_capture_poll_interval_seconds
    result["upcoming_window_minutes"] = settings.upcoming_window_minutes
    result["max_concurrent_captures"] = settings.max_concurrent_captures
    return result


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
    date_slug = request.date or utc_now().strftime("%Y-%m-%d")
    try:
        path = export_final_odds(database.final_snapshot_items(), settings.export_dir, date_slug, fmt)
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
