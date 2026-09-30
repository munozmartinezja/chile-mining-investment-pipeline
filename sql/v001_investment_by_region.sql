WITH grouped AS (
    SELECT
        region,
        COUNT(*) AS project_rows,
        SUM(inversion_musd) AS investment_musd
    FROM cochilco_projects
    GROUP BY region
)
SELECT
    region,
    project_rows,
    ROUND(investment_musd, 1) AS investment_musd,
    ROUND(100.0 * investment_musd / SUM(investment_musd) OVER (), 2) AS participation_pct
FROM grouped
ORDER BY investment_musd DESC, region;

