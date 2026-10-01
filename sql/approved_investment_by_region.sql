SELECT
    region,
    sum(inversion_musd) AS inversion_aprobada_musd
FROM sea_mining
WHERE evento = 'aprobado'
GROUP BY region
ORDER BY inversion_aprobada_musd DESC NULLS LAST, region;
