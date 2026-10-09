# Resultados de supervivencia SEA

Censura: **25-08-2026** (último registro; descarga 30-09-2026). Población: proyectos mineros admitidos a tramitación, sin inconsistencia de fechas y excluyendo tipologías i5, i5.1 e i5.2.

## Kaplan–Meier

**Tiempo hasta aprobación entre proyectos que siguen en juego.** Los desenlaces distintos de aprobación se tratan como censura; por eso estas probabilidades no son la cifra principal de probabilidad real de aprobación.

| Instrumento | Mediana KM (meses) | IC 95% | 6 meses | 12 meses | 24 meses | 36 meses |
| --- | --- | --- | --- | --- | --- | --- |
| DIA | 8.0 | 7.6–8.3 | 33.2% | 78.3% | 96.9% | 99.1% |
| EIA | 27.3 | 23.4–32.2 | 1.1% | 4.4% | 41.6% | 70.4% |

## Riesgos competitivos (cifra principal)

La incidencia acumulada de Aalen–Johansen conserva desistimientos, rechazos y términos anticipados como desenlaces competidores. KM los censura y, en consecuencia, sobreestima la probabilidad de aprobación cuando estos riesgos existen.

| Instrumento | Desenlace | Incidencia a 24 meses |
| --- | --- | --- |
| DIA | Aprobado | 70.2% |
| DIA | Desistido o abandonado | 19.7% |
| DIA | Rechazado | 1.8% |
| DIA | Término anticipado | 6.8% |
| EIA | Aprobado | 31.7% |
| EIA | Desistido o abandonado | 17.9% |
| EIA | Rechazado | 1.0% |
| EIA | Término anticipado | 7.5% |

## Tendencia por cohorte de ingreso

La tendencia usa la mediana observada de duración exclusivamente entre proyectos aprobados. Las cohortes 2025–2026 se marcan como incompletas por censura y no deben interpretarse como una mejora reciente.

Filas de tendencia: 32 (2011–2026 por instrumento).

## Cox exploratorio

| Variable | HR | IC 95% | p |
| --- | --- | --- | --- |
| log_inversion | 1.04 | 1.00–1.08 | 0.029 |
| anio_ingreso | 0.97 | 0.95–0.98 | 0.000 |
| macro_zona_Norte Chico | 0.65 | 0.54–0.77 | 0.000 |
| macro_zona_Norte Grande | 0.81 | 0.67–0.98 | 0.034 |

Test de proporcionalidad de Schoenfeld (modelo inicial):

| Variable | p |
| --- | --- |
| anio_ingreso | 0.000 |
| instrumento_EIA | 0.005 |
| log_inversion | 0.535 |
| macro_zona_Norte Chico | 0.000 |
| macro_zona_Norte Grande | 0.000 |

N=1108; aprobaciones=745.
El test de Schoenfeld detectó una violación; el modelo se estratificó por instrumento, pero persistieron violaciones en otras covariables.

## Supuestos y límites

- Las duraciones son días calendario desde ingreso hasta cierre; expedientes abiertos se censuran al 25-08-2026.
- KM estima el tiempo hasta aprobación condicionado a seguir en juego; no es una probabilidad de cartera con riesgos competitivos.
- Aalen–Johansen es la estimación principal de incidencia acumulada por desenlace.
- El Cox es exploratorio y causa-específico; inversión faltante o no positiva se excluye del modelo.
- Las medianas observadas de aprobados por cohorte sufren sesgo de selección, especialmente en 2025–2026.

Fuente: Cochilco (dic-2025), SEA (descarga 30-09-2026; vigencia de datos 25-08-2026). Elaboración propia.
