CREATE MATERIALIZED VIEW IF NOT EXISTS sec_ingestion_summary AS
SELECT
    created_at::date AS ingestion_date,
    source,
    COUNT(*) FILTER (WHERE status IN ('success', 'failed', 'skipped'))::bigint AS filings_processed,
    COUNT(*) FILTER (WHERE status = 'failed')::bigint AS filings_failed,
    COUNT(*) FILTER (WHERE status = 'skipped')::bigint AS filings_skipped,
    COALESCE(SUM(transaction_count) FILTER (WHERE status = 'success'), 0)::bigint AS transactions_extracted,
    AVG(duration_ms) FILTER (WHERE duration_ms IS NOT NULL)::numeric(18, 2) AS avg_duration_ms,
    MAX(duration_ms)::bigint AS max_duration_ms
FROM sec_ingestion_log
GROUP BY created_at::date, source
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS ux_sec_ingestion_summary_date_source
ON sec_ingestion_summary (ingestion_date, source);
