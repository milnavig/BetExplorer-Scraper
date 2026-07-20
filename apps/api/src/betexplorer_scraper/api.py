from __future__ import annotations

import asyncio
import io
import hashlib
import re
import zipfile
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .clock import utc_now
from .capture import CaptureService
from .config import get_settings
from .database import Database
from .exporter import export_final_odds, export_played_match_archive
from .historical import HistoricalDocxImporter, HistoricalSignalAutoRefresh

settings = get_settings()
database = Database(settings.database_path, timezone_offset=settings.betexplorer_timezone_offset)
service = CaptureService(settings, database)
historical_importer = HistoricalDocxImporter(database)
historical_auto_refresh = HistoricalSignalAutoRefresh(
    database,
    historical_importer,
    [settings.historical_database_root],
)

scheduler_task: asyncio.Task[None] | None = None
scheduler_started_at: datetime | None = None
scheduler_cycle_started_at: datetime | None = None
scheduler_next_run_at: datetime | None = None
scheduler_last_error: str | None = None
archive_tasks: dict[str, asyncio.Task[None]] = {}
maintenance_tasks: dict[str, asyncio.Task[None]] = {}
status_refresh_task: asyncio.Task[None] | None = None
status_snapshot: dict[str, object] | None = None
status_snapshot_database_id: int | None = None
status_snapshot_updated_at: datetime | None = None
status_snapshot_error: str | None = None
read_database: Database | None = None
read_database_source_id: int | None = None


def _reader() -> Database:
    global read_database, read_database_source_id
    if str(database.path) == ":memory:":
        return database
    if read_database is None or read_database_source_id != id(database):
        if read_database is not None:
            with suppress(Exception):
                read_database.connection.close()
        read_database = Database(database.path, timezone_offset=database.timezone_offset, initialize=False)
        read_database_source_id = id(database)
    return read_database


def _refresh_status_snapshot() -> None:
    global status_snapshot, status_snapshot_database_id, status_snapshot_updated_at, status_snapshot_error
    try:
        status_snapshot = _reader().status()
        status_snapshot_database_id = id(database)
        status_snapshot_updated_at = utc_now()
        status_snapshot_error = None
    except Exception as exc:
        status_snapshot_error = str(exc)


async def _status_refresh_loop() -> None:
    while True:
        await asyncio.to_thread(_refresh_status_snapshot)
        await asyncio.sleep(15)


async def _run_archive_job(job_id: str, target_date: date) -> None:
    try:
        await service.run_archive_job(job_id, target_date)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        database.log(
            "error",
            "archive",
            "archive_job_failed",
            details={"job_id": job_id, "date": target_date.isoformat(), "error": str(exc)},
        )
    finally:
        archive_tasks.pop(job_id, None)


def _schedule_archive_job(job: dict[str, object]) -> None:
    job_id = str(job["id"])
    existing = archive_tasks.get(job_id)
    if existing and not existing.done():
        return
    target_date = date.fromisoformat(str(job["target_date"]))
    archive_tasks[job_id] = asyncio.create_task(_run_archive_job(job_id, target_date))


