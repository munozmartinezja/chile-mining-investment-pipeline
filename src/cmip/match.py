"""Produce a human-review queue of Cochilco-to-SEA candidate matches."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

from cmip.config import PROCESSED_DIR, PROJECT_ROOT

MATCH_COLUMNS = [
    "cochilco_id",
    "cochilco_nombre",
    "cochilco_empresa",
    "cochilco_mina",
    "exp_id",
    "sea_nombre",
    "sea_empresa",
    "sea_estado",
    "sea_fecha_ingreso",
    "score",
    "empresa_no_coincide",
    "match_tipo",
    "match_confirmado",
    "criterio",
    "historial",
]
ALIASES_PATH = PROJECT_ROOT / "data" / "curated" / "company_aliases.csv"
ALIAS_STATES = {"confirmado", "rechazado", "pendiente"}
ABBREVIATIONS = {
    "cia": "compania",
    "comp": "compania",
    "min": "minera",
    "soc": "sociedad",
}
REGION_ALIASES = {
    "arica y parinacota": "xv",
    "tarapaca": "i",
    "antofagasta": "ii",
    "atacama": "iii",
    "coquimbo": "iv",
    "valparaiso": "v",
    "ohiggins": "vi",
    "libertador general bernardo ohiggins": "vi",
    "maule": "vii",
    "biobio": "viii",
    "araucania": "ix",
    "los lagos": "x",
    "aysen": "xi",
    "magallanes": "xii",
    "metropolitana": "rm",
    "metropolitana de santiago": "rm",
    "los rios": "xiv",
    "nuble": "xvi",
}
GENERIC_MINING_WORDS = {
    "proyecto",
    "continuidad",
    "operacional",
    "minera",
    "minero",
    "expansion",
    "ampliacion",
    "actualizacion",
    "optimizacion",
    "modificacion",
    "nueva",
    "nuevo",
    "etapa",
    "planta",
    "mina",
    "desarrollo",
}
ROMAN_NUMERALS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}


def normalize_text(value: object) -> str:
    """Normalize names for conservative fuzzy comparison."""
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value).casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    tokens = re.findall(r"[a-z0-9]+", text)
    collapsed: list[str] = []
    index = 0
    while index < len(tokens):
        if tokens[index : index + 2] == ["s", "a"]:
            collapsed.append("sa")
            index += 2
        else:
            collapsed.append(tokens[index])
            index += 1
    return " ".join(ABBREVIATIONS.get(token, token) for token in collapsed)


def _region_key(value: object) -> str:
    normalized = normalize_text(value)
    return REGION_ALIASES.get(normalized, normalized)


def _token_sort_ratio(left: str, right: str) -> float:
    try:
        from rapidfuzz import fuzz
    except ModuleNotFoundError as error:  # pragma: no cover - dependency installation issue
        raise RuntimeError("rapidfuzz is required to rank SEA candidates") from error
    return float(fuzz.token_sort_ratio(left, right)) if left and right else 0.0


def strip_generic_mining_words(value: object) -> str:
    """Normalize a name, retaining a phase marker while removing generic tokens."""
    tokens = normalize_text(value).split()
    distinctive: list[str] = []
    for token in tokens:
        is_number = token in ROMAN_NUMERALS or re.fullmatch(r"\d+a?", token) is not None
        if token in GENERIC_MINING_WORDS:
            continue
        if is_number and (not distinctive or distinctive[-1] != "fase"):
            continue
        distinctive.append(token)
    return " ".join(distinctive)


def project_name_score(left: object, right: object) -> float:
    """Score only the distinctive tokens in two project names."""
    score = _token_sort_ratio(strip_generic_mining_words(left), strip_generic_mining_words(right))
    left_phase = re.search(r"\bfase\s+([ivx]+|\d+)\b", normalize_text(left))
    right_phase = re.search(r"\bfase\s+([ivx]+|\d+)\b", normalize_text(right))
    if left_phase and (not right_phase or left_phase.group(1) != right_phase.group(1)):
        score = min(score, 90.0)
    return score


def _first_text(*values: object) -> str:
    for value in values:
        normalized = normalize_text(value)
        if normalized:
            return str(value)
    return ""


def company_matches_candidate(
    project: dict[str, object],
    candidate: dict[str, object],
    aliases: pd.DataFrame | None = None,
) -> bool:
    """Return whether a SEA company/holder contains a confirmed project identifier."""
    identifiers = {
        normalize_text(project.get("empresa")),
        normalize_text(project.get("mina")),
    }
    if aliases is not None and not aliases.empty:
        required = {"cochilco_empresa", "alias", "estado"}
        missing = required.difference(aliases.columns)
        if missing:
            raise ValueError(f"Missing company-alias columns: {sorted(missing)}")
        company_key = normalize_text(project.get("empresa"))
        confirmed = aliases.loc[
            aliases["cochilco_empresa"].map(normalize_text).eq(company_key)
            & aliases["estado"].eq("confirmado"),
            "alias",
        ]
        identifiers.update(confirmed.map(normalize_text))
    identifiers.difference_update({"", "n a", "na"})
    sea_names = [
        normalize_text(candidate.get("empresa_nombre")),
        normalize_text(candidate.get("titular_nombre")),
    ]
    return any(identifier in sea_name for identifier in identifiers for sea_name in sea_names)


def _validate_aliases(aliases: pd.DataFrame) -> None:
    """Validate the alias catalog used by matching and notebook decisions."""
    required = {"cochilco_empresa", "alias", "estado"}
    missing = required.difference(aliases.columns)
    if missing:
        raise ValueError(f"Missing company-alias columns: {sorted(missing)}")
    invalid = set(aliases["estado"]) - ALIAS_STATES
    if invalid:
        raise ValueError(f"Invalid alias states in CSV: {sorted(invalid)}")


def apply_alias_decisions(
    aliases: pd.DataFrame, decisions: dict[tuple[str, str], str]
) -> pd.DataFrame:
    """Apply J's status decisions to known aliases."""
    _validate_aliases(aliases)
    invalid_decisions = set(decisions.values()) - ALIAS_STATES
    if invalid_decisions:
        raise ValueError(f"Invalid alias state: {sorted(invalid_decisions)}")
    known = set(zip(aliases["cochilco_empresa"], aliases["alias"], strict=True))
    unknown = set(decisions) - known
    if unknown:
        raise ValueError(f"Unknown alias: {sorted(unknown)}")
    result = aliases.copy()
    for (company, alias), state in decisions.items():
        target = result["cochilco_empresa"].eq(company) & result["alias"].eq(alias)
        result.loc[target, "estado"] = state
    return result


