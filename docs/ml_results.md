# Modelo predictivo de aprobación ambiental a 24 meses

## 1. Pregunta

Con lo conocido al momento del ingreso al SEIA, ¿se puede anticipar si un proyecto obtendrá RCA favorable dentro de 24 meses?

## 2. Población y objetivo

El dataset ML incluye 920 expedientes con horizonte completo de observación (fecha de ingreso + 24 meses (730,5 días) ≤ fecha de corte de los datos). De estos, 617 obtuvieron RCA favorable dentro del horizonte (tasa de aprobación: 67,1 %). La distribución por instrumento es 817 DIA y 103 EIA.

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

El intervalo de confianza 95 % bootstrap para la diferencia de Brier entre M2c y B0 incluye cero; la mejora en calibración no es estadísticamente concluyente.

## 5. Dónde no funciona

**EIA:** el subgrupo EIA acumula solo 45 expedientes de prueba en los 7 folds. El ROC AUC de M2c en EIA (0,449) no supera el azar, frente a 0,737 en DIA. Las probabilidades no son confiables para EIA.

**Inestabilidad entre años:** el ROC AUC varía entre folds. El mínimo por fold de M2c es 0,514, lo que indica que el modelo no es igualmente discriminativo en todos los años de prueba.

## 6. Qué lo mueve

El historial del titular al momento del ingreso —número de proyectos previos, aprobaciones anteriores y cierres negativos recientes— es la señal principal para ordenar el riesgo de aprobación de las DIA. La calibración reduce el error de las probabilidades, pero esa mejora no es estadísticamente concluyente (IC 95 % bootstrap incluye cero). Los resultados de ablación por bloque de variables están en proceso de revisión y no se publican aquí.

## 7. Límites

- **Asociación, no causalidad.** El modelo detecta patrones históricos; no explica por qué un proyecto es aprobado.
- **Calibración.** M2c usa calibración sigmoide (Platt) con validación cruzada aleatoria dentro del entrenamiento, no temporal. La calibración puede degradarse fuera de la muestra.
- **Población pequeña.** Con menos de mil expedientes elegibles, los intervalos de confianza son amplios.
- **Sin uso operativo para EIA.** Las probabilidades para EIA no son confiables y no deben usarse para tomar decisiones.