async def _run_maintenance_job(job_id: str) -> None:
    job = database.get_maintenance_job(job_id)
    if not job:
        return
    kind = str(job["kind"])
    payload = dict(job.get("payload") or {})
    try:
        database.update_maintenance_job(job_id, status="running", phase="starting", current=0, total=4)
        if kind == "import_zip":
            final_total = 4
            upload_path = Path(str(payload["upload_path"]))
            filename = str(payload.get("filename") or upload_path.name)
            zip_bytes = await asyncio.to_thread(upload_path.read_bytes)
            database.update_maintenance_job(job_id, phase="extracting", current=1)
            import_root = await asyncio.to_thread(_extract_docx_zip, zip_bytes, filename)
            database.update_maintenance_job(job_id, phase="importing_docx", current=2)
            result = await asyncio.to_thread(
                historical_importer.import_roots,
                _historical_import_roots(import_root),
                replace_active=True,
                source_name=filename,
                source_kind="zip",
                content_hash=hashlib.sha256(zip_bytes).hexdigest(),
            )
            database.update_maintenance_job(job_id, phase="recomputing_signals", current=3)
            archive = await asyncio.to_thread(database.archive_played_matches)
            recompute = await asyncio.to_thread(database.recompute_historical_signals)
            final = {
                **result,
                **{f"recompute_{key}": value for key, value in recompute.items()},
                **archive,
                "import_root": str(import_root),
            }
        elif kind == "recompute_signals":
            final_total = 2
            database.update_maintenance_job(job_id, phase="archiving_played_matches", current=1, total=2)
            archive = (
                await asyncio.to_thread(database.archive_played_matches)
                if bool(payload.get("archive_played", True))
                else {"archived": 0}
            )
            database.update_maintenance_job(job_id, phase="recomputing_signals", current=1, total=2)
            recompute = await asyncio.to_thread(database.recompute_historical_signals)
            final = {**recompute, **archive}
        elif kind == "import_folder":
            final_total = 3
            database.update_maintenance_job(job_id, phase="importing_docx", current=1, total=3)
            result = await asyncio.to_thread(
                historical_importer.import_roots,
                [settings.historical_database_root],
                replace_active=True,
                source_name=str(settings.historical_database_root.name),
                source_kind="folder",
            )
            database.update_maintenance_job(job_id, phase="recomputing_signals", current=2, total=3)
            archive = await asyncio.to_thread(database.archive_played_matches)
            recompute = await asyncio.to_thread(database.recompute_historical_signals)
            final = {**result, **archive, **{f"recompute_{key}": value for key, value in recompute.items()}}
        else:
            raise ValueError(f"Unknown maintenance job type: {kind}")
        database.update_maintenance_job(
            job_id,
            status="completed",
            phase="complete",
            current=final_total,
            total=final_total,
            result=final,
        )
    except asyncio.CancelledError:
        database.update_maintenance_job(job_id, status="pending", phase="queued", error=None)
        raise
    except Exception as exc:
        database.update_maintenance_job(job_id, status="failed", phase="failed", error=str(exc))
        database.log("error", "maintenance", "maintenance_job_failed", details={"job_id": job_id, "error": str(exc)})
    finally:
        maintenance_tasks.pop(job_id, None)


def _schedule_maintenance_job(job: dict[str, object]) -> None:
    job_id = str(job["id"])
    existing = maintenance_tasks.get(job_id)
    if existing and not existing.done():
        return
    maintenance_tasks[job_id] = asyncio.create_task(_run_maintenance_job(job_id))


async def _api_scheduler_loop() -> None:
    global scheduler_cycle_started_at, scheduler_last_error, scheduler_next_run_at
    database.log("info", "scheduler", "api_scheduler_started")
    while True:
        try:
            scheduler_next_run_at = None
            scheduler_cycle_started_at = utc_now()
            result = await service.run_once(trigger="api_scheduler", force_discovery=False)
            _refresh_historical_after_capture(result, "api_scheduler")
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
    global scheduler_task, scheduler_started_at, status_refresh_task, read_database, read_database_source_id
    _refresh_status_snapshot()
    status_refresh_task = asyncio.create_task(_status_refresh_loop())
    if settings.historical_auto_import and int(database.historical_import_status().get("records", 0) or 0) == 0:
        _schedule_maintenance_job(database.create_maintenance_job("import_folder", {}))
    if settings.enable_api_scheduler:
        scheduler_started_at = utc_now()
        scheduler_task = asyncio.create_task(_api_scheduler_loop())
    for job in database.resumable_archive_jobs():
        _schedule_archive_job(job)
    for job in database.resumable_maintenance_jobs():
        _schedule_maintenance_job(job)
    try:
        yield
    finally:
        if scheduler_task:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
            database.log("info", "scheduler", "api_scheduler_stopped")
        pending_archive_tasks = list(archive_tasks.values())
        for task in pending_archive_tasks:
            task.cancel()
        for task in pending_archive_tasks:
            with suppress(asyncio.CancelledError):
                await task
        pending_maintenance_tasks = list(maintenance_tasks.values())
        for task in pending_maintenance_tasks:
            task.cancel()
        for task in pending_maintenance_tasks:
            with suppress(asyncio.CancelledError):
                await task
        if status_refresh_task:
            status_refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await status_refresh_task
        await service.close()
        if read_database is not None:
            with suppress(Exception):
                read_database.connection.close()
            read_database = None
            read_database_source_id = None


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


