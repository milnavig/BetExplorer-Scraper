from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from docx import Document

from .historical import normalize_odds, normalize_score


OddsTriplet = tuple[float, float, float]
DATE_ROW_RE = re.compile(r"^\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}\.?$")


@dataclass(frozen=True, slots=True)
class HistoricalOutcome:
    full_time_score: str
    half_time_score: str | None
    source_row_index: int


@dataclass(slots=True)
class HistoricalBlock:
    dataset: str
    logical_source_file: str
    table_index: int
    block_index: int
    bwin_odds: OddsTriplet
    unibet_odds: OddsTriplet
    outcomes: list[HistoricalOutcome] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class HistoricalParseWarning:
    logical_source_file: str
    table_index: int
    row_index: int
    code: str

    def message(self) -> str:
        return (
            f"{self.logical_source_file}:{self.table_index + 1}:"
            f"{self.row_index + 1}: {self.code}"
        )


@dataclass(slots=True)
class _OddsRow:
    row_index: int
    odds: OddsTriplet
    outcome: HistoricalOutcome | None


def parse_historical_docx(
    path: Path,
    dataset: str,
    logical_source_file: str,
) -> tuple[list[HistoricalBlock], list[HistoricalParseWarning]]:
    document = Document(str(path))
    blocks: list[HistoricalBlock] = []
    warnings: list[HistoricalParseWarning] = []

    for table_index, table in enumerate(document.tables):
        odds_rows: list[_OddsRow] = []
        score_only_rows: list[HistoricalOutcome] = []

        for row_index, row in enumerate(table.rows):
            cells = _normalized_row_cells(row.cells)
            if not any(cells):
                continue
            odds = _row_odds(cells)
            outcome = _row_outcome(cells, row_index)
            if odds is not None:
                odds_rows.append(_OddsRow(row_index, odds, outcome))
            elif outcome is not None:
                score_only_rows.append(outcome)
            elif _is_metadata_row(cells):
                continue
            else:
                warnings.append(
                    HistoricalParseWarning(
                        logical_source_file,
                        table_index,
                        row_index,
                        "unparsed row",
                    )
                )

        if len(odds_rows) % 2:
            warnings.append(
                HistoricalParseWarning(
                    logical_source_file,
                    table_index,
                    odds_rows[-1].row_index,
                    "odd number of odds rows",
                )
            )
            odds_rows = odds_rows[:-1]

        table_blocks: list[HistoricalBlock] = []
        for pair_index in range(0, len(odds_rows), 2):
            bwin_row = odds_rows[pair_index]
            unibet_row = odds_rows[pair_index + 1]
            outcomes = [
                outcome
                for outcome in (bwin_row.outcome, unibet_row.outcome)
                if outcome is not None
            ]
            block = HistoricalBlock(
                dataset=dataset,
                logical_source_file=logical_source_file,
                table_index=table_index,
                block_index=pair_index // 2,
                bwin_odds=bwin_row.odds,
                unibet_odds=unibet_row.odds,
                outcomes=outcomes,
            )
            table_blocks.append(block)
            blocks.append(block)

        for outcome in score_only_rows:
            preceding = [
                (odds_rows[index + 1].row_index, table_blocks[index // 2])
                for index in range(0, len(odds_rows), 2)
                if odds_rows[index + 1].row_index < outcome.source_row_index
            ]
            if not preceding:
                warnings.append(
                    HistoricalParseWarning(
                        logical_source_file,
                        table_index,
                        outcome.source_row_index,
                        "score row before a complete odds pair",
                    )
                )
                continue
            preceding[-1][1].outcomes.append(outcome)

        for block in table_blocks:
            if not block.outcomes:
                row_index = odds_rows[block.block_index * 2 + 1].row_index
                warnings.append(
                    HistoricalParseWarning(
                        logical_source_file,
                        table_index,
                        row_index,
                        "complete odds pair has no outcome",
                    )
                )

    return blocks, warnings


def block_records(block: HistoricalBlock) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for outcome in block.outcomes:
        records.append(
            {
                "dataset": block.dataset,
                "source_file": block.logical_source_file,
                "source_home_bucket": None,
                "source_away_file": None,
                "query_home_odds": block.bwin_odds[0],
                "query_draw_odds": block.bwin_odds[1],
                "query_away_odds": block.bwin_odds[2],
                "historical_home_odds": block.unibet_odds[0],
                "historical_draw_odds": block.unibet_odds[1],
                "historical_away_odds": block.unibet_odds[2],
                "full_time_score": outcome.full_time_score,
                "half_time_score": outcome.half_time_score,
                "parse_status": "complete_block",
                "parse_warning": None,
            }
        )
    return records


def _row_odds(cells: list[str]) -> OddsTriplet | None:
    if len(cells) < 3:
        return None
    values = [normalize_odds(cells[index]) for index in range(3)]
    if any(value is None for value in values):
        return None
    return values[0], values[1], values[2]  # type: ignore[return-value]


def _row_outcome(cells: list[str], row_index: int) -> HistoricalOutcome | None:
    full_time_score = normalize_score(cells[3] if len(cells) > 3 else "")
    half_time_value = cells[4] if len(cells) > 4 else ""
    if full_time_score is None and len(cells) >= 2 and not any(cells[2:]):
        full_time_score = normalize_score(cells[0])
        half_time_value = cells[1]
    if full_time_score is None:
        return None
    return HistoricalOutcome(
        full_time_score=full_time_score,
        half_time_score=normalize_score(half_time_value),
        source_row_index=row_index,
    )


def _cell_text(value: str) -> str:
    return " ".join(value.replace("\n", " ").strip().split())


def _normalized_row_cells(row_cells: object) -> list[str]:
    cells = [_cell_text(cell.text) for cell in row_cells]  # type: ignore[attr-defined]
    leading_odds = normalize_odds(cells[0]) if cells else None
    if len(cells) >= 6 and leading_odds is not None and leading_odds == normalize_odds(cells[1]):
        # One audited DOCX table contains a duplicated leading Word cell. The
        # logical five columns still follow it in the normal odds/FT/HT order.
        return cells[1:6]
    return cells[:5]


def _is_metadata_row(cells: list[str]) -> bool:
    values = [value for value in cells if value]
    if len(values) != 1:
        return False
    value = values[0]
    return bool(DATE_ROW_RE.match(value)) or (value.startswith("(") and value.endswith(")"))
