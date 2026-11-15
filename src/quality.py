"""Data quality validation and audit engine."""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List
import duckdb

from src.config import SCHEMA_REGISTRY, REPORTS_DIR

logger = logging.getLogger("pipeline.quality")


@dataclass
class QualityMetrics:
    """Summary metrics of data quality checks for a single dataset."""
    service_type: str
    year: int
    month: int
    total_raw_rows: int
    valid_rows: int
    invalid_rows: int
    validity_rate_pct: float
    out_of_bounds_pickup_count: int
    inverted_timestamp_count: int  # dropoff < pickup
    zero_or_negative_duration_count: int
    negative_distance_count: int
    null_location_count: int


class DataQualityAuditor:
    """Performs automated data quality validations using DuckDB queries."""

    def __init__(self, con: duckdb.DuckDBPyConnection | None = None):
        self.con = con or duckdb.connect()

    def audit_dataset(
        self,
        service_type: str,
        year: int,
        month: int,
        parquet_path: Path,
    ) -> QualityMetrics:
        """Run statistical and rule-based data quality checks on a parquet file."""
        cfg = SCHEMA_REGISTRY[service_type]
        dist_expr = f'"{cfg.distance_col}"' if cfg.distance_col else "NULL"
        start_bound = f"'{year}-01-01 00:00:00'"
        end_bound = f"'{year}-06-30 23:59:59'"

        query = f"""
        WITH raw_view AS (
            SELECT
                TRY_CAST("{cfg.pickup_col}" AS TIMESTAMP) AS pickup_dt,
                TRY_CAST("{cfg.dropoff_col}" AS TIMESTAMP) AS dropoff_dt,
                TRY_CAST({dist_expr} AS DOUBLE) AS trip_dist,
                TRY_CAST("{cfg.pulocation_col}" AS INTEGER) AS pu_id,
                TRY_CAST("{cfg.dolocation_col}" AS INTEGER) AS do_id
            FROM read_parquet('{parquet_path.as_posix()}')
        )
        SELECT
            COUNT(*) AS total_raw,
            COUNT(*) FILTER (
                WHERE pickup_dt IS NOT NULL
                  AND dropoff_dt IS NOT NULL
                  AND pickup_dt >= {start_bound}
                  AND pickup_dt <= {end_bound}
                  AND dropoff_dt >= pickup_dt
                  AND epoch(dropoff_dt) - epoch(pickup_dt) > 0
                  AND epoch(dropoff_dt) - epoch(pickup_dt) <= 86400
                  AND (trip_dist IS NULL OR trip_dist >= 0)
            ) AS valid_rows,
            COUNT(*) FILTER (
                WHERE pickup_dt < {start_bound} OR pickup_dt > {end_bound}
            ) AS out_of_bounds_pickup,
            COUNT(*) FILTER (
                WHERE dropoff_dt < pickup_dt
            ) AS inverted_timestamps,
            COUNT(*) FILTER (
                WHERE epoch(dropoff_dt) - epoch(pickup_dt) <= 0
            ) AS zero_or_negative_duration,
            COUNT(*) FILTER (
                WHERE trip_dist < 0
            ) AS negative_distance,
            COUNT(*) FILTER (
                WHERE pu_id IS NULL OR do_id IS NULL
            ) AS null_locations
        FROM raw_view
        """

        res = self.con.execute(query).fetchone()
        assert res is not None

        total_raw = res[0]
        valid_rows = res[1]
        invalid_rows = total_raw - valid_rows
        validity_pct = round((valid_rows / total_raw * 100.0) if total_raw > 0 else 0.0, 2)

        metrics = QualityMetrics(
            service_type=service_type,
            year=year,
            month=month,
            total_raw_rows=total_raw,
            valid_rows=valid_rows,
            invalid_rows=invalid_rows,
            validity_rate_pct=validity_pct,
            out_of_bounds_pickup_count=res[2],
            inverted_timestamp_count=res[3],
            zero_or_negative_duration_count=res[4],
            negative_distance_count=res[5],
            null_location_count=res[6],
        )

        logger.info(
            "[%s %d-%02d] Total: %d | Valid: %d (%.2f%%) | DQ Anomalies: %d",
            service_type,
            year,
            month,
            total_raw,
            valid_rows,
            validity_pct,
            invalid_rows,
        )
        return metrics

    def generate_report(
        self,
        metrics_list: List[QualityMetrics],
        output_file: Path | None = None,
    ) -> Dict[str, Any]:
        """Compile quality metrics across all datasets into a structured report."""
        report_path = output_file or (REPORTS_DIR / "data_quality_report.json")
        overall_raw = sum(m.total_raw_rows for m in metrics_list)
        overall_valid = sum(m.valid_rows for m in metrics_list)
        overall_invalid = overall_raw - overall_valid
        overall_pct = round((overall_valid / overall_raw * 100.0) if overall_raw > 0 else 0.0, 2)

        data = {
            "summary": {
                "datasets_audited": len(metrics_list),
                "total_raw_records": overall_raw,
                "total_valid_records": overall_valid,
                "total_anomalies_quarantined": overall_invalid,
                "overall_validity_pct": overall_pct,
            },
            "datasets": [asdict(m) for m in metrics_list],
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info("Saved Data Quality report to %s", report_path)
        return data
