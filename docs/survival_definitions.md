# SEA survival definitions

The unit of analysis is one SEA environmental-assessment expediente, identified by the
unique `exp_id`. The files were downloaded on **2026-09-30**, but the latest observed
`fecha_ingreso`, `fecha_cierre`, or `exp_fecha_rca` is **2026-08-25**. That data-currency
date is the analysis cutoff for open cases.

- `fecha_ingreso`: submission date (`exp_fpres`).
- `fecha_cierre`: closing date (`exp_fcierre`), when present.
- `duracion_dias`: calendar days from `fecha_ingreso` through `fecha_cierre`; open cases
  use 2026-08-25 as the right-censoring date. The value must be non-negative. It is null
  when `fecha_inconsistente` is true, so source-date anomalies do not enter time analyses.
- `fecha_inconsistente`: `true` when the original `fecha_cierre` precedes
  `fecha_ingreso`. Both source dates are preserved without correction.
- `evento`: normalized outcome derived explicitly from `estado` (`est_nombre`).
- `estado_post_rca`: preserves the original `estado` for `Caducado`, `Revocado`, and
  `Renuncia RCA`; it is null for all other cases. These are post-approval RCA statuses,
  so their survival event is `aprobado` while their later status remains available.
- `admitido`: `false` only for `No Admitido a Tramitación`; `true` otherwise.

| SEA estado | `evento` |
| --- | --- |
| Aprobado | `aprobado` |
| Rechazado | `rechazado` |
| Desistido | `desistido_o_abandonado` |
| Abandonado | `desistido_o_abandonado` |
| No Admitido a Tramitación | `no_admitido` |
| En Calificación | `en_tramite` |
| No calificado | `termino_anticipado` |
| Caducado | `aprobado` |
| Renuncia RCA | `aprobado` |
| Revocado | `aprobado` |

The pipeline fails if it encounters an unlisted state or duplicate `exp_id`. A date
inconsistency also fails validation when its event is `aprobado`, `rechazado`,
`en_tramite`, or `termino_anticipado`, because those events enter time analyses. The
source regression check requires exactly 53 marked inconsistencies.

The principal population excludes every `tipologia` beginning with `i5` (519 admitted,
date-consistent records) and names matching the explicit, accent-insensitive terms
`árido`, `aridos`, `pozo lastrero`, `empréstito`, `ripio`, or
`extracción de material`. The name rule removes 151 additional DIA records. `Cantera`
is deliberately not a criterion, so non-metallic gypsum and limestone quarries remain.
The resulting population has 975 expedientes (851 DIA and 124 EIA). Every exclusion is
listed with its reason in `docs/population_exclusions.csv`.
Every conversion from days to months uses `days / 30.4375` (`365.25 / 12`).

## Unidad de análisis: expediente principal

El cruce de la cartera Cochilco usa como principal el expediente que autoriza el
alcance del proyecto. La inversión SEA/Cochilco es una señal secundaria: recibe un
bono sólo cuando el nombre del proyecto o de la faena también coincide y el cociente
está entre 0,8 y 1,25. Un monto parecido, sin esa coincidencia textual, no genera un
match.

Una familia de reingresos exige el mismo titular y un nombre equivalente después de
retirar términos mineros genéricos. El principal es el expediente más reciente que no
terminó en `no_admitido`, `termino_anticipado`, `desistido_o_abandonado` ni
`rechazado`; si todos terminaron así, se usa el más reciente. La regla anterior
comparaba el nombre normalizado completo y por eso no agrupó “Proyecto Ciclón
Exploradora” con “Proyecto Minero Ciclón Exploradora”: asignó 2155609426, no
calificado, en vez de 2160317349, aprobado.

Dentro de una familia con la misma faena y titular, se despriorizan —sin excluirse—
los expedientes cuyo nombre comienza con Actualización, Modificación, Adecuación,
Optimización o Ajustes, y aquellos con inversión menor o igual a 1 MMUS$. Si existe
un expediente viable no modificatorio con puntaje a no más de cinco puntos, éste se
ordena primero. Expedientes no admitidos, desistidos o rechazados no desplazan a uno
que sí puede autorizar el alcance. Finalmente, un `exp_id` no puede ser principal de
dos proyectos Cochilco salvo que la excepción esté documentada explícitamente al
construir la tabla confirmada.

### Categorías del estado ambiental de la cartera

- `aprobado`, `en_evaluacion` y `desistido_rechazado_o_no_calificado` se derivan del desenlace
  normalizado del expediente SEA principal. Si una RCA fue anulada y el procedimiento
  retrotraído —como C20+— el expediente abierto permanece en `en_evaluacion`.
- `agregado_no_asignable` identifica una fila agregada de Cochilco que reúne varios
  proyectos y no admite asignar un único expediente principal.
- `rca_previa_2011` identifica un proyecto cubierto por una RCA base anterior al inicio
  de la ventana SEA 2011–2026.
- `pertinencia` identifica un proyecto respaldado por una consulta de pertinencia y no
  por un expediente propio de evaluación ambiental.
- `no_determinado` identifica un caso donde la revisión manual no pudo determinar el
  instrumento ambiental aplicable.
- `sin_expediente_en_ejecucion` y `sin_expediente_en_estudio` quedan reservadas para
  respuestas de J que realmente concluyen ausencia de expediente. Ninguna de las cuatro
  categorías manuales anteriores cuenta como “sin expediente”.

## Source-date inconsistency diagnosis

| Diagnostic | Value |
| --- | ---: |
| Total cases | 53 |
| `No Admitido a Tramitación` | 49 |
| `Desistido` | 4 |
| Median offset (`fecha_ingreso - fecha_cierre`) | 1 day |
| Maximum offset | 28 days |

Four inconsistent cases are in the mining subset, and all four are `no_admitido`.
