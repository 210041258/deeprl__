#!/usr/bin/env python3
"""Validate traffic-control experiment result CSVs before analysis.

Checks required columns, blank/malformed values, numeric metric validity,
duplicate controller/seed/context keys, and missing comparison metadata. It
writes a Markdown report and a row-level issue CSV. Validation is structural:
it does not certify simulator execution, scientific validity, or fairness.

Example:
    python experiments/validate_results.py --input evaluation.csv
    python experiments/validate_results.py --input evaluation.csv \\
      --environment-column scenario --algorithm-column agent \\
      --metrics mean_travel_time mean_waiting_time throughput
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_METRICS = ("mean_travel_time", "mean_waiting_time", "mean_queue_length", "throughput")
DEFAULT_CONTEXT = (
    "scenario", "demand_id", "demand_file", "network", "simulator",
    "simulator_version", "config_hash",
)
ALIASES = {
    "algorithm": {"algorithm", "agent", "controller", "method"},
    "seed": {"seed", "randomseed", "evaluationseed"},
    "environment": {"environment", "env", "scenario", "network"},
    "mean_travel_time": {"meantraveltime", "averagetraveltime", "avgtraveltime", "traveltime"},
    "mean_waiting_time": {"meanwaitingtime", "averagewaitingtime", "avgwaitingtime", "waitingtime", "waittime"},
    "mean_queue_length": {"meanqueuelength", "averagequeuelength", "avgqueuelength", "queuelength"},
    "throughput": {"throughput", "vehiclescompleted", "completedvehicles", "departedvehicles"},
}


def normalize(value: object) -> str:
    return "".join(character for character in str(value).strip().lower() if character.isalnum())


def resolve_column(headers: Sequence[str], requested: str) -> Optional[str]:
    wanted = normalize(requested)
    aliases = ALIASES.get(wanted, {wanted})
    for header in headers:
        if normalize(header) == wanted or normalize(header) in aliases:
            return header
    return None


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="Evaluation results CSV to validate.")
    parser.add_argument("--algorithm-column", default="algorithm", help="Controller label column; common aliases are accepted.")
    parser.add_argument("--seed-column", default="seed", help="Evaluation seed column; common aliases are accepted.")
    parser.add_argument("--environment-column", default=None, help="Optional environment/scenario column name.")
    parser.add_argument("--metrics", nargs="+", default=list(DEFAULT_METRICS), help="Numeric metric columns to validate.")
    parser.add_argument("--context-columns", nargs="+", default=None, help="Context fields required for fairness review. Defaults to available standard fields.")
    parser.add_argument("--key-columns", nargs="+", default=None, help="Columns used for duplicate detection. Defaults to controller, seed, and available context columns.")
    parser.add_argument("--nonnegative-metrics", nargs="*", default=list(DEFAULT_METRICS), help="Metrics that must be zero or greater.")
    parser.add_argument("--output-dir", type=Path, help="Report directory (default: INPUT parent/validation).")
    parser.add_argument("--strict", action="store_true", help="Exit with status 1 for warnings as well as errors.")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def issue(severity: str, code: str, message: str, row: Optional[int] = None,
          column: Optional[str] = None, value: Optional[str] = None) -> Dict[str, object]:
    return {"severity": severity, "code": code, "row": row or "", "column": column or "",
            "value": value or "", "message": message}


def read_csv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row")
            headers = [header.strip() for header in reader.fieldnames if header]
            rows: List[Dict[str, str]] = []
            for row in reader:
                rows.append({(key or "").strip(): (value or "").strip() for key, value in row.items()})
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"Unable to read CSV '{path}': {exc}") from exc
    return rows, headers


def numeric_value(value: str) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def write_issues(path: Path, issues: List[Dict[str, object]]) -> None:
    fields = ("severity", "code", "row", "column", "value", "message")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(issues)


def validate(rows: List[Dict[str, str]], headers: Sequence[str], args: argparse.Namespace
             ) -> Tuple[List[Dict[str, object]], List[str], List[str]]:
    issues: List[Dict[str, object]] = []
    warnings: List[str] = []
    errors: List[str] = []

    algorithm_col = resolve_column(headers, args.algorithm_column)
    seed_col = resolve_column(headers, args.seed_column)
    env_col = resolve_column(headers, args.environment_column) if args.environment_column else resolve_column(headers, "environment")
    if not algorithm_col:
        issues.append(issue("ERROR", "missing_algorithm_column", "No algorithm/controller column found."))
        errors.append("Algorithm/controller column is required.")
    if not seed_col:
        issues.append(issue("ERROR", "missing_seed_column", "No seed column found; cannot validate independent runs."))
        errors.append("Seed column is required.")
    if args.environment_column and not env_col:
        issues.append(issue("ERROR", "missing_environment_column", f"Requested environment column '{args.environment_column}' was not found."))
        errors.append(f"Environment column '{args.environment_column}' was not found.")

    metric_columns: Dict[str, str] = {}
    for metric in args.metrics:
        column = resolve_column(headers, metric)
        if column:
            metric_columns[metric] = column
        else:
            issues.append(issue("ERROR", "missing_metric", f"Requested metric '{metric}' is absent from the CSV.", column=metric))
            errors.append(f"Metric column '{metric}' is missing.")
    if not rows:
        issues.append(issue("ERROR", "empty_data", "CSV contains no data rows."))
        errors.append("CSV contains no data rows.")
        return issues, warnings, errors

    resolved_context: List[str] = []
    requested_context = args.context_columns if args.context_columns else list(DEFAULT_CONTEXT)
    for requested in requested_context:
        column = resolve_column(headers, requested)
        if column:
            if column not in resolved_context:
                resolved_context.append(column)
        elif args.context_columns:
            issues.append(issue("WARNING", "missing_context_column", f"Context column '{requested}' is absent.", column=requested))
            warnings.append(f"Context field '{requested}' is missing; comparison fairness cannot be checked for it.")

    if not resolved_context:
        issues.append(issue("WARNING", "no_context_metadata", "No standard comparison context columns were found."))
        warnings.append("No scenario/demand/network/simulator/config metadata was found.")

    for index, row in enumerate(rows, start=2):  # CSV header is row 1
        if not any(value.strip() for value in row.values()):
            issues.append(issue("WARNING", "blank_row", "Blank CSV row.", row=index))
            warnings.append(f"Blank row at CSV line {index}.")
            continue
        for column in (algorithm_col, seed_col, env_col):
            if column and not row.get(column, "").strip():
                issues.append(issue("ERROR", "missing_identifier", "Required identifier is blank.", row=index, column=column))
                errors.append(f"Line {index}: missing {column} value.")
        for metric, column in metric_columns.items():
            raw = row.get(column, "").strip()
            value = numeric_value(raw)
            if not raw:
                issues.append(issue("ERROR", "missing_metric_value", f"Metric '{metric}' is blank.", row=index, column=column))
                errors.append(f"Line {index}: missing {metric}.")
            elif value is None:
                issues.append(issue("ERROR", "invalid_metric_value", f"Metric '{metric}' must be finite numeric data.", row=index, column=column, value=raw))
                errors.append(f"Line {index}: invalid numeric value for {metric}: {raw!r}.")
            elif normalize(metric) in {normalize(item) for item in args.nonnegative_metrics} and value < 0:
                issues.append(issue("ERROR", "negative_metric", f"Metric '{metric}' must be nonnegative.", row=index, column=column, value=raw))
                errors.append(f"Line {index}: negative value for nonnegative metric {metric}.")

    if algorithm_col and seed_col:
        key_columns: List[str] = [algorithm_col, seed_col]
        if args.key_columns:
            key_columns = []
            for requested in args.key_columns:
                column = resolve_column(headers, requested)
                if column and column not in key_columns:
                    key_columns.append(column)
                elif not column:
                    issues.append(issue("WARNING", "missing_key_column", f"Duplicate-check column '{requested}' is absent.", column=requested))
                    warnings.append(f"Duplicate-check column '{requested}' is missing.")
            if algorithm_col not in key_columns:
                key_columns.insert(0, algorithm_col)
            if seed_col not in key_columns:
                key_columns.insert(1, seed_col)
        else:
            key_columns.extend(column for column in resolved_context if column not in key_columns)

        seen: Dict[Tuple[str, ...], int] = {}
        duplicates: List[Tuple[int, Tuple[str, ...], int]] = []
        for index, row in enumerate(rows, start=2):
            key = tuple(row.get(column, "").strip() for column in key_columns)
            if any(not value for value in key):
                continue
            if key in seen:
                duplicates.append((index, key, seen[key]))
            else:
                seen[key] = index
        for row_number, key, first_row in duplicates:
            issues.append(issue("ERROR", "duplicate_run_key", f"Duplicate run key; first seen on CSV line {first_row}.", row=row_number, value=" | ".join(key)))
            errors.append(f"Line {row_number}: duplicate controller/seed/context key (first at line {first_row}).")

        labels = Counter(row.get(algorithm_col, "").strip() for row in rows if row.get(algorithm_col, "").strip())
        if len(labels) < 2:
            issues.append(issue("WARNING", "single_controller", "Only one controller label found; baseline comparison is not possible."))
            warnings.append("Only one controller is present; comparative analysis needs actual baseline rows.")
        if seed_col:
            seeds_per_label: Dict[str, set] = defaultdict(set)
            for row in rows:
                label = row.get(algorithm_col, "").strip()
                seed = row.get(seed_col, "").strip()
                if label and seed:
                    seeds_per_label[label].add(seed)
            if len(seeds_per_label) > 1:
                all_seed_sets = list(seeds_per_label.values())
                if any(seed_set != all_seed_sets[0] for seed_set in all_seed_sets[1:]):
                    issues.append(issue("WARNING", "unmatched_seed_sets", "Controller rows do not all contain the same seed set."))
                    warnings.append("Controllers have different seed sets; paired comparisons may have fewer runs.")

    status = "ERROR" if errors else ("WARNING" if warnings else "OK")
    issues.append(issue("INFO", "validation_status", f"Validation status: {status}; rows checked: {len(rows)}."))
    return issues, warnings, errors


def write_report(path: Path, input_path: Path, headers: Sequence[str], row_count: int,
                 issues: List[Dict[str, object]], warnings: List[str], errors: List[str]) -> None:
    error_count = sum(item["severity"] == "ERROR" for item in issues)
    warning_count = sum(item["severity"] == "WARNING" for item in issues)
    status = "FAIL" if error_count else ("PASS WITH WARNINGS" if warning_count else "PASS")
    lines = [
        "# Experiment results validation", "",
        f"- Input: `{input_path}`", f"- Rows: {row_count}",
        f"- Columns: {', '.join(f'`{name}`' for name in headers)}",
        f"- Status: **{status}**", f"- Errors: {error_count}", f"- Warnings: {warning_count}", "",
        "> Structural validation only. A passing CSV does not prove that the simulator ran, that results are scientifically valid, or that controllers were evaluated under identical conditions.", "",
        "## Errors", "",
    ]
    lines.extend([f"- {message}" for message in errors] or ["- None"])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {message}" for message in warnings] or ["- None"])
    lines.extend(["", "## Issue details", "", "See the accompanying `validation_issues.csv` for row-level issue codes and values.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    input_path = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else input_path.parent / "validation"
    try:
        rows, headers = read_csv(input_path)
        issues, warnings, errors = validate(rows, headers, args)
    except (OSError, ValueError) as exc:
        print(f"Validation could not run: {exc}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    issues_path = output_dir / "validation_issues.csv"
    report_path = output_dir / "validation_report.md"
    write_issues(issues_path, issues)
    write_report(report_path, input_path, headers, len(rows), issues, warnings, errors)
    error_count = sum(item["severity"] == "ERROR" for item in issues)
    warning_count = sum(item["severity"] == "WARNING" for item in issues)
    print(f"Rows checked: {len(rows)}; errors: {error_count}; warnings: {warning_count}")
    print(f"Report: {report_path}")
    print(f"Issue CSV: {issues_path}")
    if error_count:
        return 1
    if args.strict and warning_count:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
