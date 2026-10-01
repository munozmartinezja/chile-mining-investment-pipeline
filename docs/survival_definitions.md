# SEA survival definitions

The unit of analysis is one SEA environmental-assessment expediente, identified by the
unique `exp_id`. The analysis cutoff is **2026-09-30**.

- `fecha_ingreso`: submission date (`exp_fpres`).
- `fecha_cierre`: closing date (`exp_fcierre`), when present.
- `duracion_dias`: calendar days from `fecha_ingreso` through `fecha_cierre`; open cases
  use 2026-09-30 as the right-censoring date. The value must be non-negative.
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

The pipeline fails if it encounters an unlisted state. It also rejects duplicate `exp_id`
values, closure dates before submission, negative durations, and deviations from the
verified mining-state counts for the 2026-09-30 snapshot.
