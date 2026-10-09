"""Build the manually confirmed Cochilco-to-SEA portfolio status."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from cmip.config import PROCESSED_DIR, PROJECT_ROOT
from cmip.match import is_viable_principal_state, reentry_family_key

CURATED_DIR = PROJECT_ROOT / "data" / "curated"
REVIEW_PATH = PROJECT_ROOT / "docs" / "match_review.csv"
COCHILCO_PATH = PROCESSED_DIR / "cochilco_projects.parquet"
SEA_PATH = PROJECT_ROOT / "data" / "interim" / "sea_mining.parquet"
CONFIRMED_MATCH_PATH = CURATED_DIR / "cochilco_seia_match.csv"
PORTFOLIO_STATUS_PATH = PROCESSED_DIR / "cochilco_seia.parquet"
CHECKLIST_PATH = PROJECT_ROOT / "docs" / "validation_checklist.csv"
SHARED_EXCEPTIONS_PATH = CURATED_DIR / "shared_expediente_exceptions.csv"

MATCH_OUTPUT_COLUMNS = [
    "cochilco_id",
    "exp_id_confirmado",
    "criterio",
    "historial",
    "estado_ambiental_override",
]
SEA_STATUS_COLUMNS = [
    "exp_id",
    "instrumento",
    "evento",
    "fecha_ingreso",
    "duracion_dias",
    "estado",
]
ADVERSE_EVENTS = {"desistido_o_abandonado", "rechazado", "termino_anticipado"}
DECISION_CRITERIA = {
    "regla_auto",
    "regla_reingreso",
    "regla_sin_expediente",
    "decision_J",
    "decision_J_checklist",
    "regla_desplazada_por_checklist",
}
AFFIRMATIVE_CHECKLIST_RESPONSES = {
    "si",
    "rca_identificada",
    "expediente_encontrado",
}
CONFIRM_ASSIGNED_RESPONSE = "confirmado"
EMPTY_CHECKLIST_RESPONSES = {"sin_expediente", "otra_fase"}
SPECIAL_CHECKLIST_STATUSES = {
    "rca_previa": "rca_previa_2011",
    "fila_agregada": "agregado_no_asignable",
    "pertinencia": "pertinencia",
    "no_determinado": "no_determinado",
}
CHECKLIST_RESPONSES = (
    AFFIRMATIVE_CHECKLIST_RESPONSES
    | EMPTY_CHECKLIST_RESPONSES
    | set(SPECIAL_CHECKLIST_STATUSES)
    | {CONFIRM_ASSIGNED_RESPONSE}
    | {""}
)


def _decision_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _parse_confirmed_id(value: str) -> int:
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(f"Invalid match_confirmado value: {value!r}") from error
    if not number.is_integer():
        raise ValueError(f"Confirmed exp_id must be an integer: {value!r}")
    return int(number)


def _candidate_order(candidates: pd.DataFrame) -> pd.DataFrame:
    ordered = candidates.copy()
    ordered["_score_numeric"] = pd.to_numeric(ordered["score"], errors="coerce").fillna(
        float("-inf")
    )
    if "ranking_match" in ordered:
        ordered["_ranking_match_numeric"] = pd.to_numeric(
            ordered["ranking_match"], errors="coerce"
        ).fillna(float("inf"))
        return ordered.sort_values(
            ["_ranking_match_numeric", "exp_id"],
            ascending=[True, True],
            na_position="last",
        ).drop(columns="_ranking_match_numeric")
    return ordered.sort_values(
        ["_score_numeric", "exp_id"], ascending=[False, True], na_position="last"
    )


def apply_automatic_match_rules(review: pd.DataFrame) -> pd.DataFrame:
    """Apply conservative automatic decisions while preserving explicit J decisions."""
    required = {"cochilco_id", "exp_id", "score", "empresa_no_coincide"}
    missing = required.difference(review.columns)
    if missing:
        raise ValueError(f"Missing match-review columns: {sorted(missing)}")
    result = review.copy()
    if "match_confirmado" not in result:
        result["match_confirmado"] = ""
    if "criterio" not in result:
        result["criterio"] = ""
    if "historial" not in result:
        result["historial"] = ""
    result["match_confirmado"] = result["match_confirmado"].map(_decision_text)
    result["criterio"] = result["criterio"].map(_decision_text)
    result["historial"] = result["historial"].map(_decision_text)

    for _, candidates in result.groupby("cochilco_id", sort=False, dropna=False):
        explicit_j = candidates["criterio"].eq("decision_J") & candidates[
            "match_confirmado"
        ].ne("")
        if explicit_j.any():
            continue
        result.loc[candidates.index, ["match_confirmado", "criterio", "historial"]] = ""
        ordered = _candidate_order(candidates)
        best = ordered.iloc[0]
        best_score = float(best["_score_numeric"])
        decision = ""
        criterion = ""
        history = ""
        high = ordered.loc[
            ordered["_score_numeric"].ge(95) & ~ordered["empresa_no_coincide"].astype(bool)
        ].copy()
        high["_family"] = high.apply(
            lambda row: reentry_family_key(row.get("sea_nombre"), row.get("sea_empresa")),
            axis=1,
        )
        best_family = reentry_family_key(best.get("sea_nombre"), best.get("sea_empresa"))
        repeated = high.loc[
            high["_family"].map(lambda family, target=best_family: family == target)
        ].copy()
        if len(repeated) >= 2:
            repeated["_date"] = pd.to_datetime(
                repeated["sea_fecha_ingreso"], errors="raise"
            )
            viable = (
                repeated.loc[repeated["sea_estado"].map(is_viable_principal_state)]
                if "sea_estado" in repeated
                else repeated
            )
            principal_pool = viable if not viable.empty else repeated
            principal_pool = principal_pool.sort_values(
                ["_date", "exp_id"], ascending=[False, False]
            )
            selected = principal_pool.iloc[0]
            decision = str(int(float(selected["exp_id"])))
            previous = repeated.loc[repeated.index != selected.name].sort_values(
                ["_date", "exp_id"]
            )
            history = ";".join(
                str(int(float(exp_id))) for exp_id in previous["exp_id"].dropna()
            )
            criterion = "regla_reingreso"
            best = selected
        elif best_score >= 95 and not bool(best["empresa_no_coincide"]):
            if pd.isna(best["exp_id"]):
                raise ValueError(f"Automatic match for {best['cochilco_id']} has no exp_id")
            decision = str(int(float(best["exp_id"])))
            criterion = "regla_auto"
        elif best_score < 75 and ordered["empresa_no_coincide"].astype(bool).all():
            decision = "NA"
            criterion = "regla_sin_expediente"
        if decision:
            result.loc[best.name, "match_confirmado"] = decision
            result.loc[best.name, "criterio"] = criterion
            result.loc[best.name, "historial"] = history
    return result


def build_doubtful_cases(review: pd.DataFrame, top_n: int = 3) -> pd.DataFrame:
    """Return the top candidates and review attributes for unresolved projects."""
    rows: list[pd.DataFrame] = []
    for _, candidates in review.groupby("cochilco_id", sort=False, dropna=False):
        if candidates["match_confirmado"].map(_decision_text).ne("").any():
            continue
        ordered = _candidate_order(candidates).head(top_n).copy()
        ordered["rank_candidato"] = range(1, len(ordered) + 1)
        if len(ordered) > 1:
            margin = float(ordered.iloc[0]["_score_numeric"]) - float(
                ordered.iloc[1]["_score_numeric"]
            )
        else:
            margin = float("inf")
        ordered["margen_top2"] = margin
        rows.append(ordered)
    if not rows:
        return pd.DataFrame()
    result = pd.concat(rows, ignore_index=True).drop(columns="_score_numeric")
    preferred = [
        "cochilco_id",
        "cochilco_nombre",
        "cochilco_empresa",
        "cochilco_mina",
        "rank_candidato",
        "exp_id",
        "sea_nombre",
        "sea_empresa",
        "sea_estado",
        "sea_fecha_ingreso",
        "score",
        "margen_top2",
        "empresa_no_coincide",
        "match_tipo",
    ]
    return result.loc[:, [column for column in preferred if column in result.columns]]


def apply_j_decisions(
    review: pd.DataFrame,
    decisions: dict[str, int | str],
    sea_mining: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Apply explicit reviewer decisions to unresolved projects with provenance."""
    result = review.copy()
    if "historial" not in result:
        result["historial"] = ""
    known = set(result["cochilco_id"].astype(str))
    unknown = set(decisions).difference(known)
    if unknown:
        raise ValueError(f"Unknown cochilco_id in J decisions: {sorted(unknown)}")
    for cochilco_id, raw_decision in decisions.items():
        candidates = result.loc[result["cochilco_id"].astype(str).eq(cochilco_id)]
        automatic = candidates["criterio"].isin(DECISION_CRITERIA - {"decision_J"})
        if automatic.any():
            raise ValueError(f"J decision would override automatic rule for {cochilco_id}")
        decision = _decision_text(raw_decision)
        if not decision:
            raise ValueError(f"Empty J decision for {cochilco_id}")
        ordered = _candidate_order(candidates)
        target_index = ordered.index[0]
        manual_row: dict[str, object] | None = None
        if decision.upper() == "NA":
            decision = "NA"
        else:
            exp_id = _parse_confirmed_id(decision)
            candidate_ids = pd.to_numeric(candidates["exp_id"], errors="coerce").dropna()
            if exp_id not in candidate_ids.astype(int).tolist():
                sea_matches = (
                    sea_mining.loc[
                        pd.to_numeric(sea_mining["exp_id"], errors="coerce").eq(exp_id)
                    ]
                    if sea_mining is not None and "exp_id" in sea_mining
                    else pd.DataFrame()
                )
                if sea_matches.empty:
                    raise ValueError(
                        f"J decision exp_id {exp_id} is not a candidate for {cochilco_id}"
                    )
                sea_case = sea_matches.iloc[0]
                manual_row = candidates.iloc[0].to_dict()
                sea_company = sea_case.get("empresa_nombre")
                if pd.isna(sea_company) or not str(sea_company).strip():
                    sea_company = sea_case.get("titular_nombre")
                manual_row.update(
                    {
                        "exp_id": exp_id,
                        "sea_nombre": sea_case.get("exp_nombre"),
                        "sea_empresa": sea_company,
                        "sea_estado": sea_case.get("estado"),
                        "sea_fecha_ingreso": sea_case.get("fecha_ingreso"),
                        "score": float("nan"),
                        "match_tipo": "manual_J",
                        "match_confirmado": str(exp_id),
                        "criterio": "decision_J",
                        "historial": "fuera_de_top_n",
                    }
                )
            else:
                target_index = candidates.index[
                    pd.to_numeric(candidates["exp_id"], errors="coerce").eq(exp_id)
                ][0]
            decision = str(exp_id)
        result.loc[candidates.index, ["match_confirmado", "criterio", "historial"]] = ""
        if manual_row is not None:
            result = pd.concat([result, pd.DataFrame([manual_row])], ignore_index=True)
        else:
            result.loc[target_index, "match_confirmado"] = decision
            result.loc[target_index, "criterio"] = "decision_J"
    return result


