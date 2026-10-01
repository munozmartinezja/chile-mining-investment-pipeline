from __future__ import annotations

import pandas as pd
import pytest

from cmip.portfolio_status import (
    apply_automatic_match_rules,
    apply_j_decisions,
    build_confirmed_match_table,
    build_doubtful_cases,
    build_portfolio_status,
    classify_environmental_status,
    write_portfolio_status,
)


def _review_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cochilco_id": ["auto", "auto", "low", "low", "close", "close", "company"],
            "cochilco_nombre": ["A", "A", "B", "B", "C", "C", "D"],
            "cochilco_empresa": ["CA", "CA", "CB", "CB", "CC", "CC", "CD"],
            "cochilco_mina": ["MA", "MA", "MB", "MB", "MC", "MC", "MD"],
            "exp_id": [101, 102, 201, 202, 301, 302, 401],
            "sea_nombre": ["A1", "A2", "B1", "B2", "C1", "C2", "D1"],
            "sea_empresa": ["SA", "SA", "SB", "SB", "SC", "SC", "SD"],
            "sea_estado": ["Aprobado"] * 7,
            "sea_fecha_ingreso": ["2020-01-01"] * 7,
            "score": [98.0, 80.0, 59.0, 40.0, 94.0, 90.0, 100.0],
            "empresa_no_coincide": [False, False, True, True, False, False, True],
            "match_tipo": [
                "alto",
                "alto",
                "sin_candidato",
                "sin_candidato",
                "revisar",
                "revisar",
                "revisar",
            ],
            "match_confirmado": [""] * 7,
        }
    )


def test_automatic_rules_confirm_company_match_and_low_mismatch() -> None:
    result = apply_automatic_match_rules(_review_candidates())
    decisions = result.loc[result["match_confirmado"].astype(str).ne("")]

    assert decisions[["cochilco_id", "match_confirmado", "criterio"]].to_dict(
        "records"
    ) == [
        {"cochilco_id": "auto", "match_confirmado": "101", "criterio": "regla_auto"},
        {
            "cochilco_id": "low",
            "match_confirmado": "NA",
            "criterio": "regla_sin_expediente",
        },
    ]
    assert result.loc[result["cochilco_id"].isin(["close", "company"]), "criterio"].eq("").all()


def test_reentry_rule_selects_newest_same_name_and_records_history() -> None:
    review = pd.DataFrame(
        {
            "cochilco_id": ["cap-los-colorados"] * 5,
            "exp_id": [2162201555, 2164006597, 2145025521, 9001, 9002],
            "sea_nombre": [
                "Modificación Proyecto Mina Los Colorados: Ajustes y Continuidad Operacional",
                "Modificación Proyecto Mina Los Colorados - Ajustes y Continuidad Operacional",
                "Modificación Plan Minero Mina Los Colorados",
                "Proyecto alternativo repetido",
                "Proyecto alternativo repetido",
            ],
            "sea_fecha_ingreso": [
                "2024-06-11",
                "2025-01-17",
                "2020-01-14",
                "2025-02-01",
                "2025-03-01",
            ],
            # The newer filing wins within the chosen normalized name even when its
            # fuzzy score is slightly lower.
            "score": [100.0, 99.0, 68.3, 96.0, 96.0],
            "empresa_no_coincide": [False, False, False, True, True],
            "match_confirmado": [""] * 5,
            "criterio": [""] * 5,
            "historial": [""] * 5,
        }
    )

    result = apply_automatic_match_rules(review)
    selected = result.loc[result["match_confirmado"].ne("")].iloc[0]

    assert selected["match_confirmado"] == "2164006597"
    assert selected["criterio"] == "regla_reingreso"
    assert selected["historial"] == "2162201555"


