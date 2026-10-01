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
    "exp_id",
    "sea_nombre",
    "sea_empresa",
    "sea_estado",
    "sea_fecha_ingreso",
    "score",
    "match_confirmado",
]
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


def _score(left: str, right: str) -> float:
    try:
        from rapidfuzz import fuzz
    except ModuleNotFoundError as error:  # pragma: no cover - dependency installation issue
        raise RuntimeError("rapidfuzz is required to rank SEA candidates") from error
    return float(fuzz.token_set_ratio(left, right)) if left and right else 0.0


def _first_text(*values: object) -> str:
    for value in values:
        normalized = normalize_text(value)
        if normalized:
            return str(value)
    return ""


def rank_candidates(
    cochilco: pd.DataFrame, sea_mining: pd.DataFrame, top_n: int = 3
) -> pd.DataFrame:
    """Return the top SEA candidates per Cochilco project without assigning matches."""
    sea = sea_mining.loc[sea_mining["seco_nombre"].eq("Minería")].copy()
    sea["_region_key"] = sea["region"].map(_region_key)
    rows: list[dict[str, object]] = []
    for project in cochilco.to_dict("records"):
        candidates = sea
        if normalize_text(project["region"]) != "varias":
            candidates = sea.loc[sea["_region_key"].eq(_region_key(project["region"]))]
        project_name = normalize_text(project["nombre_del_proyecto"])
        company_name = normalize_text(project["empresa"])
        ranked: list[tuple[float, dict[str, object]]] = []
        for candidate in candidates.to_dict("records"):
            sea_company = _first_text(
                candidate.get("empresa_nombre"), candidate.get("titular_nombre")
            )
            company_score = max(
                _score(company_name, normalize_text(candidate.get("empresa_nombre"))),
                _score(company_name, normalize_text(candidate.get("titular_nombre"))),
            )
            score = max(
                _score(project_name, normalize_text(candidate["exp_nombre"])), company_score
            )
            ranked.append((score, candidate | {"_sea_company": sea_company}))
        ranked.sort(key=lambda item: (-item[0], str(item[1]["exp_id"])))
        for score, candidate in ranked[:top_n]:
            rows.append(
                {
                    "cochilco_id": project["project_id"],
                    "cochilco_nombre": project["nombre_del_proyecto"],
                    "cochilco_empresa": project["empresa"],
                    "exp_id": candidate["exp_id"],
                    "sea_nombre": candidate["exp_nombre"],
                    "sea_empresa": candidate["_sea_company"],
                    "sea_estado": candidate["estado"],
                    "sea_fecha_ingreso": candidate["fecha_ingreso"],
                    "score": round(score, 1),
                    "match_confirmado": pd.NA,
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
    print(f"Wrote {len(matches)} SEA match candidates")


if __name__ == "__main__":
    main()
