"""Data ingestion manager for NYC TLC Parquet files."""

import logging
from pathlib import Path
from typing import List, Tuple
import requests
from tqdm import tqdm

from src.config import SCHEMA_REGISTRY, get_local_path, get_remote_url

logger = logging.getLogger("pipeline.ingest")


class DataIngestor:
    """Manages downloading, local caching, and verification of TLC Parquet files."""

    def __init__(self, chunk_size: int = 1024 * 1024, timeout: int = 60):
        self.chunk_size = chunk_size
        self.timeout = timeout

    def check_remote_file_size(self, url: str) -> int:
        """Perform HEAD request to determine file size in bytes."""
        try:
            resp = requests.head(url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code == 200:
                return int(resp.headers.get("content-length", 0))
            logger.warning("Remote URL returned status %d: %s", resp.status_code, url)
            return 0
        except Exception as err:
            logger.error("Failed to inspect %s: %s", url, err)
            return 0

    def download_file(self, url: str, destination: Path) -> bool:
        """Download remote parquet file with progress bar and streaming."""
        if destination.exists() and destination.stat().st_size > 0:
            logger.info("Cached file already present: %s (%d bytes)", destination.name, destination.stat().st_size)
            return True

        temp_dest = destination.with_suffix(".tmp")
        try:
            logger.info("Downloading from %s to %s", url, destination.name)
            response = requests.get(url, stream=True, timeout=self.timeout)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            with open(temp_dest, "wb") as f, tqdm(
                total=total_size,
                unit="B",
                unit_scale=True,
                desc=destination.name,
                leave=False,
            ) as pbar:
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))

            temp_dest.rename(destination)
            logger.info("Successfully downloaded %s (%d bytes)", destination.name, destination.stat().st_size)
            return True
        except Exception as err:
            logger.error("Failed downloading %s: %s", url, err)
            if temp_dest.exists():
                temp_dest.unlink()
            return False

    def sync_datasets(
        self,
        services: List[str],
        year: int,
        months: List[int],
    ) -> List[Tuple[str, int, int, Path]]:
        """Download and verify all requested service-month parquet files."""
        downloaded = []
        for service in services:
            if service not in SCHEMA_REGISTRY:
                logger.warning("Skipping unknown service: %s", service)
                continue
            for month in months:
                url = get_remote_url(service, year, month)
                local_path = get_local_path(service, year, month)
                success = self.download_file(url, local_path)
                if success:
                    downloaded.append((service, year, month, local_path))
                else:
                    logger.error("Missing expected dataset: %s %d-%02d", service, year, month)
        return downloaded