def test_reentry_rule_ignores_repeated_names_from_wrong_company() -> None:
    review = pd.DataFrame(
        {
            "cochilco_id": ["project"] * 3,
            "exp_id": [1, 2, 3],
            "sea_nombre": ["Exact project", "Unrelated repeat", "Unrelated repeat"],
            "sea_fecha_ingreso": ["2024-01-01", "2024-02-01", "2024-03-01"],
            "score": [100.0, 96.0, 95.0],
            "empresa_no_coincide": [False, True, True],
        }
    )

    result = apply_automatic_match_rules(review)
    selected = result.loc[result["match_confirmado"].ne("")].iloc[0]

    assert selected["match_confirmado"] == "1"
    assert selected["criterio"] == "regla_auto"


def test_reentry_rule_requires_repeated_name_to_include_best_candidate() -> None:
    review = pd.DataFrame(
        {
            "cochilco_id": ["project"] * 3,
            "exp_id": [1, 2, 3],
            "sea_nombre": ["Exact project", "Secondary repeat", "Secondary repeat"],
            "sea_fecha_ingreso": ["2024-01-01", "2024-02-01", "2024-03-01"],
            "score": [100.0, 96.0, 95.0],
            "empresa_no_coincide": [False, False, False],
        }
    )

    result = apply_automatic_match_rules(review)
    selected = result.loc[result["match_confirmado"].ne("")].iloc[0]

    assert selected["match_confirmado"] == "1"
    assert selected["criterio"] == "regla_auto"


def test_no_case_rule_requires_all_candidates_to_miss_company() -> None:
    review = pd.DataFrame(
        {
            "cochilco_id": ["project", "project"],
            "exp_id": [1, 2],
            "sea_nombre": ["Weak first", "Weak company candidate"],
            "sea_fecha_ingreso": ["2024-01-01", "2024-02-01"],
            "score": [70.0, 60.0],
            "empresa_no_coincide": [True, False],
        }
    )

    result = apply_automatic_match_rules(review)

    assert result["match_confirmado"].eq("").all()


def test_doubtful_cases_show_top_three_candidates_and_attributes() -> None:
    review = _review_candidates()
    extra = review.loc[review["cochilco_id"].eq("close")].iloc[[0]].copy()
    extra["exp_id"] = 303
    extra["score"] = 70.0
    review = pd.concat([review, extra], ignore_index=True)
    ruled = apply_automatic_match_rules(review)

    doubtful = build_doubtful_cases(ruled)

    close = doubtful.loc[doubtful["cochilco_id"].eq("close")]
    assert close["exp_id"].tolist() == [301, 302, 303]
    assert close["rank_candidato"].tolist() == [1, 2, 3]
    assert {
        "cochilco_mina",
        "sea_nombre",
        "sea_empresa",
        "sea_estado",
        "score",
        "margen_top2",
    }.issubset(doubtful.columns)


def test_j_decisions_fill_only_explicit_projects_with_provenance() -> None:
    ruled = apply_automatic_match_rules(_review_candidates())

    result = apply_j_decisions(ruled, {"close": 302, "company": "NA"})
    confirmed = build_confirmed_match_table(result)

    assert confirmed.set_index("cochilco_id").loc["close", "exp_id_confirmado"] == 302
    assert confirmed.set_index("cochilco_id").loc["close", "criterio"] == "decision_J"
    assert pd.isna(confirmed.set_index("cochilco_id").loc["company", "exp_id_confirmado"])


def test_j_decision_adds_verified_sea_case_outside_top_n() -> None:
    review = apply_automatic_match_rules(
        _review_candidates().loc[lambda frame: frame["cochilco_id"].eq("close")]
    )
    sea_mining = pd.DataFrame(
        {
            "exp_id": [2130502645],
            "exp_nombre": ["Desarrollo Minera Centinela"],
            "empresa_nombre": ["Minera Centinela SpA"],
            "titular_nombre": ["Titular alternativo"],
            "estado": ["Aprobado"],
            "fecha_ingreso": pd.to_datetime(["2015-07-21"]),
        }
    )

    result = apply_j_decisions(
        review, {"close": 2130502645}, sea_mining=sea_mining
    )

    manual = result.loc[result["exp_id"].eq(2130502645)].iloc[0]
    assert manual["sea_nombre"] == "Desarrollo Minera Centinela"
    assert manual["sea_empresa"] == "Minera Centinela SpA"
    assert manual["sea_estado"] == "Aprobado"
    assert manual["sea_fecha_ingreso"] == pd.Timestamp("2015-07-21")
    assert pd.isna(manual["score"])
    assert manual["match_tipo"] == "manual_J"
    assert manual["match_confirmado"] == "2130502645"
    assert manual["criterio"] == "decision_J"
    assert manual["historial"] == "fuera_de_top_n"
    assert result.loc[result["exp_id"].ne(2130502645), "match_confirmado"].eq("").all()

    confirmed = build_confirmed_match_table(result)
    assert len(confirmed) == 1
    assert confirmed.iloc[0]["exp_id_confirmado"] == 2130502645