class SignalRecomputeRequest(BaseModel):
    archive_played: bool = True


class ArchiveDateRequest(BaseModel):
    date: date


SAFE_IMPORT_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _refresh_historical_signals(reason: str) -> dict[str, object]:
    try:
        return historical_auto_refresh.refresh(reason)
    except Exception as exc:
        database.log("error", "historical", "auto_refresh_failed", details={"reason": reason, "error": str(exc)})
        return {
            "files_seen": 0,
            "files_imported": 0,
            "records_imported": 0,
            "warnings": 0,
            "recompute_matches_evaluated": 0,
            "recompute_signals": 0,
            "archived": 0,
        }


def _refresh_historical_after_capture(result: dict[str, object], reason: str) -> dict[str, object]:
    if not settings.historical_auto_recompute:
        return result
    if int(result.get("captured", 0) or 0) <= 0 and int(result.get("results_captured", 0) or 0) <= 0:
        return result
    changed_match_ids_getter = getattr(service, "last_changed_match_ids", None)
    changed_match_ids = changed_match_ids_getter() if callable(changed_match_ids_getter) else None
    if isinstance(changed_match_ids, list):
        archive = database.archive_played_matches([str(match_id) for match_id in changed_match_ids])
        recompute = database.recompute_historical_signals(
            [str(match_id) for match_id in changed_match_ids]
        )
        historical_result: dict[str, object] = {
            "archived": archive["archived"],
            "recompute_matches_evaluated": recompute["matches_evaluated"],
            "recompute_signals": recompute["signals"],
        }
        return {**result, **{f"historical_{key}": value for key, value in historical_result.items()}}
    historical_result = _refresh_historical_signals(reason)
    return {**result, **{f"historical_{key}": value for key, value in historical_result.items()}}


@app.get("/api/status")
def status() -> dict[str, object]:
    if status_snapshot is None or status_snapshot_database_id != id(database):
        _refresh_status_snapshot()
    result = dict(status_snapshot or {})
    last_run = result.get("last_run")
    progress = service.progress_status()
    archive_progress = service.archive_progress_status()
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
    result["running"] = (
        api_scheduler_running
        or bool(progress.get("running"))
        or bool(archive_progress.get("running"))
    )
    result["scheduler"] = {
        "enabled": settings.enable_api_scheduler,
        "running": api_scheduler_running,
        "started_at": scheduler_started_at.isoformat() if scheduler_started_at else None,
        "cycle_started_at": scheduler_cycle_started_at.isoformat() if scheduler_cycle_started_at else None,
        "next_run_at": scheduler_next_run_at.isoformat() if scheduler_next_run_at else None,
        "last_error": scheduler_last_error,
    }
    result["capture_progress"] = progress
    result["archive_progress"] = archive_progress
    result["ingest"] = service.ingest_status()
    result["maintenance_busy"] = any(not task.done() for task in maintenance_tasks.values())
    result["status_snapshot"] = {
        "updated_at": status_snapshot_updated_at.isoformat() if status_snapshot_updated_at else None,
        "last_error": status_snapshot_error,
    }
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
    return _reader().list_matches()


@app.get("/api/matches-page")
def matches_page(
    q: str = "",
    filter: str = "all",
    sort: str = "capture_desc",
    date: str = "",
    offset: int = 0,
    limit: int = 120,
) -> dict[str, object]:
    return _reader().list_matches_page(query=q, match_filter=filter, sort_mode=sort, match_date=date, offset=offset, limit=limit)


