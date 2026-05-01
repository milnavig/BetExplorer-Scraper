from __future__ import annotations

import argparse
import asyncio

from betexplorer_scraper.capture import CaptureService
from betexplorer_scraper.config import get_settings
from betexplorer_scraper.database import Database


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run BetExplorer live odds capture")
    parser.add_argument("--once", action="store_true", help="Run one capture cycle and exit")
    args = parser.parse_args()
    settings = get_settings()
    service = CaptureService(settings, Database(settings.database_path))

    if args.once:
        print(await service.run_once())
        return

    while True:
        print(await service.run_once(trigger="cli_scheduler", force_discovery=False))
        await asyncio.sleep(service.settings.scheduler_tick_seconds)


if __name__ == "__main__":
    asyncio.run(main())