def _principal_from_source(source: object) -> int | None:
    text = _decision_text(source)
    matches = re.findall(r"(?:^|\s+\|\s+)principal:\s*(\d+)(?=\s|$)", text)
    if not matches:
        return None
    principals = {int(value) for value in matches}
    if len(principals) != 1:
        raise ValueError(f"Contradictory principal segments in fuente_J: {text!r}")
    return principals.pop()


def apply_checklist_decisions(
    confirmed: pd.DataFrame,
    checklist: pd.DataFrame,
    sea_mining: pd.DataFrame,
) -> pd.DataFrame:
    """Override automatic matches with J's validated checklist decisions."""
    confirmed_required = {"cochilco_id", "exp_id_confirmado", "criterio"}
    checklist_required = {"cochilco_id", "pregunta", "respuesta_J", "fuente_J"}
    missing_confirmed = confirmed_required.difference(confirmed.columns)
    missing_checklist = checklist_required.difference(checklist.columns)
    if missing_confirmed:
        raise ValueError(f"Missing confirmed columns: {sorted(missing_confirmed)}")
    if missing_checklist:
        raise ValueError(f"Missing checklist columns: {sorted(missing_checklist)}")
    if checklist.duplicated(["cochilco_id", "pregunta"]).any():
        raise ValueError("Checklist key (cochilco_id, pregunta) must be unique")
    if "exp_id" not in sea_mining:
        raise ValueError("sea_mining has no exp_id column")

    result = confirmed.copy()
    if "historial" not in result:
        result["historial"] = ""
    if "estado_ambiental_override" not in result:
        result["estado_ambiental_override"] = ""
    result["estado_ambiental_override"] = result["estado_ambiental_override"].map(
        _decision_text
    )
    known_ids = set(result["cochilco_id"].astype(str))
    checklist_ids = set(checklist["cochilco_id"].astype(str))
    unknown_ids = checklist_ids - known_ids
    if unknown_ids:
        raise ValueError(f"Checklist contains unknown cochilco_id values: {sorted(unknown_ids)}")

    responses = checklist["respuesta_J"].map(_decision_text).str.casefold()
    invalid = set(responses) - CHECKLIST_RESPONSES
    if invalid:
        raise ValueError(f"Invalid respuesta_J values: {sorted(invalid)}")
    sea_ids = set(pd.to_numeric(sea_mining["exp_id"], errors="raise").astype(int))

    checklist_work = checklist.copy()
    checklist_work["_response"] = responses
    for cochilco_id, decisions in checklist_work.groupby("cochilco_id", sort=False):
        decisions = decisions.loc[decisions["_response"].ne("")]
        if decisions.empty:
            continue
        confirms_assigned = decisions["_response"].eq(CONFIRM_ASSIGNED_RESPONSE).any()
        affirmative = decisions.loc[
            decisions["_response"].isin(AFFIRMATIVE_CHECKLIST_RESPONSES)
        ]
        principals: set[int] = set()
        for row in affirmative.itertuples(index=False):
            principal = _principal_from_source(row.fuente_J)
            if principal is None:
                raise ValueError(
                    "Checklist affirmative response requires a principal in fuente_J "
                    f"for {cochilco_id}"
                )
            principals.add(principal)
        confirmed_rows = decisions.loc[
            decisions["_response"].eq(CONFIRM_ASSIGNED_RESPONSE)
        ]
        for row in confirmed_rows.itertuples(index=False):
            if (principal := _principal_from_source(row.fuente_J)) is not None:
                principals.add(principal)
        if len(principals) > 1:
            raise ValueError(
                f"Contradictory checklist principal values for {cochilco_id}: "
                f"{sorted(principals)}"
            )

        special_responses = set(decisions["_response"]) & set(
            SPECIAL_CHECKLIST_STATUSES
        )
        if principals and special_responses:
            raise ValueError(
                f"Contradictory principal and environmental decisions for {cochilco_id}"
            )
        if len(special_responses - {"fila_agregada", "rca_previa"}) > 1:
            raise ValueError(
                f"Contradictory environmental checklist decisions for {cochilco_id}: "
                f"{sorted(special_responses)}"
            )
        if special_responses & {"pertinencia", "no_determinado"} and len(
            special_responses
        ) > 1:
            raise ValueError(
                f"Contradictory environmental checklist decisions for {cochilco_id}: "
                f"{sorted(special_responses)}"
            )

        target = result["cochilco_id"].astype(str).eq(str(cochilco_id))
        assigned = result.loc[target, "exp_id_confirmado"].dropna()
        principal = next(iter(principals), None)
        if confirms_assigned and principal is None:
            if assigned.empty:
                raise ValueError(
                    f"Checklist confirmado requires an assigned principal for {cochilco_id}"
                )
            principal = int(assigned.iloc[0])
        if principal is not None and principal not in sea_ids:
            raise ValueError(
                f"Checklist principal {principal} for {cochilco_id} is absent from sea_mining"
            )
        if principal is not None:
            override = ""
        elif "fila_agregada" in special_responses:
            override = SPECIAL_CHECKLIST_STATUSES["fila_agregada"]
        elif "rca_previa" in special_responses:
            override = SPECIAL_CHECKLIST_STATUSES["rca_previa"]
        elif special_responses:
            override = SPECIAL_CHECKLIST_STATUSES[next(iter(special_responses))]
        else:
            override = ""

        result.loc[target, "exp_id_confirmado"] = (
            principal if principal is not None else pd.NA
        )
        result.loc[target, "criterio"] = "decision_J_checklist"
        result.loc[target, "historial"] = ""
        result.loc[target, "estado_ambiental_override"] = override

    duplicated_ids = result.loc[
        result["exp_id_confirmado"].notna()
        & result["exp_id_confirmado"].duplicated(keep=False),
        "exp_id_confirmado",
    ].unique()
    for exp_id in duplicated_ids:
        same_expediente = result["exp_id_confirmado"].eq(exp_id)
        checklist_owner = same_expediente & result["criterio"].eq(
            "decision_J_checklist"
        )
        if checklist_owner.sum() != 1:
            continue
        displaced = same_expediente & ~checklist_owner
        result.loc[displaced, "exp_id_confirmado"] = pd.NA
        result.loc[displaced, "criterio"] = "regla_desplazada_por_checklist"
        result.loc[displaced, "historial"] = ""
        result.loc[displaced, "estado_ambiental_override"] = ""

    result["exp_id_confirmado"] = pd.to_numeric(
        result["exp_id_confirmado"], errors="coerce"
    ).astype("Int64")
    return result.loc[:, MATCH_OUTPUT_COLUMNS]


