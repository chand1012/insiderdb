CREATE MATERIALIZED VIEW IF NOT EXISTS sec_cluster_buys AS
WITH purchases AS (
    SELECT
        ticker,
        transaction_date,
        reporting_owner_cik,
        reporting_owner_name,
        officer_title,
        value
    FROM sec_insider_transactions
    WHERE transaction_code = 'P'
      AND value >= 25000
      AND ticker IS NOT NULL
      AND transaction_date IS NOT NULL
),
candidate_windows AS (
    SELECT DISTINCT
        ticker,
        transaction_date AS cluster_start,
        (transaction_date + INTERVAL '6 days')::date AS cluster_window_end
    FROM purchases
)
SELECT
    candidate_windows.ticker,
    candidate_windows.cluster_start,
    MAX(purchases.transaction_date)::date AS cluster_end,
    COUNT(DISTINCT COALESCE(purchases.reporting_owner_cik, purchases.reporting_owner_name))::integer AS unique_insiders,
    SUM(purchases.value)::numeric(24, 2) AS total_value,
    ARRAY_AGG(DISTINCT purchases.reporting_owner_name) FILTER (WHERE purchases.reporting_owner_name IS NOT NULL) AS insider_names,
    ARRAY_AGG(DISTINCT purchases.officer_title) FILTER (WHERE purchases.officer_title IS NOT NULL) AS officer_titles
FROM candidate_windows
JOIN purchases
  ON purchases.ticker = candidate_windows.ticker
 AND purchases.transaction_date BETWEEN candidate_windows.cluster_start AND candidate_windows.cluster_window_end
GROUP BY candidate_windows.ticker, candidate_windows.cluster_start
HAVING COUNT(DISTINCT COALESCE(purchases.reporting_owner_cik, purchases.reporting_owner_name)) >= 2
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS ux_sec_cluster_buys_ticker_start
ON sec_cluster_buys (ticker, cluster_start);
