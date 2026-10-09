from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pypdf
import pytest
import reportlab  # noqa: F401

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
    portfolio = pd.read_parquet(PORTFOLIO_PATH)
    forbidden = {
        str(value).strip()
        for column in ("empresa", "mina", "nombre_del_proyecto")
        for value in portfolio[column].dropna()
        if str(value).strip()
    }
    # The method bullet names Codelco as the source of the aggregate rows;
    # individual projects remain forbidden.
    forbidden.discard("Codelco")
    for path in PDF_PATHS:
        reader = pypdf.PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        assert len(reader.pages) == 1
        assert not [name for name in forbidden if name.casefold() in text.casefold()]


@requires_brief_data
def test_brief_headline_values_equal_verified_portfolio_claims() -> None:
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


@requires_brief_data
def test_every_pdf_number_is_verified_or_explicitly_whitelisted() -> None:
    metrics = compute_brief_metrics()
    whitelist = {
        "2011",
        "2025",
        "2034",
        "24",
        "36",
        "100",
        "2",
        "30,44",
        "30.44",
        "30",
        "09",
        "2026",
    }
    for lang, path in zip(("es", "en"), PDF_PATHS, strict=True):
        allowed = set(whitelist)
        for value in metrics["valor"].dropna():
            for decimals in (0, 1, 2):
                allowed.add(format_number(float(value), decimals, lang))
            if float(value).is_integer():
                allowed.add(str(int(value)))
        allowed.add("08")
        text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(path).pages)
        tokens = re.findall(r"\d+(?:[.,]\d+)*", text)
        unsupported = sorted(set(tokens) - allowed)
        assert not unsupported, {"path": str(path), "unsupported": unsupported}


def test_pdf_copy_contains_no_forbidden_adversarial_phrases() -> None:
    forbidden = (
        "como mínimo",
        "at least",
        "1 de cada",
        "1 in",
        "validado manualmente",
        "manually validated",
        "ingenua",
        "naive",
        "hoy",
        "today",
        "sin permiso",
        "without a permit",
    )
    for path in PDF_PATHS:
        text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(path).pages)
        lowered = text.casefold()
        assert not [phrase for phrase in forbidden if phrase.casefold() in lowered]


def test_claims_map_covers_every_extracted_pdf_line() -> None:
    claims_map = pd.read_csv(ROOT / "docs/brief/claims_map.csv", keep_default_na=False)
    register = compute_brief_metrics().set_index("claim_id")
    assert claims_map.columns.tolist() == [
        "lang",
        "bloque",
        "texto_renderizado",
        "claim_ids",
        "evidencia",
    ]
    assert (claims_map["claim_ids"].ne("") | claims_map["evidencia"].ne("")).all()
    for row in claims_map.itertuples(index=False):
        for claim_id in filter(None, row.claim_ids.split(";")):
            assert register.loc[claim_id, "estado"] == "verificada"
    for lang, path in zip(("es", "en"), PDF_PATHS, strict=True):
        mapped = set(
            claims_map.loc[claims_map["lang"].eq(lang), "texto_renderizado"]
        )
        text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(path).pages)
        extracted = {
            line.strip().lstrip("\x7f•").strip()
            for line in text.splitlines()
            if line.strip().lstrip("\x7f•").strip()
        }
        assert extracted <= mapped
