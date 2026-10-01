SELECT
    instrumento,
    median(duracion_dias) AS mediana_duracion_dias,
    quantile_cont(duracion_dias, 0.75) AS p75_duracion_dias
FROM sea_mining
WHERE evento = 'aprobado'
GROUP BY instrumento
ORDER BY instrumento;