@app.get("/api/match-days")
def match_days() -> list[dict[str, object]]:
    return _reader().list_match_days()


@app.get("/api/matches/{match_id}")
def match_detail(
    match_id: str,
    snapshots_limit: int = 100,
    attempts_limit: int = 100,
) -> dict[str, object]:
    detail = _reader().match_detail(
        match_id,
        snapshots_limit=snapshots_limit,
        attempts_limit=attempts_limit,
    )
    if not detail:
        raise HTTPException(status_code=404, detail="Match not found")
    return detail


@app.get("/api/snapshots")
def snapshots() -> list[dict[str, object]]:
    return _reader().list_snapshots()


@app.get("/api/attempts")
def attempts() -> list[dict[str, object]]:
    return _reader().list_attempts()


@app.get("/api/logs")
def logs() -> list[dict[str, object]]:
    return _reader().list_logs()


@app.get("/api/bookmakers")
def bookmakers() -> list[dict[str, object]]:
    return _reader().bookmaker_coverage()


@app.get("/api/historical/import-status")
def historical_import_status() -> dict[str, object]:
    result = _reader().historical_import_status()
    result["root"] = str(settings.historical_database_root)
    result["root_exists"] = settings.historical_database_root.exists()
    result["auto_import"] = settings.historical_auto_import
    result["auto_recompute"] = settings.historical_auto_recompute
    return result


@app.post("/api/historical/import")
async def historical_import() -> dict[str, object]:
    job = database.create_maintenance_job("import_folder", {})
    _schedule_maintenance_job(job)
    return job


@app.post("/api/historical/import-zip")
async def historical_import_zip(request: Request) -> dict[str, object]:
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="ZIP payload is empty")
    filename = unquote(request.headers.get("x-filename", "historical-docx.zip"))
    upload_root = settings.historical_database_root / "_job_uploads"
    await asyncio.to_thread(upload_root.mkdir, parents=True, exist_ok=True)
    upload_path = upload_root / f"{utc_now().strftime('%Y%m%d%H%M%S%f')}.zip"
    await asyncio.to_thread(upload_path.write_bytes, payload)
    job = database.create_maintenance_job(
        "import_zip",
        {"upload_path": str(upload_path), "filename": filename},
    )
    _schedule_maintenance_job(job)
    return job


@app.get("/api/maintenance/jobs/{job_id}")
def maintenance_job(job_id: str) -> dict[str, object]:
    job = _reader().get_maintenance_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Maintenance job not found")
    return job