def _validate_shared_expediente_assignments(
    confirmed: pd.DataFrame,
    shared_expediente_exceptions: pd.DataFrame | None,
) -> None:
    duplicated = confirmed.loc[
        confirmed["exp_id_confirmado"].notna()
        & confirmed["exp_id_confirmado"].duplicated(keep=False),
        ["cochilco_id", "exp_id_confirmado"],
    ]
    if duplicated.empty:
        return
    exceptions = (
        shared_expediente_exceptions
        if shared_expediente_exceptions is not None
        else pd.DataFrame(columns=["exp_id", "cochilco_id", "motivo"])
    )
    required = {"exp_id", "cochilco_id", "motivo"}
    missing = required.difference(exceptions.columns)
    if missing:
        raise ValueError(f"Missing shared-expediente exception columns: {sorted(missing)}")
    if exceptions["motivo"].map(_decision_text).eq("").any():
        raise ValueError("Shared-expediente exceptions require a motivo")
    allowed = set(
        zip(
            pd.to_numeric(exceptions["exp_id"], errors="raise").astype(int),
            exceptions["cochilco_id"].astype(str),
            strict=True,
        )
    )
    actual = set(
        zip(
            duplicated["exp_id_confirmado"].astype(int),
            duplicated["cochilco_id"].astype(str),
            strict=True,
        )
    )
    undocumented = actual - allowed
    if undocumented:
        ids = sorted({exp_id for exp_id, _ in undocumented})
        raise ValueError(
            "An expediente cannot be principal for two Cochilco projects; "
            f"Duplicate confirmed exp_id without documented exception: {ids}"
        )


