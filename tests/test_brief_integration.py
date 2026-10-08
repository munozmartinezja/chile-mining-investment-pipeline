from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cmip.brief import compute_brief_metrics, format_number

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO_PATH = ROOT / "data/processed/cochilco_seia.parquet"
PDF_PATHS = [
    ROOT / "docs/brief/brief_c1_es.pdf",
    ROOT / "docs/brief/brief_c1_en.pdf",
]
REQUIRED_DATA = [
    PORTFOLIO_PATH,
    ROOT / "data/processed/survival_km_summary.parquet",
    ROOT / "data/processed/survival_competing_risks_summary.parquet",
    ROOT / "data/interim/sea_mining.parquet",
]
requires_brief_data = pytest.mark.skipif(
    not all(path.exists() for path in REQUIRED_DATA),
    reason="requires local portfolio and SEA analysis parquets",
)


@requires_brief_data
def test_versioned_briefs_are_one_page_and_contain_no_portfolio_names() -> None:
    pypdf = pytest.importorskip("pypdf")
    portfolio = pd.read_parquet(PORTFOLIO_PATH)
    forbidden = {
        str(value).strip()
        for column in ("empresa", "mina", "nombre_del_proyecto")
        for value in portfolio[column].dropna()
        if str(value).strip()
    }
    for path in PDF_PATHS:
        reader = pypdf.PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        assert len(reader.pages) == 1
        assert not [name for name in forbidden if name.casefold() in text.casefold()]


@requires_brief_data
def test_brief_headline_values_equal_verified_portfolio_claims() -> None:
    pypdf = pytest.importorskip("pypdf")
    metrics = compute_brief_metrics().set_index("claim_id")
    for lang, path in zip(("es", "en"), PDF_PATHS, strict=True):
        text = "\n".join(
            page.extract_text() or "" for page in pypdf.PdfReader(path).pages
        )
        amount = format_number(
            metrics.loc["estado_sin_expediente_en_estudio_inversion", "valor"],
            0,
            lang,
        )
        projects = format_number(
            metrics.loc["estado_sin_expediente_en_estudio_n", "valor"], 0, lang
        )
        assert amount in text
        assert projects in text
