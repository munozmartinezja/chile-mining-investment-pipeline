"""Filesystem configuration for the CMIP pipeline."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "cochilco" / "anexo_c"
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DATABASE_PATH = PROJECT_ROOT / "data" / "cmip.duckdb"
SQL_DIR = PROJECT_ROOT / "sql"

