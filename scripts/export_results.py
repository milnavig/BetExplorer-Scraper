from __future__ import annotations

import argparse

from betexplorer_scraper.clock import utc_now
from betexplorer_scraper.config import get_settings
from betexplorer_scraper.database import Database
from betexplorer_scraper.exporter import export_final_odds


def main() -> None:
    parser = argparse.ArgumentParser(description="Export BetExplorer final odds")
    parser.add_argument("--date", default=utc_now().strftime("%Y-%m-%d"))
    parser.add_argument("--format", choices=["csv", "xlsx"], default="csv")
    parser.add_argument("--layout", choices=["wide", "long"], default="wide")
    args = parser.parse_args()

    settings = get_settings()
    database = Database(settings.database_path)
    path = export_final_odds(
        database.final_snapshot_items(),
        settings.export_dir,
        args.date,
        args.format,
        settings.betexplorer_timezone_offset,
        args.layout,
    )
    print(path)


if __name__ == "__main__":
    main()
