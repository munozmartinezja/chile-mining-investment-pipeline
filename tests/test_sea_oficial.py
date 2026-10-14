from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cmip.sea_oficial import load_sea_oficial

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_PATH = ROOT / "data/raw/sea_transparencia/sea_transparencia_proyectos_mineros_20261013.csv"

HEADERS = [
    "ID_EXPEDIENTE",
    "NOMBRE_PROYECTO",
    "TIPO DE PRESENTACION",
    "REGION",
    "COMUNA",
    "PROVINCIA",
    "TIPOLOGIA",
    "SECTOR_PRODUCTIVO",
    "RAZON_DE_INGRESO",
    "ESTADO",
    "MONTO_INVERSION",
    "TITULAR",
    "EMPRESA",
    "FECHA_PRESENTACION",
    "FECHA_CIERRE",
    "DIAS_CORRIDOS",
    "DIAS_EVALUACION_INHABIL",
    "DIAS_EVALUACION_HABIL",
    "DIAS_SUSPENSION_INHABIL",
    "DIAS_SUSPENSION_HABIL",
    "COORDENADA_X",
    "COORDENADA_Y",
    "LINK_EXPEDIENTE",
]


def _write_official_fixture(path: Path, *, delimiter: str = ";") -> None:
    values = [
        "2165000000",
        "Proyecto sintético",
        "EIA DS40",
        "II",
        "Calama",
        "El Loa",
        "i4",
        "Minería",
        "Ingreso voluntario",
        "Aprobado",
        "1.234.567.890",
        "Titular reservado",
        "Empresa reservada",
        "24/08/2026",
        "25/08/2026",
        "1",
        "2",
        "3",
        "4",
        "5",
        "-69,1234",
        "-22,5678",
        "https://example.invalid/2165000000",
    ]
    text = delimiter.join(HEADERS) + "\r\n" + delimiter.join(values) + "\r\n"
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))


def test_load_sea_oficial_parses_bom_semicolon_and_domain_types(tmp_path: Path) -> None:
    path = tmp_path / "oficial.csv"
    _write_official_fixture(path)

    result = load_sea_oficial(path)

    assert len(result) == 1
    assert len(result.columns) == 24
    assert result.loc[0, "exp_id"] == 2_165_000_000
    assert result["exp_id"].dtype == "int64"
    assert result.loc[0, "instrumento"] == "EIA"
    assert result.loc[0, "reglamento"] == "DS40"
    assert result.loc[0, "fecha_ingreso"] == pd.Timestamp("2026-08-24")
    assert result.loc[0, "fecha_cierre"] == pd.Timestamp("2026-08-25")
    assert result.loc[0, "inversion_musd"] == pytest.approx(1_234.56789)
    assert result.loc[0, "coordenada_x"] == pytest.approx(-69.1234)
    assert result.loc[0, "coordenada_y"] == pytest.approx(-22.5678)
    for column in (
        "dias_corridos",
        "dias_evaluacion_inhabil",
        "dias_evaluacion_habil",
        "dias_suspension_inhabil",
        "dias_suspension_habil",
    ):
        assert result[column].dtype == "Int64"


def test_load_sea_oficial_rejects_a_changed_separator(tmp_path: Path) -> None:
    path = tmp_path / "oficial.csv"
    _write_official_fixture(path, delimiter=",")

    with pytest.raises(ValueError, match="separador.*;.*23 columnas"):
        load_sea_oficial(path)


def test_load_sea_oficial_rejects_a_missing_column(tmp_path: Path) -> None:
    path = tmp_path / "oficial.csv"
    _write_official_fixture(path)
    text = path.read_text(encoding="utf-8-sig").replace(";EMPRESA", "", 1)
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))

    with pytest.raises(ValueError, match="esquema.*empresa"):
        load_sea_oficial(path)


@pytest.mark.skipif(not OFFICIAL_PATH.exists(), reason="requires local official SEA response")
def test_real_sea_oficial_file_has_expected_shape_and_types() -> None:
    result = load_sea_oficial(OFFICIAL_PATH)

    assert result.shape == (1_965, 24)
    assert result["exp_id"].dtype == "int64"
    assert result["fecha_ingreso"].dtype == "datetime64[ns]"
    assert result["fecha_cierre"].dtype == "datetime64[ns]"
    assert set(result["instrumento"]) == {"DIA", "EIA"}
    assert set(result["reglamento"]) == {"", "DS17", "DS40"}
