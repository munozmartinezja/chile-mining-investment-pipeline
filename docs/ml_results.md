# Modelo predictivo de aprobación ambiental a 24 meses

## 1. Pregunta

Con lo conocido al momento del ingreso al SEIA, ¿se puede anticipar si un proyecto obtendrá RCA favorable dentro de 24 meses?

## 2. Población y objetivo

El dataset ML incluye 920 ingresos con seguimiento completo de 24 meses (fecha de ingreso + 24 meses (730,5 días) ≤ fecha de corte de los datos). De estos, 617 obtuvieron RCA favorable dentro del horizonte (tasa de aprobación: 67,1 %). La distribución por instrumento es 817 DIA y 103 EIA.
El corte 2024 incluye solo 28 de 42 expedientes; por tanto, ese año no representa todos sus ingresos.

Variable objetivo `y = 1` si el expediente fue aprobado dentro de 24 meses desde el ingreso; `y = 0` en cualquier otro desenlace (desistimiento, rechazo, en trámite sin resolución en el horizonte).

## 3. Validación

Se utilizó validación rolling origin con 7 folds anuales (años 2018–2024). Para cada año de prueba Y, el conjunto de entrenamiento incluye solo expedientes cuyo horizonte de 24 meses cerró antes del 1 de enero de Y. Este embargo garantiza que no se entrena con información futura.

## 4. Resultados

| Modelo | ROC AUC | Brier | Log loss |
|--------|---------|-------|----------|
| B0 (tasa base) | 0,612 | 0,213 | 0,619 |
| M1 (logístico) | 0,706 | 0,209 | 0,622 |
| M2 (HGB) | 0,745 | 0,213 | 0,655 |
| M2c (HGB calibrado) | 0,733 | 0,198 | 0,578 |

ROC AUC mínimo por fold de M2c: 0,514.

La diferencia de Brier frente a B0 depende del esquema de remuestreo (por expediente, el IC incluye cero; por año, lo excluye), así que no se afirma una mejora en probabilidades.

## 5. Dónde no funciona

**EIA:** el subgrupo EIA acumula solo 45 expedientes de prueba en los 7 folds. El ROC AUC de M2c en EIA (0,449) no supera el azar, frente a 0,737 en DIA. Las probabilidades no son confiables para EIA.

**Inestabilidad entre años:** el ROC AUC varía entre folds. El mínimo por fold de M2c es 0,514, lo que indica que el modelo no es igualmente discriminativo en todos los años de prueba.

## 6. Qué lo mueve

Análisis exploratorio, sin protocolo preespecificado.

| Familia | Especificaciones evaluadas |
|---|---|
| Modelos completos | B0; M1; M2; M2c |
| Ablaciones | M1 y M2 sin titular; sin carga; sin calendario |
| Calibración | Curvas de M1; M2; M2c |
| Subgrupos | DIA; EIA |

En la ablación del modelo M2, el ROC AUC es 0,745 con todas las variables y 0,649 sin el bloque del titular. Esta comparación exploratoria respalda que el historial del titular aporta señal a M2; no es una afirmación causal ni sobre M2c.

Como sensibilidad, el ROC AUC de M2c dentro de las DIA sin el corte 2024 es 0,744.

## 7. Límites

- **Asociación, no causalidad.** El modelo detecta patrones históricos; no explica por qué un proyecto es aprobado.
- **Calibración.** M2c usa `CalibratedClassifierCV` con 5 folds estratificados dentro del entrenamiento de cada corte; esos folds no son aleatorios ni temporales. La calibración puede degradarse fuera de la muestra.
- **Población pequeña.** Con menos de mil expedientes elegibles, los intervalos de confianza son amplios.
- **Sin uso operativo para EIA.** Las probabilidades para EIA no son confiables y no deben usarse para tomar decisiones.
