"""Attach reproducible SEA expediente evidence to the company-alias catalog."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cmip.config import INTERIM_DIR, PROCESSED_DIR, PROJECT_ROOT
from cmip.match import normalize_text

ALIASES_PATH = PROJECT_ROOT / "data" / "curated" / "company_aliases.csv"
COCHILCO_PATH = PROCESSED_DIR / "cochilco_projects.parquet"
SEA_PATH = INTERIM_DIR / "sea_mining.parquet"


def build_alias_evidence(
    aliases: pd.DataFrame,
    cochilco: pd.DataFrame,
    sea: pd.DataFrame,
) -> pd.DataFrame:
    """Return aliases with up to three locally supported SEA expediente IDs."""
    result = aliases.copy()
    result["fuente"] = result["fuente"].replace(
        {"revision_J_2026-10": "revision_autor_2026-10"}
    )
    result["momento"] = result["fuente"].map(
        {
            "catalogo_inicial": "antes_de_resultados",
            "revision_autor_2026-10": "despues_de_resultados",
        }
    )
    if result["momento"].isna().any():
        invalid = sorted(result.loc[result["momento"].isna(), "fuente"].unique())
        raise ValueError(f"Fuentes de alias sin momento definido: {invalid}")

    sea_work = sea.copy()
    sea_work["_holder"] = sea_work["titular_nombre"].fillna("").map(normalize_text)
    sea_work["_company"] = sea_work["empresa_nombre"].fillna("").map(normalize_text)
    sea_work["_region"] = sea_work["region"].fillna("").map(normalize_text)
    sea_work["_name"] = sea_work["exp_nombre"].fillna("").map(normalize_text)

    evidence: list[str] = []
    for row in result.itertuples(index=False):
        company_projects = cochilco.loc[
            cochilco["empresa"].map(normalize_text).eq(normalize_text(row.cochilco_empresa))
        ]
        regions = set(company_projects["region"].dropna().map(normalize_text)) - {""}
        mines = set(company_projects["mina"].dropna().map(normalize_text)) - {"", "n a", "na"}
        alias = normalize_text(row.alias)
        holder_match = sea_work["_holder"].str.contains(alias, regex=False) | sea_work[
            "_company"
        ].str.contains(alias, regex=False)
        place_match = sea_work["_region"].isin(regions)
        if mines:
            place_match |= sea_work["_name"].map(
                lambda name, _mines=frozenset(mines): any(mine in name for mine in _mines)
            )
        candidates = sea_work.loc[holder_match & place_match].sort_values(
            ["fecha_ingreso", "exp_id"], ascending=[False, False]
        )
        ids = candidates["exp_id"].drop_duplicates().astype(int).head(3)
        evidence.append(";".join(ids.astype(str)))

    result["evidencia"] = evidence
    return result[
        ["cochilco_empresa", "alias", "estado", "fuente", "evidencia", "momento"]
    ]


def main(
    aliases_path: Path = ALIASES_PATH,
    cochilco_path: Path = COCHILCO_PATH,
    sea_path: Path = SEA_PATH,
) -> None:
    aliases = pd.read_csv(aliases_path, keep_default_na=False)
    enriched = build_alias_evidence(
        aliases,
        pd.read_parquet(cochilco_path),
        pd.read_parquet(sea_path),
    )
    aliases_path.write_text(enriched.to_csv(index=False), encoding="utf-8")
    print(f"Alias con evidencia: {enriched['evidencia'].ne('').sum()}/{len(enriched)}")


if __name__ == "__main__":
    main()
