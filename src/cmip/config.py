"""Filesystem configuration for the CMIP pipeline."""

from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "cochilco" / "anexo_c"
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DATABASE_PATH = PROJECT_ROOT / "data" / "cmip.duckdb"
SQL_DIR = PROJECT_ROOT / "sql"
AUTHOR_LINE = "J. A. Muñoz Martínez · github.com/munozmartinezja"
SEA_DOWNLOAD_DATE = date(2026, 9, 30)
SEA_DATA_CURRENCY_DATE = date(2026, 8, 25)
SEIA_FICHA_URL = (
    "https://seia.sea.gob.cl/expediente/ficha/fichaPrincipal.php?"
    "id_expediente={exp_id}&modo=ficha"
)
