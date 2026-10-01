SELECT
    year(fecha_ingreso) AS ingreso_year,
    instrumento,
    count(*) AS expedientes
FROM sea_mining
GROUP BY ingreso_year, instrumento
ORDER BY ingreso_year, instrumento;
