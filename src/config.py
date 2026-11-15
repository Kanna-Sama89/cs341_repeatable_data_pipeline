"""Pipeline configuration and schema registry."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

# Base filesystem paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
CURATED_DIR = DATA_DIR / "curated"
REPORTS_DIR = BASE_DIR / "reports"
LOGS_DIR = BASE_DIR / "logs"

# Ensure runtime directories exist
for directory in (RAW_DIR, CURATED_DIR, REPORTS_DIR, LOGS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# TLC CloudFront Source Configuration
TLC_BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"

SERVICE_TYPES = ["yellow", "green", "fhv", "hvfhv"]

DEFAULT_YEAR = 2024
DEFAULT_MONTHS = list(range(1, 7))  # H1: Jan - Jun


@dataclass(frozen=True)
class ServiceSchemaConfig:
    """Column mapping configuration for a taxi service type."""
    service_type: str
    file_prefix: str
    pickup_col: str
    dropoff_col: str
    pulocation_col: str
    dolocation_col: str
    distance_col: str | None
    passenger_count_col: str | None


SCHEMA_REGISTRY: Dict[str, ServiceSchemaConfig] = {
    "yellow": ServiceSchemaConfig(
        service_type="yellow",
        file_prefix="yellow_tripdata",
        pickup_col="tpep_pickup_datetime",
        dropoff_col="tpep_dropoff_datetime",
        pulocation_col="PULocationID",
        dolocation_col="DOLocationID",
        distance_col="trip_distance",
        passenger_count_col="passenger_count",
    ),
    "green": ServiceSchemaConfig(
        service_type="green",
        file_prefix="green_tripdata",
        pickup_col="lpep_pickup_datetime",
        dropoff_col="lpep_dropoff_datetime",
        pulocation_col="PULocationID",
        dolocation_col="DOLocationID",
        distance_col="trip_distance",
        passenger_count_col="passenger_count",
    ),
    "fhv": ServiceSchemaConfig(
        service_type="fhv",
        file_prefix="fhv_tripdata",
        pickup_col="pickup_datetime",
        dropoff_col="dropOff_datetime",  # Note casing
        pulocation_col="PUlocationID",   # Note casing
        dolocation_col="DOlocationID",   # Note casing
        distance_col=None,
        passenger_count_col=None,
    ),
    "hvfhv": ServiceSchemaConfig(
        service_type="hvfhv",
        file_prefix="fhvhv_tripdata",
        pickup_col="pickup_datetime",
        dropoff_col="dropoff_datetime",
        pulocation_col="PULocationID",
        dolocation_col="DOLocationID",
        distance_col="trip_miles",
        passenger_count_col=None,
    ),
}


def get_remote_url(service_type: str, year: int, month: int) -> str:
    """Generate remote CloudFront Parquet URL."""
    prefix = SCHEMA_REGISTRY[service_type].file_prefix
    return f"{TLC_BASE_URL}/{prefix}_{year}-{month:02d}.parquet"


def get_local_path(service_type: str, year: int, month: int) -> Path:
    """Generate standardized local storage path for raw parquet."""
    prefix = SCHEMA_REGISTRY[service_type].file_prefix
    return RAW_DIR / f"{prefix}_{year}-{month:02d}.parquet"
