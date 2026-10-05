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
    "inversion_ratio",
    "ranking_match",
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
SECONDARY_FILING_PREFIXES = {
    "actualizacion",
    "modificacion",
    "adecuacion",
    "optimizacion",
    "ajustes",
}
INVESTMENT_RATIO_MIN = 0.8
INVESTMENT_RATIO_MAX = 1.25
INVESTMENT_RATIO_BONUS = 6.0


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


def _positive_number(value: object) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number) or float(number) <= 0:
        return None
    return float(number)


def _investment_ratio(
    project: dict[str, object], candidate: dict[str, object]
) -> float | None:
    cochilco_investment = _positive_number(project.get("inversion_musd"))
    sea_investment = _positive_number(candidate.get("inversion_musd"))
    if cochilco_investment is None or sea_investment is None:
        return None
    return sea_investment / cochilco_investment


def _semantic_name_match(
    project: dict[str, object], candidate: dict[str, object]
) -> tuple[bool, bool]:
    """Detect a project-name phrase or mine name in the SEA expediente title."""
    sea_name = normalize_text(candidate.get("exp_nombre"))
    project_phrase = strip_generic_mining_words(project.get("nombre_del_proyecto"))
    mine_phrase = strip_generic_mining_words(project.get("mina"))
    name_match = len(project_phrase) >= 4 and project_phrase in strip_generic_mining_words(
        candidate.get("exp_nombre")
    )
    mine_match = len(mine_phrase) >= 4 and mine_phrase in sea_name
    return name_match, mine_match


def _is_secondary_filing(candidate: dict[str, object]) -> bool:
    words = normalize_text(candidate.get("exp_nombre")).split()
    starts_with_secondary_term = bool(words) and words[0] in SECONDARY_FILING_PREFIXES
    investment = pd.to_numeric(candidate.get("inversion_musd"), errors="coerce")
    is_small = pd.notna(investment) and float(investment) <= 1.0
    return starts_with_secondary_term or is_small


def _is_viable_principal(candidate: dict[str, object]) -> bool:
    state = normalize_text(candidate.get("estado"))
    excluded_states = ("no admitido", "desistido", "rechazado", "termino anticipado")
    return not any(term in state for term in excluded_states)


def _prefer_principal_expediente(
    ranked: list[tuple[float, dict[str, object]]],
) -> list[tuple[float, dict[str, object]]]:
    """Promote the scope-authorizing filing over a comparable secondary filing."""
    if not ranked or not ranked[0][1]["_secondary_filing"]:
        return ranked
    best_score, best = ranked[0]
    for index, (score, candidate) in enumerate(ranked[1:], start=1):
        same_holder = normalize_text(candidate["_sea_company"]) == normalize_text(
            best["_sea_company"]
        )
        same_mine = candidate["_mine_match"] and best["_mine_match"]
        if (
            score >= best_score - 5
            and same_holder
            and same_mine
            and not candidate["_secondary_filing"]
            and candidate["_principal_viable"]
        ):
            return [ranked[index], *ranked[:index], *ranked[index + 1 :]]
    return ranked


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
        "inversion_ratio": pd.NA,
        "ranking_match": pd.NA,
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
            candidates = sea.loc[
                sea["_region_key"].eq(_region_key(project["region"]))
                | sea["_region_key"].eq("interregional")
            ]
        candidate_records = candidates.to_dict("records")
        ranked: list[tuple[float, dict[str, object]]] = []
        for candidate in candidate_records:
            sea_company = _first_text(
                candidate.get("empresa_nombre"), candidate.get("titular_nombre")
            )
            raw_score = project_name_score(
                project["nombre_del_proyecto"], candidate["exp_nombre"]
            )
            name_match, mine_match = _semantic_name_match(project, candidate)
            company_match = company_matches_candidate(project, candidate, aliases)
            score = raw_score
            if name_match and company_match:
                score = max(score, 95.0)
            elif mine_match and company_match:
                score = max(score, 90.0)
            ratio = _investment_ratio(project, candidate)
            if (
                ratio is not None
                and INVESTMENT_RATIO_MIN <= ratio <= INVESTMENT_RATIO_MAX
                and (name_match or mine_match)
                and company_match
            ):
                score = min(100.0, score + INVESTMENT_RATIO_BONUS)
            ranked.append(
                (
                    score,
                    candidate
                    | {
                        "_sea_company": sea_company,
                        "_empresa_no_coincide": not company_match,
                        "_inversion_ratio": ratio,
                        "_ratio_distance": (
                            abs(ratio - 1.0) if ratio is not None else float("inf")
                        ),
                        "_mine_match": mine_match,
                        "_secondary_filing": _is_secondary_filing(candidate),
                        "_principal_viable": _is_viable_principal(candidate),
                    },
                )
            )
        ranked.sort(
            key=lambda item: (
                -item[0],
                not item[1]["_principal_viable"],
                item[1]["_ratio_distance"],
                str(item[1]["exp_id"]),
            )
        )
        ranked = _prefer_principal_expediente(ranked)
        match_type = _match_type(ranked)
        # A project with no candidates in its region previously emitted no row, making a
        # 59-project Cochilco portfolio appear to contain only 58 projects in the review.
        if not ranked:
            rows.append(_empty_candidate_row(project))
            continue
        for candidate_rank, (score, candidate) in enumerate(ranked[:top_n], start=1):
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
                    "inversion_ratio": (
                        round(candidate["_inversion_ratio"], 4)
                        if candidate["_inversion_ratio"] is not None
                        else pd.NA
                    ),
                    "ranking_match": candidate_rank,
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
