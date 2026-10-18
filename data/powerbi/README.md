# Power BI exports / Exportaciones para Power BI

## Español

Ejecute `make powerbi` desde la raíz del repositorio para generar los ocho
archivos Parquet de esta carpeta. Los `.parquet` son artefactos locales y están
ignorados por Git; este README es el único archivo versionado del directorio.

Cargue cada archivo en Power BI Desktop con **Obtener datos → Parquet** y
conserve el nombre del archivo como nombre de tabla.

| Archivo | Contenido |
|---|---|
| `fact_cartera.parquet` | Proyectos Cochilco con estado SEIA y monto de inversión |
| `fact_expedientes.parquet` | Expedientes SEA de la población minera con fechas y desenlaces |
| `agg_km.parquet` | Curvas Kaplan–Meier por instrumento y meses |
| `agg_cif.parquet` | Incidencia acumulada Aalen–Johansen por instrumento, desenlace y meses |
| `agg_tendencia.parquet` | Aprobación a 24 meses por cohorte de ingreso |
| `agg_brecha_km_aj.parquet` | Brecha KM–AJ a 24 meses por instrumento |
| `agg_waffle_24m.parquet` | Desenlaces a 24 meses para gráfico de composición |
| `kpi_validados.parquet` | Registro de cifras verificadas usado como fuente de verdad del dashboard |

## English

Run `make powerbi` from the repository root to generate the eight Parquet files
in this directory. The `.parquet` files are local artifacts ignored by Git;
this README is the only versioned file in the directory.

Load every file in Power BI Desktop with **Get data → Parquet** and keep the
file name as the table name.

| File | Contents |
|---|---|
| `fact_cartera.parquet` | Cochilco projects with SEIA status and investment amount |
| `fact_expedientes.parquet` | SEA filings from the mining population with dates and outcomes |
| `agg_km.parquet` | Kaplan–Meier curves by instrument and month |
| `agg_cif.parquet` | Aalen–Johansen cumulative incidence by instrument, outcome, and month |
| `agg_tendencia.parquet` | 24-month approval by entry cohort |
| `agg_brecha_km_aj.parquet` | KM–AJ gap at 24 months by instrument |
| `agg_waffle_24m.parquet` | 24-month outcomes for composition chart |
| `kpi_validados.parquet` | Verified-figures register used as the dashboard source of truth |
