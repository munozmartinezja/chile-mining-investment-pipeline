from __future__ import annotations

from pathlib import Path

import pandas as pd
import pypdf
import pytest
import reportlab

from cmip.brief import _brief_copy, compute_brief_metrics, format_number, render_brief


def _synthetic_register() -> pd.DataFrame:
    values = {
        "cartera_inversion_total": (100_000.0, "MMUS$"),
        "cartera_proyectos_n": (59, "proyectos"),
        "sea_poblacion_admitida_n": (1_645, "expedientes"),
        "estado_sin_expediente_en_estudio_inversion": (21_000.0, "MMUS$"),
        "estado_sin_expediente_en_estudio_n": (8, "proyectos"),
        "estado_sin_expediente_en_estudio_pct": (21.0, "%"),
        "estado_aprobado_inversion": (32_000.0, "MMUS$"),
        "estado_aprobado_pct": (32.0, "%"),
        "estado_en_evaluacion_inversion": (24_000.0, "MMUS$"),
        "estado_en_evaluacion_n": (15, "proyectos"),
        "estado_desistido_rechazado_o_no_calificado_inversion": (0.0, "MMUS$"),
        "estado_agregado_no_asignable_inversion": (22_000.0, "MMUS$"),
        "estado_agregado_no_asignable_n": (4, "proyectos"),
        "estado_pertinencia_inversion": (50.0, "MMUS$"),
        "estado_no_determinado_inversion": (800.0, "MMUS$"),
        "km_DIA_mediana": (7.7, "meses"),
        "km_DIA_ic95_inf": (7.2, "meses"),
        "km_DIA_ic95_sup": (8.1, "meses"),
        "km_EIA_mediana": (28.8, "meses"),
        "km_EIA_ic95_inf": (23.7, "meses"),
        "km_EIA_ic95_sup": (32.9, "meses"),
        "km_DIA_aprobado_24m": (96.2, "%"),
        "km_EIA_aprobado_24m": (41.2, "%"),
        "aj_DIA_aprobado_24m": (66.5, "%"),
        "aj_EIA_aprobado_24m": (31.1, "%"),
        "aj_EIA_aprobado_36m": (51.7, "%"),
        "aj_EIA_mes_50pct": (33.4, "meses"),
        "eia_100m_aj_aprobado_24m_estimacion": (38.4, "%"),
        "eia_100m_aj_aprobado_24m_ic95_inf": (26.4, "%"),
        "eia_100m_aj_aprobado_24m_ic95_sup": (49.8, "%"),
        "eia_100m_n": (81, "expedientes"),
        "poblacion_periodo_inicio": (2011, "año"),
        "poblacion_periodo_fin": (2026, "año"),
        "cruces_revision_manual_n": (38, "proyectos"),
        "cruces_regla_auto_n": (21, "proyectos"),
        "headline_piso_pct": (8.6, "%"),
        "headline_techo_pct": (44.9, "%"),
        "sea_fecha_datos_dia": (25, "día"),
        "sea_fecha_datos_mes": (8, "mes"),
        "sea_fecha_datos_anio": (2026, "año"),
        "headline_amount_round_mmusd": (21_000, "MMUS$"),
        "confidence_level_pct": (95, "%"),
        "aj_threshold_pct": (50, "%"),
    }
    return pd.DataFrame(
        [
            {
                "claim_id": claim_id,
                "texto_es": claim_id,
                "valor": value,
                "unidad": unit,
                "fuente": "fixture.parquet",
                "calculo": "fixture independiente",
                "valor_recalculado": value,
                "diferencia": 0.0,
                "estado": "verificada",
                "nota_semantica": "Fixture sintético.",
            }
            for claim_id, (value, unit) in values.items()
        ]
    )


def test_compute_brief_metrics_rejects_any_unverified_used_claim() -> None:
    register = _synthetic_register()
    register.loc[
        register["claim_id"].eq("aj_EIA_aprobado_24m"), "estado"
    ] = "pendiente_J"

    with pytest.raises(ValueError, match="aj_EIA_aprobado_24m.*pendiente_J"):
        compute_brief_metrics(register)


def test_compute_brief_metrics_headline_uses_only_study_without_filing() -> None:
    register = _synthetic_register()
    extra = register.iloc[[0]].copy()
    extra["claim_id"] = "estado_sin_expediente_en_ejecucion_inversion"
    extra["valor"] = 99_999.0
    register = pd.concat([register, extra], ignore_index=True)

    metrics = compute_brief_metrics(register).set_index("claim_id")

    assert metrics.loc["estado_sin_expediente_en_estudio_inversion", "valor"] == 21_000.0
    assert "estado_sin_expediente_en_ejecucion_inversion" not in metrics.index


@pytest.mark.parametrize(
    ("value", "decimals", "lang", "expected"),
    [
        (21_894, 0, "es", "21.894"),
        (7.7, 1, "es", "7,7"),
        (21_894, 0, "en", "21,894"),
        (7.7, 1, "en", "7.7"),
    ],
)
def test_format_number_uses_language_specific_separators(
    value: float, decimals: int, lang: str, expected: str
) -> None:
    assert format_number(value, decimals, lang) == expected


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("es", "21.000 MMUS$ en 8 proyectos, todos en etapa de estudio · corte SEA 25-08-2026"),
        ("en", "US$21,000m across 8 projects, all at study stage · SEA data to 25-08-2026"),
    ],
)
def test_subtitle_uses_whole_mmusd_and_one_decimal_percentages(
    lang: str, expected: str
) -> None:
    assert _brief_copy(compute_brief_metrics(_synthetic_register()), lang)["subtitle"] == expected


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("es", "38,4% (IC95% 26,4–49,8) · n=81"),
        ("en", "38.4% (95% CI 26.4–49.8) · n=81"),
    ],
)
def test_bootstrap_percentages_use_one_decimal(lang: str, expected: str) -> None:
    assert _brief_copy(compute_brief_metrics(_synthetic_register()), lang)[
        "bootstrap_body"
    ] == expected


def test_rendered_brief_is_one_page_and_contains_no_portfolio_names(tmp_path: Path) -> None:
    assert reportlab and pypdf

    output = tmp_path / "brief.pdf"
    metrics = compute_brief_metrics(_synthetic_register())
    render_brief(metrics, "es", output, portfolio_names=["Empresa Prohibida"])

    reader = pypdf.PdfReader(output)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) == 1
    assert "Empresa Prohibida" not in text


@pytest.mark.parametrize(
    ("lang", "headline", "footer_sentence"),
    [
        (
            "es",
            "21,0% de la inversión minera 2025–2034 no tiene expediente SEIA identificado",
            "Cifras recalculadas por un script independiente",
        ),
        (
            "en",
            "21.0% of 2025–2034 mining investment has no identified SEIA filing",
            "Figures recalculated by an independent script",
        ),
    ],
)
def test_pdf_text_extraction_preserves_headline_and_footer_sentence(
    tmp_path: Path, lang: str, headline: str, footer_sentence: str
) -> None:
    output = tmp_path / f"brief_{lang}.pdf"

    render_brief(compute_brief_metrics(_synthetic_register()), lang, output)

    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(output).pages)
    assert headline in text
    assert footer_sentence in text
    assert footer_sentence in text


def test_render_brief_writes_a_pdf_without_optional_pdf_reader(tmp_path: Path) -> None:
    output = tmp_path / "brief.pdf"

    render_brief(compute_brief_metrics(_synthetic_register()), "en", output)

    assert output.read_bytes().startswith(b"%PDF")
