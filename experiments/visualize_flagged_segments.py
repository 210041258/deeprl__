#!/usr/bin/env python3
"""Visualize segment-level traffic flags from flag_segments.R output.

Creates a status-count chart, a per-segment metric chart, a segment summary CSV,
and—when coordinate columns are supplied—a point map of segment statuses.
This plots segment coordinates as points; it does not draw road geometry.

Example:
    python experiments/visualize_flagged_segments.py \
      --input segment_metrics_flagged.csv --metric mean_queue_length

With segment coordinates:
    python experiments/visualize_flagged_segments.py \
      --input segment_metrics_flagged.csv --metric mean_queue_length \
      --x-column longitude --y-column latitude

Requires matplotlib for PNG output. The segment summary CSV is still generated
if matplotlib is unavailable. Thresholds and flags come from the input file.
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

LOG = logging.getLogger("flagged_segment_visualizer")
SEVERITY = {"NO_DATA": 0, "NORMAL": 1, "WARNING": 2, "CRITICAL": 3}
COLORS = {"NO_DATA": "#9e9e9e", "NORMAL": "#2e8b57", "WARNING": "#f0ad4e", "CRITICAL": "#d9534f"}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="CSV produced by flag_segments.R.")
    parser.add_argument("--segment-column", default="segment_id", help="Segment identifier column.")
    parser.add_argument("--metric", help="Metric column to plot; auto-detected from *_numeric or flag_metric if omitted.")
    parser.add_argument("--flag-column", default="segment_flag", help="Flag column (NORMAL/WARNING/CRITICAL/NO_DATA).")
    parser.add_argument("--time-column", help="Optional timestamp column; latest row supplies displayed metric and coordinates.")
    parser.add_argument("--x-column", help="Optional segment x/longitude coordinate column.")
    parser.add_argument("--y-column", help="Optional segment y/latitude coordinate column.")
    parser.add_argument("--output-dir", type=Path, help="Output directory (default: INPUT parent/segment_visualization).")
    parser.add_argument("--max-segments", type=int, default=80, help="Maximum segments shown in metric bar chart; 0 means all.")
    parser.add_argument("--title", default="Flagged road segments", help="Plot title.")
    parser.add_argument("--show", action="store_true", help="Open plots interactively as well as saving PNGs.")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def read_rows(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row")
            headers = [h.strip() for h in reader.fieldnames if h]
            rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"Could not read {path}: {exc}") from exc
    if not rows:
        raise ValueError("CSV contains no data rows")
    return rows, headers


def finite_number(value: object) -> Optional[float]:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_time(value: str) -> Optional[datetime]:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def choose_metric(rows: List[Dict[str, str]], headers: Sequence[str], requested: Optional[str]) -> str:
    if requested:
        if requested not in headers:
            raise ValueError(f"Metric column not found: {requested}")
        return requested
    for row in rows:
        name = row.get("flag_metric", "").strip()
        if name in headers:
            return name
        candidate = f"{name}_numeric" if name else ""
        if candidate in headers:
            return candidate
    candidates = [h for h in headers if h.endswith("_numeric")]
    if candidates:
        return candidates[0]
    raise ValueError("Could not infer metric column; specify it with --metric.")


def summarize_segments(rows: List[Dict[str, str]], segment_col: str, flag_col: str,
                       metric_col: str, time_col: Optional[str], x_col: Optional[str],
                       y_col: Optional[str]) -> List[Dict[str, object]]:
    groups: Dict[str, List[Tuple[int, Dict[str, str]]]] = defaultdict(list)
    for index, row in enumerate(rows):
        segment = row.get(segment_col, "").strip()
        if segment:
            groups[segment].append((index, row))
    if not groups:
        raise ValueError(f"No non-empty segment IDs found in column '{segment_col}'.")

    output: List[Dict[str, object]] = []
    for segment, indexed_rows in groups.items():
        flags = [row.get(flag_col, "NO_DATA").strip().upper() for _, row in indexed_rows]
        unknown = sorted(set(flags) - set(SEVERITY))
        if unknown:
            raise ValueError(f"Unexpected flag(s) for segment {segment}: {', '.join(unknown)}")
        worst_flag = max(flags, key=lambda flag: SEVERITY[flag])

        if time_col:
            parsed = [(parse_time(row.get(time_col, "")), index, row) for index, row in indexed_rows]
            valid_times = [item for item in parsed if item[0] is not None]
            latest = max(valid_times, key=lambda item: (item[0], item[1]))[2] if valid_times else indexed_rows[-1][1]
        else:
            latest = indexed_rows[-1][1]

        metric = finite_number(latest.get(metric_col, ""))
        record: Dict[str, object] = {
            segment_col: segment,
            "segment_flag": worst_flag,
            "latest_metric": metric,
            "metric_column": metric_col,
            "observations": len(indexed_rows),
            "critical_observations": sum(flag == "CRITICAL" for flag in flags),
            "warning_observations": sum(flag == "WARNING" for flag in flags),
            "latest_time": latest.get(time_col, "") if time_col else "",
        }
        if x_col:
            record[x_col] = finite_number(latest.get(x_col, ""))
        if y_col:
            record[y_col] = finite_number(latest.get(y_col, ""))
        output.append(record)
    return sorted(output, key=lambda row: str(row[segment_col]))


def write_summary(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: List[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def create_plots(summary: List[Dict[str, object]], output_dir: Path, args: argparse.Namespace,
                 segment_col: str) -> List[Path]:
    try:
        import matplotlib
        if not args.show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("Matplotlib is required for plots. Install it with: python -m pip install matplotlib") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: List[Path] = []
    counts = Counter(str(row["segment_flag"]) for row in summary)
    statuses = ["NORMAL", "WARNING", "CRITICAL", "NO_DATA"]
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(statuses, [counts.get(status, 0) for status in statuses],
                  color=[COLORS[status] for status in statuses])
    ax.set(title=f"{args.title}: segment status counts", xlabel="Status", ylabel="Number of segments")
    ax.grid(axis="y", alpha=0.25)
    for bar in bars:
        ax.annotate(f"{int(bar.get_height())}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    ha="center", va="bottom")
    fig.tight_layout()
    path = output_dir / "segment_status_counts.png"
    fig.savefig(path, dpi=160)
    outputs.append(path)

    metric_rows = [row for row in summary if isinstance(row.get("latest_metric"), (int, float))]
    metric_rows.sort(key=lambda row: (SEVERITY[str(row["segment_flag"])], float(row["latest_metric"])), reverse=True)
    if args.max_segments > 0:
        metric_rows = metric_rows[:args.max_segments]
    if metric_rows:
        # Reverse ordering so the most severe/highest items are at the top visually.
        metric_rows = list(reversed(metric_rows))
        fig_height = max(5.0, min(18.0, 0.28 * len(metric_rows) + 2.0))
        fig, ax = plt.subplots(figsize=(11, fig_height))
        labels = [str(row[segment_col]) for row in metric_rows]
        values = [float(row["latest_metric"]) for row in metric_rows]
        colors = [COLORS[str(row["segment_flag"])] for row in metric_rows]
        ax.barh(labels, values, color=colors)
        ax.set(title=f"{args.title}: {args.metric or metric_rows[0]['metric_column']}",
               xlabel=str(metric_rows[0]["metric_column"]), ylabel="Segment")
        ax.grid(axis="x", alpha=0.25)
        fig.tight_layout()
        path = output_dir / "segment_metric_by_id.png"
        fig.savefig(path, dpi=160)
        outputs.append(path)

    if args.x_column and args.y_column:
        coordinates = [row for row in summary
                       if isinstance(row.get(args.x_column), (int, float))
                       and isinstance(row.get(args.y_column), (int, float))]
        if not coordinates:
            LOG.warning("Coordinate columns supplied, but no rows have valid numeric coordinates.")
        else:
            fig, ax = plt.subplots(figsize=(9, 7))
            for status in statuses:
                selected = [row for row in coordinates if row["segment_flag"] == status]
                if selected:
                    ax.scatter([row[args.x_column] for row in selected],
                               [row[args.y_column] for row in selected],
                               label=f"{status} ({len(selected)})", c=COLORS[status], s=55, alpha=0.85,
                               edgecolors="white", linewidths=0.4)
            ax.set(title=f"{args.title}: segment locations (points)", xlabel=args.x_column, ylabel=args.y_column)
            ax.legend()
            ax.grid(alpha=0.2)
            fig.tight_layout()
            path = output_dir / "segment_status_map.png"
            fig.savefig(path, dpi=160)
            outputs.append(path)

    if args.show:
        plt.show()
    plt.close("all")
    return outputs


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")
    input_path = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else input_path.parent / "segment_visualization"
    try:
        rows, headers = read_rows(input_path)
        for column in (args.segment_column, args.flag_column):
            if column not in headers:
                raise ValueError(f"Required column not found: {column}")
        if args.time_column and args.time_column not in headers:
            raise ValueError(f"Time column not found: {args.time_column}")
        if bool(args.x_column) != bool(args.y_column):
            raise ValueError("Provide both --x-column and --y-column for a coordinate plot.")
        for column in (args.x_column, args.y_column):
            if column and column not in headers:
                raise ValueError(f"Coordinate column not found: {column}")
        metric_col = choose_metric(rows, headers, args.metric)
        summary = summarize_segments(rows, args.segment_column, args.flag_column, metric_col,
                                     args.time_column, args.x_column, args.y_column)
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "segment_summary.csv"
        write_summary(summary_path, summary)
        plots = create_plots(summary, output_dir, args, args.segment_column)
    except (OSError, ValueError, RuntimeError) as exc:
        LOG.error("%s", exc)
        return 2

    counts = Counter(str(row["segment_flag"]) for row in summary)
    print(f"Segments summarized: {len(summary)}")
    print("Status counts: " + ", ".join(f"{name}={counts.get(name, 0)}" for name in ("NORMAL", "WARNING", "CRITICAL", "NO_DATA")))
    print(f"Summary CSV: {summary_path}")
    for path in plots:
        print(f"Plot: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
