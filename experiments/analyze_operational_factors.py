#!/usr/bin/env python3
"""Explore how recorded operational factors vary with traffic outcomes.

Reads a CSV of evaluation runs and summarizes requested factors (such as demand
level, peak period, weather label, network, simulator version, or control
interval) against numeric outcome metrics. Produces a factor_summary.csv and a
Markdown report. This is descriptive analysis, not causal inference: an
association does not show that a factor caused a performance change.

Example:
    python experiments/analyze_operational_factors.py --input evaluation.csv
    python experiments/analyze_operational_factors.py --input evaluation.csv \\
      --factors scenario demand_level peak_period control_interval_sec \\
      --metrics mean_travel_time mean_waiting_time throughput

Each row should represent a run/seed summary. Include seed and experiment
metadata, and avoid treating repeated observations from the same run as
independent samples.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_METRICS = ("mean_travel_time", "mean_waiting_time", "mean_queue_length", "throughput")
DEFAULT_FACTOR_CANDIDATES = (
    "scenario", "environment", "network", "demand_level", "demand_scale", "demand_id",
    "demand_file", "peak_period", "time_of_day", "weather", "incident", "simulator",
    "simulator_version", "control_interval_sec", "objective", "vehicle_mix",
)
ALIASES = {
    "mean_travel_time": {"meantraveltime", "averagetraveltime", "avgtraveltime", "traveltime"},
    "mean_waiting_time": {"meanwaitingtime", "averagewaitingtime", "avgwaitingtime", "waitingtime", "waittime"},
    "mean_queue_length": {"meanqueuelength", "averagequeuelength", "avgqueuelength", "queuelength"},
    "throughput": {"throughput", "vehiclescompleted", "completedvehicles", "departedvehicles"},
}


def normalize(value: object) -> str:
    return "".join(char for char in str(value).strip().lower() if char.isalnum())


def resolve_column(headers: Sequence[str], requested: str) -> Optional[str]:
    wanted = normalize(requested)
    candidates = ALIASES.get(wanted, {wanted})
    for header in headers:
        if normalize(header) == wanted or normalize(header) in candidates:
            return header
    return None


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="CSV containing run-level results and operational factors.")
    parser.add_argument("--factors", nargs="+", default=None, help="Factor columns to examine; default uses recognized columns present in the CSV.")
    parser.add_argument("--metrics", nargs="+", default=list(DEFAULT_METRICS), help="Numeric outcome metric columns.")
    parser.add_argument("--seed-column", default="seed", help="Optional seed column used to count distinct runs.")
    parser.add_argument("--output-dir", type=Path, help="Output directory (default: INPUT parent/operational_factor_analysis).")
    parser.add_argument("--min-group-size", type=int, default=1, help="Minimum observations for a factor level to appear in the report.")
    parser.add_argument("--max-levels", type=int, default=100, help="Maximum distinct levels per factor; set 0 for no limit.")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def load_csv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row")
            headers = [header.strip() for header in reader.fieldnames if header]
            rows = [{(key or "").strip(): (value or "").strip() for key, value in row.items()} for row in reader]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"Could not read {path}: {exc}") from exc
    if not rows:
        raise ValueError("Input CSV has no data rows")
    return rows, headers


def finite_number(value: object) -> Optional[float]:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def mean(values: List[float]) -> Optional[float]:
    return statistics.mean(values) if values else None


def sd(values: List[float]) -> Optional[float]:
    return statistics.stdev(values) if len(values) >= 2 else None


def analyze(rows: List[Dict[str, str]], factor_columns: Sequence[str], metric_columns: Dict[str, str],
            seed_column: Optional[str], min_group_size: int, max_levels: int
            ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[str]]:
    summaries: List[Dict[str, object]] = []
    checks: List[Dict[str, object]] = []
    notes: List[str] = []
    for factor in factor_columns:
        groups: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        missing_rows = 0
        for row in rows:
            level = row.get(factor, "").strip()
            if not level:
                missing_rows += 1
                continue
            groups[level].append(row)
        if missing_rows:
            checks.append({"factor": factor, "check": "missing_factor_values", "count": missing_rows,
                           "details": "Rows with blank factor values excluded from this factor summary."})
        if not groups:
            notes.append(f"No usable values found for factor '{factor}'.")
            continue
        ordered_levels = sorted(groups, key=lambda level: (-len(groups[level]), level))
        if max_levels > 0 and len(ordered_levels) > max_levels:
            notes.append(f"Factor '{factor}' has {len(ordered_levels)} levels; only the {max_levels} most frequent are summarized.")
            ordered_levels = ordered_levels[:max_levels]
        for level in ordered_levels:
            group = groups[level]
            if len(group) < min_group_size:
                continue
            seed_values = {row.get(seed_column, "").strip() for row in group} if seed_column else set()
            seed_values.discard("")
            base: Dict[str, object] = {
                "factor": factor,
                "factor_level": level,
                "observations": len(group),
                "distinct_seeds": len(seed_values) if seed_column else None,
            }
            for metric, column in metric_columns.items():
                values = [value for row in group if (value := finite_number(row.get(column, ""))) is not None]
                base[f"{metric}_n"] = len(values)
                base[f"{metric}_mean"] = mean(values)
                base[f"{metric}_sd"] = sd(values)
                base[f"{metric}_median"] = statistics.median(values) if values else None
            summaries.append(base)
    return summaries, checks, notes


def write_csv(path: Path, rows: List[Dict[str, object]], empty_fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: List[str] = list(empty_fields)
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: object) -> str:
    if value is None or value == "":
        return "NA"
    try:
        number = float(value)
        return "NA" if not math.isfinite(number) else f"{number:.3f}"
    except (TypeError, ValueError):
        return str(value)


def write_report(path: Path, input_path: Path, rows: List[Dict[str, str]], factors: Sequence[str],
                 metrics: Sequence[str], summaries: List[Dict[str, object]],
                 checks: List[Dict[str, object]], notes: Sequence[str]) -> None:
    lines = [
        "# Operational factors analysis", "",
        f"- Input CSV: `{input_path}`",
        f"- Input rows: {len(rows)}",
        f"- Factors analyzed: {', '.join(f'`{factor}`' for factor in factors) or 'none detected'}",
        f"- Metrics analyzed: {', '.join(f'`{metric}`' for metric in metrics)}", "",
        "> Descriptive summaries only. Differences between factor levels are associations in the supplied data and do not establish that an operational factor caused a result. Confounding variables, simulator settings, and run/seed dependence must be considered.", "",
        "## Factor-level summary", "",
        "| Factor | Level | Observations | Distinct seeds | Metric | Mean | Sample SD | Median | Valid n |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    if not summaries:
        lines.append("| — | — | 0 | NA | — | NA | NA | NA | 0 |")
    else:
        for row in summaries:
            for metric in metrics:
                if f"{metric}_mean" not in row:
                    continue
                lines.append(
                    f"| {row['factor']} | {row['factor_level']} | {row['observations']} | "
                    f"{row['distinct_seeds'] if row['distinct_seeds'] is not None else 'NA'} | {metric} | "
                    f"{fmt(row.get(metric + '_mean'))} | {fmt(row.get(metric + '_sd'))} | "
                    f"{fmt(row.get(metric + '_median'))} | {row.get(metric + '_n', 0)} |"
                )
    lines.extend(["", "## Data checks", ""])
    if checks:
        lines.extend(f"- `{check['factor']}`: {check['details']} Count: {check['count']}." for check in checks)
    else:
        lines.append("- No blank factor values were detected in analyzed factors.")
    lines.extend(f"- Note: {note}" for note in notes)
    lines.extend([
        "", "## Interpretation guidance", "",
        "- Compare factor levels only when other conditions (network, demand, simulator/version, policy, and evaluation protocol) are comparable.",
        "- Means and standard deviations are computed over rows with valid finite metric values. Standard deviation is NA for groups with fewer than two valid observations.",
        "- `distinct_seeds` is a count, not proof that runs are independent. If multiple records share a seed, account for that dependence in any inferential analysis.",
        "- This tool does not fit causal models, test statistical significance, choose optimal operating settings, or generate missing measurements.", "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    input_path = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else input_path.parent / "operational_factor_analysis"
    if args.min_group_size < 1:
        print("Error: --min-group-size must be at least 1.", file=sys.stderr)
        return 2
    try:
        rows, headers = load_csv(input_path)
        if args.factors:
            factors = []
            for requested in args.factors:
                column = resolve_column(headers, requested)
                if column is None:
                    raise ValueError(f"Requested factor column not found: {requested}")
                if column not in factors:
                    factors.append(column)
        else:
            factors = [column for name in DEFAULT_FACTOR_CANDIDATES
                       if (column := resolve_column(headers, name)) is not None]
        if not factors:
            raise ValueError("No operational factor columns detected; pass them explicitly with --factors.")

        metric_columns: Dict[str, str] = {}
        for metric in args.metrics:
            column = resolve_column(headers, metric)
            if column:
                metric_columns[metric] = column
        if not metric_columns:
            raise ValueError("None of the requested metric columns were found in the CSV.")
        seed_column = resolve_column(headers, args.seed_column)
        summaries, checks, notes = analyze(rows, factors, metric_columns, seed_column,
                                           args.min_group_size, args.max_levels)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "operational_factor_summary.csv"
    check_path = output_dir / "operational_factor_checks.csv"
    report_path = output_dir / "operational_factor_report.md"
    write_csv(summary_path, summaries, ("factor", "factor_level", "observations", "distinct_seeds"))
    write_csv(check_path, checks, ("factor", "check", "count", "details"))
    write_report(report_path, input_path, rows, factors, list(metric_columns), summaries, checks, notes)
    print(f"Analyzed {len(rows)} rows across {len(factors)} factor(s).")
    print(f"Summary: {summary_path}")
    print(f"Checks: {check_path}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