def _extract_docx_zip(payload: bytes, filename: str) -> Path:
    zip_buffer = io.BytesIO(payload)
    if not zipfile.is_zipfile(zip_buffer):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP archive")
    safe_name = SAFE_IMPORT_NAME_RE.sub("-", Path(filename).stem or "historical-docx").strip(".-") or "historical-docx"
    import_root = settings.historical_database_root / "_zip_imports" / f"{safe_name}-{utc_now().strftime('%Y%m%d%H%M%S')}"
    import_root.mkdir(parents=True, exist_ok=True)
    root_resolved = import_root.resolve()
    extracted = 0
    with zipfile.ZipFile(zip_buffer) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".docx"):
                continue
            relative_path = Path(info.filename)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise HTTPException(status_code=400, detail="ZIP archive contains an unsafe path")
            target = import_root / relative_path
            if not target.resolve().is_relative_to(root_resolved):
                raise HTTPException(status_code=400, detail="ZIP archive contains an unsafe path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as destination:
                destination.write(source.read())
            extracted += 1
    if extracted == 0:
        raise HTTPException(status_code=400, detail="ZIP archive does not contain DOCX files")
    return import_root


def _historical_import_roots(import_root: Path) -> list[Path]:
    candidates = [import_root, *[item for item in import_root.rglob("*") if item.is_dir()]]
    roots: list[Path] = []
    for candidate in candidates:
        if not _looks_like_historical_root(candidate):
            continue
        if any(candidate != root and root in candidate.parents for root in roots):
            continue
        roots.append(candidate)
    return roots or [import_root]


def _looks_like_historical_root(path: Path) -> bool:
    name = path.name.lower()
    if "odds" in name or "gebruikbare" in name or "usable" in name:
        return True
    return any(
        child.is_dir() and ("odds" in child.name.lower() or "gebruikbare" in child.name.lower() or "usable" in child.name.lower())
        for child in path.iterdir()
    )


@app.get("/api/signals")
def signals(
    dataset: str = "all",
    bookmaker: str = "all",
    signal_type: str = "all",
    min_sample: int = 1,
    from_date: str = "",
    date: str = "",
    actionable_only: bool = False,
    sort: str = "quality",
) -> list[dict[str, object]]:
    actionable_after = None
    if actionable_only:
        actionable_after = datetime.now() - timedelta(minutes=settings.recently_started_window_minutes)
    return _reader().list_signals(
        dataset=dataset,
        bookmaker=bookmaker,
        signal_type=signal_type,
        min_sample=min_sample,
        from_date=from_date,
        match_date=date,
        actionable_after=actionable_after,
        sort_mode=sort,
    )


@app.get("/api/signal-days")
def signal_days() -> list[dict[str, object]]:
    return _reader().list_signal_days()


@app.post("/api/signals/recompute")
async def recompute_signals(request: SignalRecomputeRequest) -> dict[str, object]:
    job = database.create_maintenance_job("recompute_signals", {"archive_played": request.archive_played})
    _schedule_maintenance_job(job)
    return job


@app.post("/api/maintenance/repair-final-snapshots")
def repair_final_snapshots() -> dict[str, int]:
    repair = database.repair_final_snapshots(settings.required_bookmakers)
    archive = database.archive_played_matches()
    recompute = database.recompute_historical_signals()
    return {**repair, **archive, **{f"recompute_{key}": value for key, value in recompute.items()}}


@app.post("/api/archive/date")
async def archive_date(request: ArchiveDateRequest) -> dict[str, object]:
    job = database.create_archive_job(request.date)
    _schedule_archive_job(job)
    return job


@app.get("/api/archive/jobs/{job_id}")
def archive_job(job_id: str) -> dict[str, object]:
    job = _reader().get_archive_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Archive job not found")
    return job


@app.get("/api/archive/jobs/{job_id}/items")
def archive_job_items(job_id: str, incomplete_only: bool = True) -> list[dict[str, object]]:
    if not _reader().get_archive_job(job_id):
        raise HTTPException(status_code=404, detail="Archive job not found")
    return _reader().list_archive_job_items(job_id, incomplete_only)


@app.post("/api/archive/jobs/{job_id}/retry")
async def retry_archive_job(job_id: str) -> dict[str, object]:
    job = database.retry_archive_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Archive job not found")
    _schedule_archive_job(job)
    return job


@app.get("/api/signals/{match_id}")
def match_signals(match_id: str) -> list[dict[str, object]]:
    detail = _reader().match_detail(match_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Match not found")
    return _reader().list_signals(match_id=match_id)


@app.get("/api/exports")
def exports() -> list[dict[str, object]]:
    if not settings.export_dir.exists():
        return []
    files = []
    paths = [
        path
        for pattern in ("final_odds_*.*", "played_match_archive_*.*")
        for path in settings.export_dir.glob(pattern)
    ]
    for path in sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True):
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
async def capture_run_once() -> dict[str, object]:
    result = await service.run_once(trigger="manual_force")
    return _refresh_historical_after_capture(result, "capture_run_once")


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


@app.post("/api/exports/played-archive")
def export_played_archive_endpoint(request: ExportRequest) -> dict[str, str]:
    fmt = request.format.lower()
    date_slug = request.date or utc_now().strftime("%Y-%m-%d")
    database.archive_played_matches()
    try:
        path = export_played_match_archive(
            database.list_played_match_archive(),
            settings.export_dir,
            date_slug,
            fmt,
            settings.betexplorer_timezone_offset,
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
