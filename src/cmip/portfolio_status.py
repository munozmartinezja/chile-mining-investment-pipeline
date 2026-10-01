"""Build the manually confirmed Cochilco-to-SEA portfolio status."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cmip.config import PROCESSED_DIR, PROJECT_ROOT
from cmip.match import normalize_text

CURATED_DIR = PROJECT_ROOT / "data" / "curated"
REVIEW_PATH = PROJECT_ROOT / "docs" / "match_review.csv"
COCHILCO_PATH = PROCESSED_DIR / "cochilco_projects.parquet"
SEA_PATH = PROJECT_ROOT / "data" / "interim" / "sea_mining.parquet"
CONFIRMED_MATCH_PATH = CURATED_DIR / "cochilco_seia_match.csv"
PORTFOLIO_STATUS_PATH = PROCESSED_DIR / "cochilco_seia.parquet"

MATCH_OUTPUT_COLUMNS = ["cochilco_id", "exp_id_confirmado", "criterio", "historial"]
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
}


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
        high["_normalized_name"] = high["sea_nombre"].map(normalize_text)
        best_name = normalize_text(best.get("sea_nombre"))
        repeated = high.loc[high["_normalized_name"].eq(best_name)].copy()
        if len(repeated) >= 2:
            repeated["_date"] = pd.to_datetime(
                repeated["sea_fecha_ingreso"], errors="raise"
            )
            repeated = repeated.sort_values(
                ["_date", "exp_id"], ascending=[False, False]
            )
            selected = repeated.iloc[0]
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


def build_confirmed_match_table(review: pd.DataFrame) -> pd.DataFrame:
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
    return result


def classify_environmental_status(evento: object, exp_id: object) -> str:
    """Map a confirmed SEA outcome to the five portfolio categories."""
    if exp_id is None or pd.isna(exp_id):
        return "sin_ingreso_seia"
    if evento == "aprobado":
        return "aprobado"
    if evento == "en_tramite":
        return "en_evaluacion"
    if evento in ADVERSE_EVENTS:
        return "desistido_o_rechazado"
    return "otro"


def build_portfolio_status(
    cochilco: pd.DataFrame, confirmed: pd.DataFrame, sea_mining: pd.DataFrame
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

    matched = joined.loc[joined["exp_id_confirmado"].notna()].copy()
    duplicated = matched["exp_id_confirmado"].duplicated(keep=False)
    if duplicated.any() and not matched.loc[duplicated, "nota_agregacion"].fillna(False).all():
        ids = matched.loc[duplicated, "exp_id_confirmado"].astype(int).unique().tolist()
        raise ValueError(f"Duplicate confirmed exp_id without documented aggregation: {ids}")

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
    result["estado_ambiental"] = [
        classify_environmental_status(evento, exp_id)
        for evento, exp_id in zip(result["evento"], result["exp_id_confirmado"], strict=True)
    ]
    return result.drop(columns=["cochilco_id", "exp_id"])


def write_portfolio_status(
    review_path: Path = REVIEW_PATH,
    cochilco_path: Path = COCHILCO_PATH,
    sea_path: Path = SEA_PATH,
    confirmed_path: Path = CONFIRMED_MATCH_PATH,
    output_path: Path = PORTFOLIO_STATUS_PATH,
) -> pd.DataFrame:
    """Read local inputs and write privacy-safe match and portfolio artifacts."""
    review = pd.read_csv(review_path, dtype={"match_confirmado": "string"}, keep_default_na=False)
    confirmed = build_confirmed_match_table(review)
    portfolio = build_portfolio_status(
        pd.read_parquet(cochilco_path), confirmed, pd.read_parquet(sea_path)
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
