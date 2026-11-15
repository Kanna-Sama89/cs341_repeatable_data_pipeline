"""Master CLI entry point for NYC Taxi Data Pipeline."""

import argparse
import logging
import sys
import time
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.analysis import AnalysisEngine
from src.config import DEFAULT_MONTHS, DEFAULT_YEAR, LOGS_DIR, SERVICE_TYPES
from src.ingest import DataIngestor
from src.quality import DataQualityAuditor
from src.transformer import DataTransformer

console = Console()


def setup_logging() -> logging.Logger:
    """Setup dual console and file logging."""
    log_file = LOGS_DIR / "pipeline_run.log"
    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.INFO)

    # Clean existing handlers
    logger.handlers.clear()

    # File handler
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(ch)

    return logger


def main() -> None:
    """Execute end-to-end data pipeline."""
    parser = argparse.ArgumentParser(description="NYC Taxi Reproducible Data Pipeline")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR, help="Target year (default: 2024)")
    parser.add_argument("--start-month", type=int, default=1, help="Start month (default: 1)")
    parser.add_argument("--end-month", type=int, default=6, help="End month (default: 6)")
    parser.add_argument(
        "--services",
        nargs="+",
        default=SERVICE_TYPES,
        help="List of services to process (default: yellow green fhv hvfhv)",
    )
    args = parser.parse_args()

    logger = setup_logging()
    start_time = time.time()

    console.print(
        Panel.fit(
            f"[bold cyan]NYC Taxi Data Lifecycle Pipeline[/bold cyan]\n"
            f"[yellow]Scope:[/yellow] Year {args.year}, Months {args.start_month:02d} to {args.end_month:02d}\n"
            f"[yellow]Services:[/yellow] {', '.join(args.services)}",
            title="🚀 CS341 Pipeline Launch",
            border_style="cyan",
        )
    )

    months = list(range(args.start_month, args.end_month + 1))

    # Phase 1: Ingestion
    logger.info("=== Phase 1: Ingestion & Caching ===")
    ingestor = DataIngestor()
    datasets = ingestor.sync_datasets(args.services, args.year, months)
    logger.info("Ingestion complete. Total datasets ready: %d", len(datasets))

    if not datasets:
        console.print("[bold red]Error: No datasets were downloaded or found. Aborting.[/bold red]")
        sys.exit(1)

    # Phase 2: Data Quality Audit
    logger.info("=== Phase 2: Data Quality & Sanity Validation ===")
    auditor = DataQualityAuditor()
    metrics_list = []
    for service, year, month, path in datasets:
        m = auditor.audit_dataset(service, year, month, path)
        metrics_list.append(m)
    auditor.generate_report(metrics_list)

    # Phase 3: Transformation & Curation
    logger.info("=== Phase 3: Transformation & Curation ===")
    transformer = DataTransformer()
    transformer.process_monthly_curation(datasets)
    transformer.generate_curated_sample(datasets)

    # Phase 4: Analysis & Reporting
    logger.info("=== Phase 4: Downstream Analysis & Output Generation ===")
    analyzer = AnalysisEngine()
    summary = analyzer.generate_h1_summary()
    analyzer.render_visualizations(summary["rankings"])
    analyzer.write_summary_report(summary["rankings"])

    elapsed = time.time() - start_time

    # Display Rich Terminal Output
    table = Table(title="🏆 NYC Taxi H1 2024 Usage Rankings", show_header=True, header_style="bold magenta")
    table.add_column("Rank", justify="center")
    table.add_column("Service Type", justify="left")
    table.add_column("Total Trips", justify="right")
    table.add_column("Market Share", justify="right")
    table.add_column("Total Hours", justify="right")
    table.add_column("Avg Duration", justify="right")

    for r in summary["rankings"]:
        table.add_row(
            f"#{r['rank']}",
            f"[bold]{r['service_type'].upper()}[/bold]",
            f"{r['total_trips']:,}",
            f"{r['market_share_pct']}%",
            f"{r['total_hours']:,.1f} hrs",
            f"{r['overall_avg_duration_min']} min",
        )

    console.print(table)
    console.print(
        Panel(
            f"[bold green]✔ Pipeline finished successfully in {elapsed:.2f} seconds![/bold green]\n"
            f"[dim]Curated datasets saved to data/curated/\n"
            f"Quality report saved to reports/data_quality_report.json\n"
            f"Summary report saved to reports/summary_results.md[/dim]",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()
