"""Analysis and reporting engine to answer the core assignment question."""

import logging
import os
from pathlib import Path
from typing import Dict, List

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
import duckdb
import matplotlib.pyplot as plt

from src.config import CURATED_DIR, REPORTS_DIR

logger = logging.getLogger("pipeline.analysis")


class AnalysisEngine:
    """Answers 'Which taxi type was the most used in H1 2024?' from curated outputs."""

    def __init__(self, con: duckdb.DuckDBPyConnection | None = None):
        self.con = con or duckdb.connect()

    def generate_h1_summary(self) -> Dict[str, List[Dict]]:
        """Compute aggregated H1 2024 statistics by service type."""
        curated_path = CURATED_DIR / "curated_monthly_metrics.parquet"
        if not curated_path.exists():
            raise FileNotFoundError(f"Missing curated metrics at {curated_path}")

        query = f"""
        WITH service_totals AS (
            SELECT
                service_type,
                SUM(trip_count) AS total_trips,
                ROUND(SUM(total_duration_hours), 1) AS total_hours,
                ROUND(AVG(avg_duration_minutes), 1) AS overall_avg_duration_min,
                ROUND(SUM(total_miles), 1) AS total_miles_driven,
                ROUND(AVG(avg_miles), 2) AS overall_avg_miles
            FROM read_parquet('{curated_path.as_posix()}')
            GROUP BY service_type
        ),
        grand_total AS (
            SELECT SUM(total_trips) AS all_trips FROM service_totals
        )
        SELECT
            s.service_type,
            s.total_trips,
            ROUND(s.total_trips * 100.0 / g.all_trips, 2) AS market_share_pct,
            s.total_hours,
            s.overall_avg_duration_min,
            s.total_miles_driven,
            s.overall_avg_miles,
            RANK() OVER (ORDER BY s.total_trips DESC) AS rank
        FROM service_totals s, grand_total g
        ORDER BY s.total_trips DESC;
        """

        results = self.con.sql(query).to_dicts()
        return {"rankings": results}

    def render_visualizations(self, rankings: List[Dict]) -> Path:
        """Render publication-grade visualization chart comparing taxi service usage."""
        chart_path = REPORTS_DIR / "market_share_h1_2024.png"

        labels = [r["service_type"].upper() for r in rankings]
        trips_millions = [r["total_trips"] / 1_000_000.0 for r in rankings]
        shares = [r["market_share_pct"] for r in rankings]

        colors = ["#2b5c8f", "#d97724", "#2ca02c", "#d62728"]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

        # Bar chart
        bars = ax1.bar(labels, trips_millions, color=colors[: len(labels)], edgecolor="black", alpha=0.85)
        ax1.set_title("Total Completed Trips (H1 2024)", fontsize=14, fontweight="bold")
        ax1.set_ylabel("Trips (Millions)", fontsize=12)
        ax1.grid(axis="y", linestyle="--", alpha=0.5)

        for bar in bars:
            height = bar.get_height()
            ax1.annotate(
                f"{height:.2f}M",
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontweight="bold",
            )

        # Pie chart
        wedges, texts, autotexts = ax2.pie(
            shares,
            labels=labels,
            autopct="%1.1f%%",
            startangle=140,
            colors=colors[: len(labels)],
            explode=[0.05 if i == 0 else 0 for i in range(len(labels))],
        )
        for autotext in autotexts:
            autotext.set_color("white")
            autotext.set_fontweight("bold")
        ax2.set_title("Market Share by Trip Volume (H1 2024)", fontsize=14, fontweight="bold")

        plt.suptitle("NYC Taxi & For-Hire Vehicle Usage — First Half of 2024", fontsize=16, fontweight="bold")
        plt.tight_layout()
        plt.savefig(chart_path, dpi=300)
        plt.close(fig)

        logger.info("Saved visualization chart to %s", chart_path)
        return chart_path

    def write_summary_report(self, rankings: List[Dict]) -> Path:
        """Write comprehensive markdown report answering the prompt."""
        report_path = REPORTS_DIR / "summary_results.md"
        winner = rankings[0]

        lines = [
            "# NYC Taxi Analysis (H1 2024) — Summary Results",
            "",
            "## 🏆 Primary Finding & Answer",
            "",
            f"**Winner**: `{winner['service_type'].upper()}` is unequivocally the most used taxi/for-hire service in the first half of 2024.",
            "",
            f"- **Total Completed Trips**: **{winner['total_trips']:,}** rides",
            f"- **Market Share**: **{winner['market_share_pct']}%** of all recorded NYC trips in H1 2024",
            f"- **Cumulative Duration**: **{winner['total_hours']:,.1f}** operational hours",
            "",
            "---",
            "",
            "## 📊 Complete Rankings & Market Breakdown",
            "",
            "| Rank | Service Type | Total Trips | Market Share (%) | Total Hours | Avg Duration (min) | Total Miles | Avg Distance (mi) |",
            "|---|---|---|---|---|---|---|---|",
        ]

        for r in rankings:
            miles_str = f"{r['total_miles_driven']:,.1f}" if r["total_miles_driven"] else "N/A"
            avg_mi_str = f"{r['overall_avg_miles']:.2f}" if r["overall_avg_miles"] else "N/A"
            lines.append(
                f"| #{r['rank']} | **{r['service_type'].upper()}** | {r['total_trips']:,} | {r['market_share_pct']}% | "
                f"{r['total_hours']:,.1f} | {r['overall_avg_duration_min']} min | {miles_str} | {avg_mi_str} mi |"
            )

        lines.extend([
            "",
            "---",
            "",
            "## 🔍 Methodological & Semantic Notes",
            "1. **Uniform Metric Justification**: Total completed valid trip volume is the primary unbiased metric. "
            "Yellow and Green taxis record passenger count, while FHV and HVFHV do not reliably capture passenger numbers. "
            "Using passenger volume would introduce structural bias against for-hire vehicles.",
            "2. **HVFHV Dominance**: High-Volume FHVs (Uber & Lyft) account for the overwhelming majority of trip volume across New York City.",
            "3. **Data Quality Impact**: Strict temporal and logical filters were enforced to eliminate historical date anomalies (e.g. 2008/2088 trips) and negative durations.",
            "",
            "![Market Share Chart](market_share_h1_2024.png)",
        ])

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        logger.info("Saved summary report to %s", report_path)
        return report_path
