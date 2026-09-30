WITH grouped AS (
    SELECT
        empresa,
        COUNT(*) AS project_rows,
        SUM(inversion_musd) AS investment_musd
    FROM cochilco_projects
    GROUP BY empresa
), ranked AS (
    SELECT
        empresa,
        project_rows,
        investment_musd,
        SUM(investment_musd) OVER () AS portfolio_musd
    FROM grouped
)
SELECT
    empresa,
    project_rows,
    ROUND(investment_musd, 1) AS investment_musd,
    ROUND(100.0 * investment_musd / portfolio_musd, 2) AS participation_pct
FROM ranked
ORDER BY investment_musd DESC, empresa
LIMIT 15;