def _match_type(ranked: list[tuple[float, dict[str, object]]]) -> str:
    if not ranked or ranked[0][0] < 60:
        return "sin_candidato"
    best = ranked[0][0]
    second_best = ranked[1][0] if len(ranked) > 1 else 0.0
    if best >= 85 and best - second_best >= 10:
        return "alto"
    return "revisar"


def _empty_candidate_row(project: dict[str, object]) -> dict[str, object]:
    return {
        "cochilco_id": project["project_id"],
        "cochilco_nombre": project["nombre_del_proyecto"],
        "cochilco_empresa": project["empresa"],
        "cochilco_mina": project.get("mina", pd.NA),
        "exp_id": pd.NA,
        "sea_nombre": pd.NA,
        "sea_empresa": pd.NA,
        "sea_estado": pd.NA,
        "sea_fecha_ingreso": pd.NaT,
        "score": 0.0,
        "empresa_no_coincide": True,
        "match_tipo": "sin_candidato",
        "match_confirmado": pd.NA,
        "criterio": pd.NA,
        "historial": pd.NA,
    }


def rank_candidates(
    cochilco: pd.DataFrame,
    sea_mining: pd.DataFrame,
    top_n: int = 5,
    aliases: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return the top SEA candidates per Cochilco project without assigning matches."""
    if aliases is None:
        aliases = pd.read_csv(ALIASES_PATH) if ALIASES_PATH.exists() else pd.DataFrame()
    if not aliases.empty:
        _validate_aliases(aliases)
    sea = sea_mining.loc[sea_mining["seco_nombre"].eq("Minería")].copy()
    sea["_region_key"] = sea["region"].map(_region_key)
    rows: list[dict[str, object]] = []
    for project in cochilco.to_dict("records"):
        candidates = sea
        if normalize_text(project["region"]) != "varias":
            candidates = sea.loc[sea["_region_key"].eq(_region_key(project["region"]))]
        candidate_records = candidates.to_dict("records")
        ranked: list[tuple[float, dict[str, object]]] = []
        for candidate in candidate_records:
            sea_company = _first_text(
                candidate.get("empresa_nombre"), candidate.get("titular_nombre")
            )
            score = project_name_score(
                project["nombre_del_proyecto"], candidate["exp_nombre"]
            )
            company_match = company_matches_candidate(project, candidate, aliases)
            ranked.append(
                (
                    score,
                    candidate
                    | {
                        "_sea_company": sea_company,
                        "_empresa_no_coincide": not company_match,
                    },
                )
            )
        ranked.sort(key=lambda item: (-item[0], str(item[1]["exp_id"])))
        match_type = _match_type(ranked)
        # A project with no candidates in its region previously emitted no row, making a
        # 59-project Cochilco portfolio appear to contain only 58 projects in the review.
        if not ranked:
            rows.append(_empty_candidate_row(project))
            continue
        for score, candidate in ranked[:top_n]:
            if pd.isna(candidate["fecha_ingreso"]):
                raise ValueError(
                    f"SEA candidate {candidate['exp_id']} has no fecha_ingreso"
                )
            rows.append(
                {
                    "cochilco_id": project["project_id"],
                    "cochilco_nombre": project["nombre_del_proyecto"],
                    "cochilco_empresa": project["empresa"],
                    "cochilco_mina": project.get("mina", pd.NA),
                    "exp_id": candidate["exp_id"],
                    "sea_nombre": candidate["exp_nombre"],
                    "sea_empresa": candidate["_sea_company"],
                    "sea_estado": candidate["estado"],
                    "sea_fecha_ingreso": candidate["fecha_ingreso"],
                    "score": round(score, 1),
                    "empresa_no_coincide": candidate["_empresa_no_coincide"],
                    "match_tipo": match_type,
                    "match_confirmado": pd.NA,
                    "criterio": pd.NA,
                    "historial": pd.NA,
                }
            )
    return pd.DataFrame(rows, columns=MATCH_COLUMNS)


def build_match_review(
    cochilco_path: Path = PROCESSED_DIR / "cochilco_projects.parquet",
    sea_path: Path = PROJECT_ROOT / "data" / "interim" / "sea_mining.parquet",
    output_path: Path = PROJECT_ROOT / "docs" / "match_review.csv",
) -> pd.DataFrame:
    """Read pipeline outputs and write the candidate review CSV."""
    matches = rank_candidates(pd.read_parquet(cochilco_path), pd.read_parquet(sea_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    matches.to_csv(output_path, index=False)
    return matches


def main() -> None:
    matches = build_match_review()
    distribution = (
        matches.drop_duplicates("cochilco_id")["match_tipo"]
        .value_counts()
        .reindex(["alto", "revisar", "sin_candidato"], fill_value=0)
    )
    print(
        "match_tipo distribution: "
        f"alto={distribution['alto']}, revisar={distribution['revisar']}, "
        f"sin_candidato={distribution['sin_candidato']}"
    )
    print(f"Wrote {len(matches)} SEA match candidates")


if __name__ == "__main__":
    main()