def test_j_decision_rejects_case_absent_from_sea_mining() -> None:
    review = apply_automatic_match_rules(
        _review_candidates().loc[lambda frame: frame["cochilco_id"].eq("close")]
    )
    sea_mining = pd.DataFrame(
        {
            "exp_id": [999],
            "exp_nombre": ["Otro proyecto"],
            "empresa_nombre": ["Otra empresa"],
            "titular_nombre": ["Otro titular"],
            "estado": ["Aprobado"],
            "fecha_ingreso": pd.to_datetime(["2015-01-01"]),
        }
    )

    with pytest.raises(ValueError, match="is not a candidate"):
        apply_j_decisions(review, {"close": 2130502645}, sea_mining=sea_mining)


def test_j_decision_outside_top_n_without_sea_mining_keeps_current_error() -> None:
    review = apply_automatic_match_rules(
        _review_candidates().loc[lambda frame: frame["cochilco_id"].eq("close")]
    )

    with pytest.raises(ValueError, match="is not a candidate"):
        apply_j_decisions(review, {"close": 2130502645}, sea_mining=None)


@pytest.mark.parametrize("criterion", ["regla_auto", "regla_reingreso", "regla_sin_expediente"])
def test_j_decisions_cannot_override_automatic_rules(criterion: str) -> None:
    review = pd.DataFrame(
        {
            "cochilco_id": ["project"],
            "exp_id": [101],
            "score": [100.0],
            "match_confirmado": ["101"],
            "criterio": [criterion],
        }
    )

    with pytest.raises(ValueError, match="override automatic rule"):
        apply_j_decisions(review, {"project": "NA"})


@pytest.mark.parametrize(
    ("evento", "exp_id", "expected"),
    [
        ("aprobado", 1, "aprobado"),
        ("en_tramite", 2, "en_evaluacion"),
        ("desistido_o_abandonado", 3, "desistido_o_rechazado"),
        ("rechazado", 4, "desistido_o_rechazado"),
        ("termino_anticipado", 5, "desistido_o_rechazado"),
        ("no_admitido", 6, "otro"),
        (pd.NA, pd.NA, "sin_ingreso_seia"),
    ],
)
def test_classify_environmental_status_maps_normalized_outcomes(
    evento: object, exp_id: object, expected: str
) -> None:
    assert classify_environmental_status(evento, exp_id) == expected


def test_confirmed_match_table_uses_decision_not_candidate_score() -> None:
    review = pd.DataFrame(
        {
            "cochilco_id": ["c1", "c1", "c2"],
            "exp_id": [101, 102, pd.NA],
            "score": [99.9, 5.0, 100.0],
            "match_confirmado": ["102", "", "NA"],
            "criterio": ["decision_J", "", "regla_auto"],
        }
    )

    result = build_confirmed_match_table(review)

    assert result["cochilco_id"].tolist() == ["c1", "c2"]
    assert result.loc[0, "exp_id_confirmado"] == 102
    assert pd.isna(result.loc[1, "exp_id_confirmado"])
    assert result["criterio"].tolist() == ["decision_J", "regla_auto"]


def test_confirmed_match_table_rejects_unreviewed_projects() -> None:
    review = pd.DataFrame(
        {
            "cochilco_id": ["c1", "c2"],
            "exp_id": [101, 102],
            "score": [99.0, 80.0],
            "match_confirmado": ["101", ""],
            "criterio": ["decision_J", ""],
        }
    )

    with pytest.raises(ValueError, match="review decision.*c2"):
        build_confirmed_match_table(review)


