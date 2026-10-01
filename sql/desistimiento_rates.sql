SELECT
    instrumento,
    count(*) AS expedientes,
    100.0 * avg((evento = 'desistido_o_abandonado')::INTEGER) AS tasa_desistimiento_pct,
    100.0 * avg((evento = 'no_admitido')::INTEGER) AS tasa_no_admision_pct
FROM sea_mining
GROUP BY instrumento
ORDER BY instrumento;
