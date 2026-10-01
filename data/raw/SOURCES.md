# Raw data sources

## Cochilco Annex C — December 2025

- Publisher: Comisión Chilena del Cobre (Cochilco)
- Publication: _Cartera de Proyectos de Inversión Minera en Chile,
  Período 2025–2034_, Annex C
- Origin URL: https://www.cochilco.cl/web/download/1004/2025/15204/anexo-c-tablas-informe-cartera-de-proyectos-de-inversion-minera-en-chile-periodo-2025-2034.xlsx
- Download date: 2026-09-30 (repository file timestamp)
- Primary source: the `.xlsx` workbook below, read with `pandas` and `openpyxl`
- Fallback: the semicolon-delimited UTF-8 CSV exports below

| File                                                                                              | SHA-256                                                            |
| ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `Anexo-C-Tablas-Informe-Cartera-de-Proyectos-de-Inversion-Minera-en-Chile-Periodo-2025-2034.xlsx` | `d94685a389e9f17430999d9f3a101984926a3b4a5aa9a178b2626470f21b54aa` |
| `Tabla 1-Tabla 1.csv`                                                                             | `456bfdbf155be0f4b306a6e9d1828da6d44497bae077f1db5136693c2e1d294f` |
| `Tabla 2 -3-Tabla 1.csv`                                                                          | `25b04bd936b5770851839cc774b9e5a27a45e7e1044912a1472f87022f1186b9` |
| `Tabla 4-5-6-7-Tabla 1.csv`                                                                       | `5bf6ec5d6981eb97b8d087ad8acf31b14a9462748e3b5f0ab508e322e6b1f116` |
| `Tabla 8-Tabla 1.csv`                                                                             | `7d6b0a610134cdfc4745d86a7a3f2ac456506399029e4e7cb613f1814e672a1c` |
| `Tabla 9-Tabla 1.csv`                                                                             | `3dbabbfd4ea097f35bc8a8f5a4b667c36ba3728db8f90801b3c647b159e129e4` |
| `Tabla 10-11-12-13-Tabla 1.csv`                                                                   | `5f128ec8e1933adccddc58c49f9949f0ee8244e5587daec339b56f6146bf5dd1` |
| `Índice-Tabla 1.csv`                                                                              | `7112e3656ad586cad295123ba5a2976733641e04831377b4f15afc8b0183f05e` |

Raw files are immutable pipeline inputs. Generated outputs belong under
`data/interim/`, `data/processed/`, or `data/cmip.duckdb`.

## Servicio de Evaluación Ambiental (SEA) — September 2026

- Publisher: Servicio de Evaluación Ambiental (SEA)
- Download date: 2026-09-30
- Projects source page:
  https://www.sea.gob.cl/informacion-de-proyectos-ingresados-al-seia
- Processing-times source page:
  https://www.sea.gob.cl/informacion-de-plazos-de-tramitacion-en-el-seia
- Tableau Public projects workbook:
  https://public.tableau.com/workbooks/ProyectosIngresados2026
- Tableau Public projects views:
  https://public.tableau.com/workbooks/ProyectosIngresados2026/INGRESO and
  https://public.tableau.com/workbooks/ProyectosIngresados2026/ComparacindePeriodos
- Tableau Public processing-times workbook:
  https://public.tableau.com/workbooks/PlazosEvaluacin
- Tableau Public processing-times view:
  https://public.tableau.com/workbooks/PlazosEvaluacin/Dashboard

| File | SHA-256 |
| --- | --- |
| `sea/sea_proyectos_ingresados.twbx` | `f2be4f485926e230ad7ddd0fb68745d05d544f6fe0afcb17807a76232850a0f6` |
| `sea/sea_plazos_tramitacion.twbx` | `ec80a746bdda54da8d7763aeb8401067a947983ddf977c24375cd888051f2246` |

The pipeline reads the non-geometry `Data/TableauTemp/*.tmp` Hyper extract whose catalog
contains `"Extract"."Extract"`. Packaged `V3.hyper` files contain geometry only and are
not used.
