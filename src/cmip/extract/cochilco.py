"""Extract the logical tables in Cochilco Annex C."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from cmip.config import INTERIM_DIR, RAW_DIR

TABLE_TITLE_RE = re.compile(r"\bTabla\s+(\d+)\s*:", re.IGNORECASE)
FOOTNOTE_PREFIXES = ("(1)", "Fuente:")


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _nonempty_cells(row: pd.Series) -> list[str]:
    return [text for value in row.tolist() if (text := _text(value))]


def table_number(row: pd.Series) -> int | None:
    """Return the Annex table number declared anywhere in a row."""
    for cell in _nonempty_cells(row):
        if match := TABLE_TITLE_RE.search(cell):
            return int(match.group(1))
    return None


def detect_header_row(sheet: pd.DataFrame, title_row: int, end_row: int | None = None) -> int:
    """Find the first multi-cell row after a table title."""
    stop = len(sheet) if end_row is None else end_row
    for index in range(title_row + 1, stop):
        cells = _nonempty_cells(sheet.iloc[index])
        if len(cells) >= 2 and not cells[0].startswith(FOOTNOTE_PREFIXES):
            return index
    raise ValueError(f"No header row found after source row {title_row + 1}")


def extract_table(
    sheet: pd.DataFrame,
    title_row: int,
    end_row: int | None = None,
) -> pd.DataFrame:
    """Extract one table, dropping empty columns and stopping at its footnotes."""
    stop = len(sheet) if end_row is None else end_row
    header_row = detect_header_row(sheet, title_row, stop)
    header = sheet.iloc[header_row]

    data_rows: list[pd.Series] = []
    for index in range(header_row + 1, stop):
        row = sheet.iloc[index]
        cells = _nonempty_cells(row)
        if not cells:
            continue
        if cells[0].startswith(FOOTNOTE_PREFIXES) or table_number(row) is not None:
            break
        data_rows.append(row)

    selected = [
        index
        for index, value in header.items()
        if _text(value) or any(_text(row[index]) for row in data_rows)
    ]
    columns = [_text(header[index]) or f"unnamed_{index + 1}" for index in selected]
    records = [[row[column] for column in selected] for row in data_rows]

    frame = pd.DataFrame(records, columns=columns)
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame.dropna(axis="columns", how="all").reset_index(drop=True)


def _workbook_sheets(path: Path) -> Iterator[tuple[str, pd.DataFrame]]:
    sheets = pd.read_excel(
        path,
        sheet_name=None,
        header=None,
        dtype=object,
        engine="openpyxl",
        keep_default_na=False,
    )
    for name, sheet in sheets.items():
        if "índice" not in name.casefold() and "indice" not in name.casefold():
            yield name, sheet


def _csv_sheets(raw_dir: Path) -> Iterator[tuple[str, pd.DataFrame]]:
    for path in sorted(raw_dir.glob("*.csv")):
        if "índice" in path.name.casefold() or "indice" in path.name.casefold():
            continue
        yield path.stem, pd.read_csv(
            path,
            sep=";",
            header=None,
            dtype=object,
            encoding="utf-8-sig",
            keep_default_na=False,
        )


def source_sheets(raw_dir: Path = RAW_DIR) -> Iterator[tuple[str, pd.DataFrame]]:
    """Yield workbook sheets, falling back to the retained CSV exports."""
    workbooks = sorted(raw_dir.glob("*.xlsx")) + sorted(raw_dir.glob("*.xls"))
    if workbooks:
        yield from _workbook_sheets(workbooks[0])
        return
    yield from _csv_sheets(raw_dir)


def extract_annex_tables(raw_dir: Path = RAW_DIR) -> dict[int, pd.DataFrame]:
    """Detect and extract all logical Annex C tables from the selected source."""
    tables: dict[int, pd.DataFrame] = {}
    for _name, sheet in source_sheets(raw_dir):
        titles = [
            (index, number)
            for index in range(len(sheet))
            if (number := table_number(sheet.iloc[index])) is not None
        ]
        for position, (title_row, number) in enumerate(titles):
            end_row = titles[position + 1][0] if position + 1 < len(titles) else len(sheet)
            tables[number] = extract_table(sheet, title_row, end_row)

    expected = set(range(1, 14))
    missing = expected.difference(tables)
    if missing:
        raise ValueError(f"Annex C tables not detected: {sorted(missing)}")
    return dict(sorted(tables.items()))


def write_interim_tables(
    tables: dict[int, pd.DataFrame], interim_dir: Path = INTERIM_DIR
) -> dict[int, Path]:
    """Persist raw extracted tables as Parquet, one file per logical table."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[int, Path] = {}
    for number, frame in tables.items():
        path = interim_dir / f"cochilco_tabla_{number:02d}.parquet"
        parquet_frame = frame.copy()
        for column in parquet_frame.select_dtypes(include="object").columns:
            parquet_frame[column] = parquet_frame[column].map(_text)
        parquet_frame.to_parquet(path, index=False)
        outputs[number] = path
    return outputs
