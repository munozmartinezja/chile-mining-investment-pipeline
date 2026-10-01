# Resultados de supervivencia SEA

Corte: **30-09-2026**. Población: proyectos mineros admitidos a tramitación y sin inconsistencia de fechas.

## Kaplan–Meier

**Tiempo hasta aprobación entre proyectos que siguen en juego.** Los desenlaces distintos de aprobación se tratan como censura; por eso estas probabilidades no son la cifra principal de probabilidad real de aprobación.

| Instrumento | Mediana KM (meses) | IC 95% | 6 meses | 12 meses | 24 meses | 36 meses |
| --- | --- | --- | --- | --- | --- | --- |
| DIA | 7.7 | 7.2–8.1 | 37.9% | 76.7% | 96.2% | 99.3% |
| EIA | 28.8 | 23.7–32.9 | 1.0% | 4.3% | 41.2% | 69.9% |

## Riesgos competitivos (cifra principal)

La incidencia acumulada de Aalen–Johansen conserva desistimientos, rechazos y términos anticipados como desenlaces competidores. KM los censura y, en consecuencia, sobreestima la probabilidad de aprobación cuando estos riesgos existen.

| Instrumento | Desenlace | Incidencia a 24 meses |
| --- | --- | --- |
| DIA | Aprobado | 66.5% |
| DIA | Desistido o abandonado | 22.5% |
| DIA | Rechazado | 2.3% |
| DIA | Término anticipado | 7.5% |
| EIA | Aprobado | 31.1% |
| EIA | Desistido o abandonado | 19.2% |
| EIA | Rechazado | 1.0% |
| EIA | Término anticipado | 7.0% |

## Tendencia por cohorte de ingreso

La tendencia usa la mediana observada de duración exclusivamente entre proyectos aprobados. Las cohortes 2025–2026 se marcan como incompletas por censura y no deben interpretarse como una mejora reciente.

Filas de tendencia: 32 (2011–2026 por instrumento).

## Cox exploratorio

| Variable | HR | IC 95% | p |
| --- | --- | --- | --- |
| log_inversion | 1.06 | 1.03–1.10 | 0.000 |
| anio_ingreso | 0.92 | 0.90–0.93 | 0.000 |
| macro_zona_Norte Chico | 0.63 | 0.53–0.74 | 0.000 |
| macro_zona_Norte Grande | 0.77 | 0.65–0.91 | 0.002 |

Test de proporcionalidad de Schoenfeld (modelo inicial):

| Variable | p |
| --- | --- |
| anio_ingreso | 0.000 |
| instrumento_EIA | 0.025 |
| log_inversion | 0.379 |
| macro_zona_Norte Chico | 0.000 |
| macro_zona_Norte Grande | 0.000 |

N=1626; aprobaciones=1041. 
El test de Schoenfeld detectó una violación; el modelo se estratificó por instrumento, pero persistieron violaciones en otras covariables.

## Supuestos y límites

- Las duraciones son días calendario desde ingreso hasta cierre; expedientes abiertos se censuran al 30-09-2026.
- KM estima el tiempo hasta aprobación condicionado a seguir en juego; no es una probabilidad de cartera con riesgos competitivos.
- Aalen–Johansen es la estimación principal de incidencia acumulada por desenlace.
- El Cox es exploratorio y causa-específico; inversión faltante o no positiva se excluye del modelo.
- Las medianas observadas de aprobados por cohorte sufren sesgo de selección, especialmente en 2025–2026.

Fuente: Cochilco (dic-2025), SEA (corte 30-09-2026). Elaboración propia.