def build_confirmed_match_table(
    review: pd.DataFrame,
    shared_expediente_exceptions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Reduce candidate rows to one explicit human decision per Cochilco project."""
    required = {"cochilco_id", "match_confirmado", "criterio"}
    missing = required.difference(review.columns)
    if missing:
        raise ValueError(f"Missing match-review columns: {sorted(missing)}")

    records: list[dict[str, object]] = []
    unreviewed: list[str] = []
    for cochilco_id, candidates in review.groupby("cochilco_id", sort=False, dropna=False):
        decisions = {text for text in candidates["match_confirmado"].map(_decision_text) if text}
        if not decisions:
            unreviewed.append(str(cochilco_id))
            continue
        if len(decisions) != 1:
            raise ValueError(
                f"Conflicting match_confirmado decisions for {cochilco_id}: {sorted(decisions)}"
            )
        decision = decisions.pop()
        decision_rows = candidates.loc[
            candidates["match_confirmado"].map(_decision_text).eq(decision)
        ]
        criteria = (
            {
                text
                for text in decision_rows["criterio"].map(_decision_text)
                if text
            }
            if "criterio" in decision_rows
            else set()
        )
        if len(criteria) > 1:
            raise ValueError(f"Conflicting criterio values for {cochilco_id}: {sorted(criteria)}")
        if not criteria:
            raise ValueError(f"Missing criterio for confirmed decision in {cochilco_id}")
        criterion = criteria.pop()
        if criterion not in DECISION_CRITERIA:
            raise ValueError(f"Invalid criterio for {cochilco_id}: {criterion}")
        histories = (
            {
                text
                for text in decision_rows["historial"].map(_decision_text)
                if text
            }
            if "historial" in decision_rows
            else set()
        )
        if len(histories) > 1:
            raise ValueError(f"Conflicting historial values for {cochilco_id}")
        history = histories.pop() if histories else ""
        if decision.upper() == "NA":
            exp_id: object = pd.NA
        else:
            exp_id = _parse_confirmed_id(decision)
        is_outside_top_n = criterion == "decision_J" and history == "fuera_de_top_n"
        if history and criterion != "regla_reingreso" and not is_outside_top_n:
            raise ValueError(
                f"historial is only valid for regla_reingreso in {cochilco_id}"
            )
        if criterion == "regla_reingreso":
            if not history:
                raise ValueError(f"Missing historial for regla_reingreso in {cochilco_id}")
            try:
                history_ids = [_parse_confirmed_id(value) for value in history.split(";")]
            except ValueError as error:
                raise ValueError(f"Invalid historial for {cochilco_id}") from error
            if len(history_ids) != len(set(history_ids)):
                raise ValueError(f"Duplicate exp_id in historial for {cochilco_id}")
            if exp_id in history_ids:
                raise ValueError(f"historial contains selected exp_id for {cochilco_id}")
            candidates_ids = set(
                pd.to_numeric(candidates["exp_id"], errors="coerce").dropna().astype(int)
            )
            if not set(history_ids).issubset(candidates_ids):
                raise ValueError(f"historial exp_id is not a candidate for {cochilco_id}")
        records.append(
            {
                "cochilco_id": cochilco_id,
                "exp_id_confirmado": exp_id,
                "criterio": criterion,
                "historial": history,
                "estado_ambiental_override": "",
            }
        )
    if unreviewed:
        preview = ", ".join(unreviewed[:5])
        suffix = "..." if len(unreviewed) > 5 else ""
        raise ValueError(
            f"Missing review decision in match_confirmado for {len(unreviewed)} project(s): "
            f"{preview}{suffix}"
        )
    result = pd.DataFrame(records, columns=MATCH_OUTPUT_COLUMNS)
    result["exp_id_confirmado"] = result["exp_id_confirmado"].astype("Int64")
    _validate_shared_expediente_assignments(result, shared_expediente_exceptions)
    return result


def classify_environmental_status(
    evento: object, exp_id: object, etapa: object | None = None
) -> str:
    """Map a confirmed SEA outcome to the portfolio categories."""
    if exp_id is None or pd.isna(exp_id):
        return (
            "sin_expediente_en_ejecucion"
            if etapa == "Ejecución"
            else "sin_expediente_en_estudio"
        )
    if evento == "aprobado":
        return "aprobado"
    if evento == "en_tramite":
        return "en_evaluacion"
    if evento in ADVERSE_EVENTS:
        return "desistido_rechazado_o_no_calificado"
    return "otro"


def build_portfolio_status(
    cochilco: pd.DataFrame,
    confirmed: pd.DataFrame,
    sea_mining: pd.DataFrame,
    shared_expediente_exceptions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Join the 59-project Cochilco portfolio to confirmed SEA records."""
    if cochilco["project_id"].duplicated().any():
        raise ValueError("Cochilco project_id values must be unique")
    if confirmed["cochilco_id"].duplicated().any():
        raise ValueError("Confirmed matches must have one row per cochilco_id")
    unmatched_ids = set(confirmed["cochilco_id"]) - set(cochilco["project_id"])
    if unmatched_ids:
        raise ValueError(f"Unknown cochilco_id values in match review: {sorted(unmatched_ids)}")

    joined = cochilco.merge(
        confirmed,
        how="left",
        left_on="project_id",
        right_on="cochilco_id",
        validate="one_to_one",
    )
    if joined["criterio"].isna().any():
        missing = joined.loc[joined["criterio"].isna(), "project_id"].tolist()
        raise ValueError(f"Missing confirmed matches for Cochilco projects: {missing[:5]}")

    _validate_shared_expediente_assignments(confirmed, shared_expediente_exceptions)

    sea = sea_mining.loc[:, SEA_STATUS_COLUMNS]
    if sea["exp_id"].duplicated().any():
        raise ValueError("sea_mining exp_id values must be unique")
    result = joined.merge(
        sea,
        how="left",
        left_on="exp_id_confirmado",
        right_on="exp_id",
        validate="many_to_one",
    )
    missing_sea = result["exp_id_confirmado"].notna() & result["exp_id"].isna()
    if missing_sea.any():
        ids = result.loc[missing_sea, "exp_id_confirmado"].astype(int).tolist()
        raise ValueError(f"Confirmed exp_id not found in sea_mining: {ids}")
    etapas = result["etapa"] if "etapa" in result else [None] * len(result)
    overrides = (
        result["estado_ambiental_override"].map(_decision_text)
        if "estado_ambiental_override" in result
        else [""] * len(result)
    )
    result["estado_ambiental"] = [
        override or classify_environmental_status(evento, exp_id, etapa)
        for evento, exp_id, etapa, override in zip(
            result["evento"],
            result["exp_id_confirmado"],
            etapas,
            overrides,
            strict=True,
        )
    ]
    return result.drop(columns=["cochilco_id", "exp_id"])


def write_portfolio_status(
    review_path: Path = REVIEW_PATH,
    cochilco_path: Path = COCHILCO_PATH,
    sea_path: Path = SEA_PATH,
    confirmed_path: Path = CONFIRMED_MATCH_PATH,
    output_path: Path = PORTFOLIO_STATUS_PATH,
    checklist_path: Path | None = CHECKLIST_PATH,
    shared_exceptions_path: Path | None = SHARED_EXCEPTIONS_PATH,
) -> pd.DataFrame:
    """Read local inputs and write privacy-safe match and portfolio artifacts."""
    review = pd.read_csv(review_path, dtype={"match_confirmado": "string"}, keep_default_na=False)
    sea_mining = pd.read_parquet(sea_path)
    shared_exceptions = (
        pd.read_csv(shared_exceptions_path)
        if shared_exceptions_path is not None
        else pd.DataFrame(columns=["exp_id", "cochilco_id", "motivo"])
    )
    confirmed = build_confirmed_match_table(
        review, shared_expediente_exceptions=shared_exceptions
    )
    if checklist_path is not None:
        checklist = pd.read_csv(checklist_path, keep_default_na=False)
        confirmed = apply_checklist_decisions(confirmed, checklist, sea_mining)
    portfolio = build_portfolio_status(
        pd.read_parquet(cochilco_path),
        confirmed,
        sea_mining,
        shared_expediente_exceptions=shared_exceptions,
    )
    confirmed_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    confirmed.to_csv(confirmed_path, index=False)
    portfolio.to_parquet(output_path, index=False)
    return portfolio


def main() -> None:
    portfolio = write_portfolio_status()
    print(f"Wrote {len(portfolio)} Cochilco portfolio status rows")


if __name__ == "__main__":
    main()
