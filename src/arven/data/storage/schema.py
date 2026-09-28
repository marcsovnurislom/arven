"""DuckDB schema.

All time columns are BIGINT UTC epoch milliseconds (suffix ``_ms``). Bars are ``[open_time_ms, close_time_ms)``
with ``close_time_ms = open_time_ms + duration``; a bar is usable from ``close_time_ms`` plus the configured
bar availability delay (applied when reading, so it is not stored). Funding and open interest store an
explicit ``available_at_ms`` because their availability differs from their event time.
"""

SCHEMA_VERSION = 1

DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_info (
        key VARCHAR PRIMARY KEY,
        value VARCHAR NOT NULL
    )
    """,
    # --- provenance ---------------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS source_files (
        source_key              VARCHAR PRIMARY KEY,  -- path relative to bucket root == path under raw_dir
        url                     VARCHAR NOT NULL,
        dataset                 VARCHAR NOT NULL,
        granularity             VARCHAR NOT NULL,
        symbol                  VARCHAR NOT NULL,
        interval                VARCHAR,
        period_start_ms         BIGINT NOT NULL,
        period_end_ms           BIGINT NOT NULL,
        expected_sha256         VARCHAR,              -- from Binance .CHECKSUM
        actual_sha256           VARCHAR,              -- computed locally
        size_bytes              BIGINT,
        downloaded_at_ms        BIGINT,
        ingested_at_ms          BIGINT,
        ingested_sha256         VARCHAR,              -- digest of the file whose rows are in the tables
        row_count               BIGINT,               -- rows stored from this file (after dropping exact duplicates)
        duplicate_rows_dropped  BIGINT,
        status                  VARCHAR NOT NULL,     -- downloaded | ingested | not_available | checksum_mismatch | failed
        error                   VARCHAR,
        last_run_id             VARCHAR,
        updated_at_ms           BIGINT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ingestion_runs (
        run_id              VARCHAR PRIMARY KEY,
        command             VARCHAR NOT NULL,
        params_json         VARCHAR NOT NULL,
        config_hash         VARCHAR NOT NULL,
        git_commit          VARCHAR,
        started_at_ms       BIGINT NOT NULL,
        finished_at_ms      BIGINT,
        status              VARCHAR NOT NULL,     -- running | succeeded | completed_with_errors | failed
        summary_json        VARCHAR
    )
    """,
    # --- market data --------------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS ohlcv_1m (
        symbol                  VARCHAR NOT NULL,
        open_time_ms            BIGINT NOT NULL,
        close_time_ms           BIGINT NOT NULL,
        open                    DOUBLE NOT NULL,
        high                    DOUBLE NOT NULL,
        low                     DOUBLE NOT NULL,
        close                   DOUBLE NOT NULL,
        volume                  DOUBLE NOT NULL,
        quote_volume            DOUBLE NOT NULL,
        trade_count             BIGINT NOT NULL,
        taker_buy_volume        DOUBLE NOT NULL,
        taker_buy_quote_volume  DOUBLE NOT NULL,
        source_key              VARCHAR NOT NULL,
        ingested_at_ms          BIGINT NOT NULL,
        PRIMARY KEY (symbol, open_time_ms)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ohlcv (
        symbol                  VARCHAR NOT NULL,
        timeframe               VARCHAR NOT NULL,
        open_time_ms            BIGINT NOT NULL,
        close_time_ms           BIGINT NOT NULL,
        open                    DOUBLE NOT NULL,
        high                    DOUBLE NOT NULL,
        low                     DOUBLE NOT NULL,
        close                   DOUBLE NOT NULL,
        volume                  DOUBLE NOT NULL,
        quote_volume            DOUBLE NOT NULL,
        trade_count             BIGINT NOT NULL,
        taker_buy_volume        DOUBLE NOT NULL,
        taker_buy_quote_volume  DOUBLE NOT NULL,
        bar_count               INTEGER NOT NULL,     -- number of 1m bars aggregated
        is_complete             BOOLEAN NOT NULL,     -- bar_count == minutes in timeframe
        built_at_ms             BIGINT NOT NULL,
        PRIMARY KEY (symbol, timeframe, open_time_ms)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ohlcv_native (
        symbol                  VARCHAR NOT NULL,
        timeframe               VARCHAR NOT NULL,
        open_time_ms            BIGINT NOT NULL,
        close_time_ms           BIGINT NOT NULL,
        open                    DOUBLE NOT NULL,
        high                    DOUBLE NOT NULL,
        low                     DOUBLE NOT NULL,
        close                   DOUBLE NOT NULL,
        volume                  DOUBLE NOT NULL,
        quote_volume            DOUBLE NOT NULL,
        trade_count             BIGINT NOT NULL,
        taker_buy_volume        DOUBLE NOT NULL,
        taker_buy_quote_volume  DOUBLE NOT NULL,
        source_key              VARCHAR NOT NULL,
        ingested_at_ms          BIGINT NOT NULL,
        PRIMARY KEY (symbol, timeframe, open_time_ms)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS funding_rates (
        symbol                  VARCHAR NOT NULL,
        funding_time_ms         BIGINT NOT NULL,      -- normalised to the funding grid (whole hour)
        raw_funding_time_ms     BIGINT NOT NULL,      -- as published (may carry ms jitter)
        funding_rate            DOUBLE NOT NULL,
        funding_interval_hours  INTEGER NOT NULL,
        available_at_ms         BIGINT NOT NULL,      -- max(raw, normalised)
        source_key              VARCHAR NOT NULL,
        ingested_at_ms          BIGINT NOT NULL,
        PRIMARY KEY (symbol, funding_time_ms)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS open_interest (
        symbol                              VARCHAR NOT NULL,
        ts_ms                               BIGINT NOT NULL,   -- snapshot time (create_time, UTC)
        available_at_ms                     BIGINT NOT NULL,   -- ts_ms + configured OI availability delay
        sum_open_interest                   DOUBLE,
        sum_open_interest_value             DOUBLE,
        count_toptrader_long_short_ratio    DOUBLE,
        sum_toptrader_long_short_ratio      DOUBLE,
        count_long_short_ratio              DOUBLE,
        sum_taker_long_short_vol_ratio      DOUBLE,
        source_key                          VARCHAR NOT NULL,
        ingested_at_ms                      BIGINT NOT NULL,
        PRIMARY KEY (symbol, ts_ms)
    )
    """,
    # --- quality ------------------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS quality_results (
        run_id          VARCHAR NOT NULL,
        check_id        VARCHAR NOT NULL,
        dataset         VARCHAR NOT NULL,
        severity        VARCHAR NOT NULL,     -- error | warning | info
        passed          BOOLEAN NOT NULL,
        observed        VARCHAR NOT NULL,
        details_json    VARCHAR,
        checked_at_ms   BIGINT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS data_gaps (
        dataset         VARCHAR NOT NULL,
        symbol          VARCHAR NOT NULL,
        timeframe       VARCHAR NOT NULL,
        gap_start_ms    BIGINT NOT NULL,      -- first missing timestamp
        gap_end_ms      BIGINT NOT NULL,      -- first present timestamp after the gap
        missing_count   BIGINT NOT NULL,
        detected_run_id VARCHAR NOT NULL
    )
    """,
)
