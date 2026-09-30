# Chile Mining Investment Pipeline

CMIP turns Cochilco's December 2025 Annex C portfolio into an analysis-ready
dataset for answering which Chilean mining projects are expected in 2025–2034,
where and when they are planned, and which projects merit later environmental
review-delay analysis. This delivery covers the Cochilco portfolio only.

## Source

The source is the Chilean Copper Commission (Cochilco), *Cartera de Proyectos de
Inversión Minera en Chile 2025–2034*, Annex C, December 2025. The original Excel
workbook is the primary input; semicolon-delimited CSV exports are retained as a
fallback. File-level provenance and checksums are recorded in
[`data/raw/SOURCES.md`](data/raw/SOURCES.md).

## Reproduce

Python 3.12 and [`uv`](https://docs.astral.sh/uv/) are required.

```bash
make setup
make data
make test
make lint
```

Generated interim Parquet files, the processed project Parquet file, and
`data/cmip.duckdb` are local build artifacts and are not committed.

## License

The code in this repository is available under the MIT License. Source data
remains subject to Cochilco's terms and is not relicensed by this project.

