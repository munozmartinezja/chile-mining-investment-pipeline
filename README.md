# Chile Mining Investment Pipeline

## Idiomas / Languages

- [Español](#español)
- [English](#english)

---

## Español

CMIP convierte la cartera de inversión minera de Cochilco de diciembre de 2025
en datos reproducibles para analizar proyectos previstos para 2025–2034 y su
tramitación ambiental en el SEA.

### Hallazgos

- El tiempo mediano KM hasta aprobación entre proyectos que siguen en juego es
  **7,7 meses para DIA** (IC 95%: 7,2–8,1) y **28,8 meses para EIA**
  (23,7–32,9).
- La incidencia acumulada de aprobación a 24 meses —la cifra principal con
  riesgos competitivos— es **66,5% para DIA** y **31,1% para EIA**.
- A 24 meses, KM entrega 96,2% para DIA y 41,2% para EIA: sobreestima la
  incidencia de aprobación en **29,7 y 10,1 puntos porcentuales**, respectivamente,
  porque censura los desenlaces competidores.
- El desistimiento o abandono a 24 meses acumula **22,5% en DIA** y **19,2% en
  EIA**; rechazo y término anticipado suman 9,7% y 8,0%, respectivamente.

Las tablas, supuestos y límites están en
[`docs/survival_results.md`](docs/survival_results.md).

### Fuentes

La fuente de cartera es la Comisión Chilena del Cobre (Cochilco), *Cartera de
Proyectos de Inversión Minera en Chile 2025–2034*, Anexo C, diciembre de 2025.
Los expedientes ambientales provienen del Servicio de Evaluación Ambiental
(SEA), con corte al 30-09-2026. Las URL, nombres de archivos y sumas de
verificación están en [`data/raw/SOURCES.md`](data/raw/SOURCES.md).

### Notebooks

- [`notebooks/00_data_checks.ipynb`](notebooks/00_data_checks.ipynb): cuadratura
  de 104.549,2 MMUS$, conteos SEA, privacidad y completitud de fechas.
- [`notebooks/01_match_review.ipynb`](notebooks/01_match_review.ipynb): reglas
  automáticas, top-3 de casos dudosos, decisiones de J y escritura de
  `match_confirmado` con `criterio` (`regla_auto` o `decision_J`).

### Reproducir

Se requieren Python 3.12 y [`uv`](https://docs.astral.sh/uv/). Descargue los dos
libros SEA `.twbx` indicados en `data/raw/SOURCES.md` y guárdelos como:

- `data/raw/sea/sea_proyectos_ingresados.twbx`
- `data/raw/sea/sea_plazos_tramitacion.twbx`

Luego ejecute:

```bash
make setup
make data
make survival
```

`make survival` usa solo datos SEA y genera el análisis de supervivencia y las
figuras 1, 2 y 4. No depende del cruce Cochilco–SEA.

Abra `notebooks/01_match_review.ipynb`, complete la celda `DECISIONES_J` y
ejecute todo el notebook. Antes de guardar o versionar, limpie todos los outputs
del notebook: pueden contener nombres del archivo local y `make test` exige que
los `.ipynb` versionados no almacenen outputs. Cuando existan 59 decisiones,
ejecute:

```bash
make portfolio
```

`make portfolio` genera el estado ambiental de la cartera y la figura 3; es el
único componente que depende de las 59 decisiones. `make analysis` ejecuta
serialmente `survival` y luego `portfolio`: si faltan decisiones, conserva la
salida SEA y retorna error al llegar al componente de cartera.

```bash
make analysis
make test
make lint
```

`docs/match_review.csv` permanece local porque contiene nombres. El único cruce
versionado es `data/curated/cochilco_seia_match.csv`, con las columnas
`cochilco_id`, `exp_id_confirmado` y `criterio`.

Los `.twbx`, Parquet intermedios/procesados y bases DuckDB son artefactos
locales. Las pruebas de integración SEA se omiten en CI cuando faltan esos datos;
la lógica de transformación y los estimadores se cubren con datos sintéticos.

### Licencia

El código se distribuye bajo licencia MIT. Los datos fuente conservan las
condiciones de sus respectivos publicadores.

---

## English

CMIP turns Cochilco's December 2025 mining-investment portfolio into
reproducible data for analyzing projects planned for 2025–2034 and their SEA
environmental-review outcomes.

### Findings

- Median KM time to approval among projects that remain in play is **7.7 months
  for DIA** (95% CI: 7.2–8.1) and **28.8 months for EIA** (23.7–32.9).
- The 24-month cumulative incidence of approval—the principal competing-risk
  estimate—is **66.5% for DIA** and **31.1% for EIA**.
- At 24 months, KM reports 96.2% for DIA and 41.2% for EIA, overestimating
  approval incidence by **29.7 and 10.1 percentage points**, respectively,
  because competing outcomes are censored.
- The 24-month cumulative incidence of withdrawal or abandonment is **22.5% for
  DIA** and **19.2% for EIA**; rejection plus early termination total 9.7% and
  8.0%, respectively.

Tables, assumptions, and limitations are documented in
[`docs/survival_results.md`](docs/survival_results.md).

### Sources

The portfolio source is the Chilean Copper Commission (Cochilco), *Mining
Investment Project Portfolio in Chile 2025–2034*, Annex C, December 2025.
Environmental cases come from Chile's Environmental Assessment Service (SEA),
cut off at 2026-09-30. URLs, file names, and checksums are recorded in
[`data/raw/SOURCES.md`](data/raw/SOURCES.md).

### Notebooks

- [`notebooks/00_data_checks.ipynb`](notebooks/00_data_checks.ipynb): validates
  the USD 104,549.2 million total, SEA counts, privacy, and date completeness.
- [`notebooks/01_match_review.ipynb`](notebooks/01_match_review.ipynb): applies
  automatic rules, shows the top three candidates for uncertain cases, records
  J's decisions, and writes `match_confirmado` plus `criterio`.

### Reproduce

Python 3.12 and [`uv`](https://docs.astral.sh/uv/) are required. Download the two
SEA `.twbx` workbooks listed in `data/raw/SOURCES.md` and save them as:

- `data/raw/sea/sea_proyectos_ingresados.twbx`
- `data/raw/sea/sea_plazos_tramitacion.twbx`

Then run:

```bash
make setup
make data
make survival
```

`make survival` uses SEA data only and produces the survival analysis plus
figures 1, 2, and 4. It does not depend on the Cochilco–SEA match.

Open `notebooks/01_match_review.ipynb`, complete the `DECISIONES_J` cell, and run
the notebook. Clear all notebook outputs before saving or committing: they may
contain names from the local file, and `make test` requires tracked notebooks to
store no outputs. Once all 59 decisions exist, run:

```bash
make portfolio
```

`make portfolio` produces the portfolio environmental status and figure 3; it
is the only component that depends on all 59 decisions. `make analysis` runs
`survival` and then `portfolio` serially: if decisions are missing, it preserves
the SEA outputs and returns an error when it reaches the portfolio component.

```bash
make analysis
make test
make lint
```

`docs/match_review.csv` stays local because it contains names. The only
versioned crosswalk is `data/curated/cochilco_seia_match.csv`, containing
`cochilco_id`, `exp_id_confirmado`, and `criterio`.

The `.twbx` files, intermediate/processed Parquet files, and DuckDB databases
are local artifacts. SEA integration tests are skipped in CI when these local
data are unavailable; synthetic fixtures cover transformation and estimator
logic.

### License

The code is available under the MIT License. Source data remain subject to
their publishers' terms.