def test_confirmed_match_table_rejects_a_decision_without_provenance() -> None:
    review = pd.DataFrame(
        {
            "cochilco_id": ["c1"],
            "match_confirmado": ["101"],
            "criterio": [""],
        }
    )

    with pytest.raises(ValueError, match="Missing criterio.*c1"):
        build_confirmed_match_table(review)


@pytest.mark.parametrize(
    ("criterion", "history", "message"),
    [
        ("regla_auto", "100", "only valid for regla_reingreso"),
        ("regla_reingreso", "not-an-id", "Invalid historial"),
        ("regla_reingreso", "101", "selected exp_id"),
        ("regla_reingreso", "999", "not a candidate"),
    ],
)
def test_confirmed_match_table_validates_history(
    criterion: str, history: str, message: str
) -> None:
    review = pd.DataFrame(
        {
            "cochilco_id": ["c1", "c1"],
            "exp_id": [100, 101],
            "match_confirmado": ["101", ""],
            "criterio": [criterion, ""],
            "historial": [history, ""],
        }
    )

    with pytest.raises(ValueError, match=message):
        build_confirmed_match_table(review)


def test_portfolio_status_rejects_undocumented_duplicate_expedientes() -> None:
    cochilco = pd.DataFrame(
        {
            "project_id": ["c1", "c2"],
            "inversion_musd": [10.0, 20.0],
            "nota_agregacion": [False, False],
        }
    )
    confirmed = pd.DataFrame(
        {
            "cochilco_id": ["c1", "c2"],
            "exp_id_confirmado": [101, 101],
            "criterio": ["confirmado_manual", "confirmado_manual"],
        }
    )
    sea = pd.DataFrame(
        {
            "exp_id": [101],
            "instrumento": ["DIA"],
            "evento": ["aprobado"],
            "fecha_ingreso": pd.to_datetime(["2020-01-01"]),
            "duracion_dias": [100],
            "estado": ["Aprobado"],
        }
    )

    with pytest.raises(ValueError, match="Duplicate confirmed exp_id"):
        build_portfolio_status(cochilco, confirmed, sea)


def test_writer_emits_only_privacy_safe_confirmed_match_columns(tmp_path) -> None:  # noqa: ANN001
    review_path = tmp_path / "match_review.csv"
    cochilco_path = tmp_path / "cochilco.parquet"
    sea_path = tmp_path / "sea.parquet"
    confirmed_path = tmp_path / "cochilco_seia_match.csv"
    output_path = tmp_path / "cochilco_seia.parquet"
    pd.DataFrame(
        {
            "cochilco_id": ["c1", "c2"],
            "cochilco_empresa": ["Empresa privada", "Otra empresa"],
            "match_confirmado": ["101", "NA"],
            "criterio": ["decision_J", "regla_sin_expediente"],
        }
    ).to_csv(review_path, index=False)
    pd.DataFrame(
        {
            "project_id": ["c1", "c2"],
            "inversion_musd": [10.0, 20.0],
            "nota_agregacion": [False, False],
        }
    ).to_parquet(cochilco_path, index=False)
    pd.DataFrame(
        {
            "exp_id": [101],
            "instrumento": ["DIA"],
            "evento": ["aprobado"],
            "fecha_ingreso": pd.to_datetime(["2020-01-01"]),
            "duracion_dias": [100],
            "estado": ["Aprobado"],
            "titular_nombre": ["Persona privada"],
        }
    ).to_parquet(sea_path, index=False)

    portfolio = write_portfolio_status(
        review_path, cochilco_path, sea_path, confirmed_path, output_path
    )

    confirmed = pd.read_csv(confirmed_path)
    assert confirmed.columns.tolist() == [
        "cochilco_id",
        "exp_id_confirmado",
        "criterio",
        "historial",
    ]
    assert "Empresa privada" not in confirmed_path.read_text(encoding="utf-8")
    assert "Persona privada" not in confirmed_path.read_text(encoding="utf-8")
    assert len(portfolio) == 2
