# SEA survival definitions

The unit of analysis is one SEA environmental-assessment expediente, identified by the
unique `exp_id`. The analysis cutoff is **2026-09-30**.

- `fecha_ingreso`: submission date (`exp_fpres`).
- `fecha_cierre`: closing date (`exp_fcierre`), when present.
- `duracion_dias`: calendar days from `fecha_ingreso` through `fecha_cierre`; open cases
  use 2026-09-30 as the right-censoring date. The value must be non-negative. It is null
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
2026-09-30 regression check requires exactly 53 marked inconsistencies.

## Source-date inconsistency diagnosis

| Diagnostic | Value |
| --- | ---: |
| Total cases | 53 |
| `No Admitido a Tramitación` | 49 |
| `Desistido` | 4 |
| Median offset (`fecha_ingreso - fecha_cierre`) | 1 day |
| Maximum offset | 28 days |

Four inconsistent cases are in the mining subset, and all four are `no_admitido`.
