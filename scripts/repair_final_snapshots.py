from __future__ import annotations

from betexplorer_scraper.config import get_settings
from betexplorer_scraper.database import Database


def main() -> None:
    settings = get_settings()
    database = Database(settings.database_path, timezone_offset=settings.betexplorer_timezone_offset)
    result = database.repair_final_snapshots(settings.required_bookmakers)
    print(
        "Repaired final snapshots: "
        f"{result['groups_repaired']} changed / {result['groups_checked']} match-market groups checked"
    )


if __name__ == "__main__":
    main()
