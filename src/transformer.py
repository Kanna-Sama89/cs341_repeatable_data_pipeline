"""Data transformation and curation engine."""

import logging
from pathlib import Path
from typing import List, Tuple
import duckdb

from src.config import CURATED_DIR, SCHEMA_REGISTRY

logger = logging.getLogger("pipeline.transformer")


class DataTransformer:
    """Transforms heterogeneous raw TLC datasets into clean, curated outputs."""

    def __init__(self, con: duckdb.DuckDBPyConnection | None = None):
        self.con = con or duckdb.connect()

    def process_monthly_curation(
        self,
        datasets: List[Tuple[str, int, int, Path]],
    ) -> Path:
        """Aggregate monthly metrics across all services into a unified curated parquet."""
        curated_metrics_path = CURATED_DIR / "curated_monthly_metrics.parquet"

        # Create temporary staging table for monthly aggregates
        self.con.execute("""
            CREATE OR REPLACE TEMP TABLE stage_monthly_metrics (
                service_type VARCHAR,
                year INTEGER,
                month INTEGER,
                trip_count BIGINT,
                total_duration_hours DOUBLE,
                avg_duration_minutes DOUBLE,
                total_miles DOUBLE,
                avg_miles DOUBLE
            );
        """)

        for service, year, month, parquet_path in datasets:
            cfg = SCHEMA_REGISTRY[service]
            dist_expr = f'TRY_CAST("{cfg.distance_col}" AS DOUBLE)' if cfg.distance_col else "NULL"
            start_bound = f"'{year}-01-01 00:00:00'"
            end_bound = f"'{year}-06-30 23:59:59'"

            query = f"""
            INSERT INTO stage_monthly_metrics
            WITH cleaned AS (
                SELECT
                    '{service}' AS service_type,
                    {year} AS year,
                    {month} AS month,
                    TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP) AS pickup_dt,
                    TRY_CAST("{cfg.dropoff_col}" AS TIMESTAMP) AS dropoff_dt,
                    {dist_expr} AS trip_dist
                FROM read_parquet('{parquet_path.as_posix()}')
                WHERE "{cfg.pickup_col}" IS NOT NULL
                  AND "{cfg.dropoff_col}" IS NOT NULL
                  AND TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP) >= {start_bound}
                  AND TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP) <= {end_bound}
                  AND TRY_CAST("{cfg.dropoff_col}" AS TIMESTAMP) >= TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP)
                  AND epoch(TRY_CAST("{cfg.dropoff_col}" AS TIMESTAMP)) - epoch(TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP)) > 0
                  AND epoch(TRY_CAST("{cfg.dropoff_col}" AS TIMESTAMP)) - epoch(TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP)) <= 86400
                  AND ({dist_expr} IS NULL OR {dist_expr} >= 0)
            )
            SELECT
                service_type,
                year,
                month,
                COUNT(*) AS trip_count,
                ROUND(SUM(epoch(dropoff_dt) - epoch(pickup_dt)) / 3600.0, 2) AS total_duration_hours,
                ROUND(AVG(epoch(dropoff_dt) - epoch(pickup_dt)) / 60.0, 2) AS avg_duration_minutes,
                ROUND(SUM(trip_dist), 2) AS total_miles,
                ROUND(AVG(trip_dist), 2) AS avg_miles
            FROM cleaned
            GROUP BY service_type, year, month;
            """
            self.con.execute(query)
            logger.info("Transformed and staged metrics for %s %d-%02d", service, year, month)

        # Export staged table to Parquet and CSV
        export_parquet = f"COPY stage_monthly_metrics TO '{curated_metrics_path.as_posix()}' (FORMAT PARQUET);"
        export_csv = f"COPY stage_monthly_metrics TO '{(CURATED_DIR / 'curated_monthly_metrics.csv').as_posix()}' (HEADER, DELIMITER ',');"
        self.con.execute(export_parquet)
        self.con.execute(export_csv)

        logger.info("Exported curated monthly metrics to %s", curated_metrics_path)
        return curated_metrics_path

    def generate_curated_sample(
        self,
        datasets: List[Tuple[str, int, int, Path]],
        sample_per_dataset: int = 5000,
    ) -> Path:
        """Create a clean, standardized sample dataset across all services."""
        sample_path = CURATED_DIR / "curated_trips_sample.parquet"

        self.con.execute("""
            CREATE OR REPLACE TEMP TABLE stage_unified_sample (
                service_type VARCHAR,
                pickup_datetime TIMESTAMP,
                dropoff_datetime TIMESTAMP,
                trip_duration_seconds INTEGER,
                trip_miles DOUBLE,
                pulocation_id INTEGER,
                dolocation_id INTEGER,
                year INTEGER,
                month INTEGER
            );
        """)

        for service, year, month, parquet_path in datasets:
            cfg = SCHEMA_REGISTRY[service]
            dist_expr = f'TRY_CAST("{cfg.distance_col}" AS DOUBLE)' if cfg.distance_col else "NULL"
            start_bound = f"'{year}-01-01 00:00:00'"
            end_bound = f"'{year}-06-30 23:59:59'"

            sample_query = f"""
            INSERT INTO stage_unified_sample
            SELECT
                '{service}' AS service_type,
                TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP) AS pickup_datetime,
                TRY_CAST("{cfg.dropoff_col}" AS TIMESTAMP) AS dropoff_datetime,
                CAST(epoch(TRY_CAST("{cfg.dropoff_col}" AS TIMESTAMP)) - epoch(TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP)) AS INTEGER) AS trip_duration_seconds,
                {dist_expr} AS trip_miles,
                TRY_CAST("{cfg.pulocation_col}" AS INTEGER) AS pulocation_id,
                TRY_CAST("{cfg.dolocation_col}" AS INTEGER) AS dolocation_id,
                {year} AS year,
                {month} AS month
            FROM read_parquet('{parquet_path.as_posix()}')
            WHERE "{cfg.pickup_col}" IS NOT NULL
              AND "{cfg.dropoff_col}" IS NOT NULL
              AND TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP) >= {start_bound}
              AND TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP) <= {end_bound}
              AND TRY_CAST("{cfg.dropoff_col}" AS TIMESTAMP) >= TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP)
              AND epoch(TRY_CAST("{cfg.dropoff_col}" AS TIMESTAMP)) - epoch(TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP)) > 0
              AND epoch(TRY_CAST("{cfg.dropoff_col}" AS TIMESTAMP)) - epoch(TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP)) <= 86400
            USING SAMPLE {sample_per_dataset} ROWS;
            """
            try:
                self.con.execute(sample_query)
            except Exception as err:
                logger.warning("Could not sample from %s %d-%02d: %s", service, year, month, err)

        export_sample = f"COPY stage_unified_sample TO '{sample_path.as_posix()}' (FORMAT PARQUET);"
        self.con.execute(export_sample)
        logger.info("Exported curated sample dataset to %s", sample_path)
        return sample_path
