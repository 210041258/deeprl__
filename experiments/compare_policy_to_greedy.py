#!/usr/bin/env python3
"""Compare a learned traffic policy with the repository's greedy baseline.

This script analyzes actual per-seed evaluation results in a CSV; it does not
run SUMO or fabricate missing greedy results. Matching rows are paired by seed
and any available context columns to reduce unfair comparisons.

Expected CSV columns (common aliases are supported):
    algorithm,seed,scenario,demand_id,simulator,simulator_version,config_hash,
    mean_travel_time,mean_waiting_time,mean_queue_length,throughput

Example:
    python experiments/compare_policy_to_greedy.py --input evaluation.csv --learned ma2c

Outputs are written to INPUT_PARENT/greedy_comparison/ unless --output-dir is
provided. Positive improvement means the learned policy is better for the
metric's configured direction. Sample SD is NA with fewer than two paired runs.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_METRICS = ("mean_travel_time", "mean_waiting_time", "mean_queue_length", "throughput")
DEFAULT_MATCH = ("seed", "scenario", "demand_id", "demand_file", "network", "simulator",
                 "simulator_version", "config_hash", "control_interval_sec", "objective",
                 "episode_length_sec")
ALIASES = {
    "algorithm": {"algorithm", "agent", "controller", "method"},
    "seed": {"seed", "randomseed", "evaluationseed"},
    "mean_travel_time": {"meantraveltime", "averagetraveltime", "avgtraveltime", "traveltime"},
    "mean_waiting_time": {"meanwaitingtime", "averagewaitingtime", "avgwaitingtime", "waitingtime", "waittime"},
    "mean_queue_length": {"meanqueuelength", "averagequeuelength", "avgqueuelength", "queuelength"},
    "throughput": {"throughput", "vehiclescompleted", "completedvehicles", "departedvehicles"},
}


def normalize(value: object) -> str:
    return "".join(char for char in str(value).strip().lower() if char.isalnum())


def resolve_column(headers: Sequence[str], requested: str) -> Optional[str]:
    wanted = normalize(requested)
    aliases = ALIASES.get(wanted, {wanted})
    for header in headers:
        if normalize(header) == wanted or normalize(header) in aliases:
            return header
    return None


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="CSV containing actual per-seed results.")
    parser.add_argument("--learned", default="ma2c", help="Learned controller label as it appears in the CSV.")
    parser.add_argument("--baseline", default="greedy", help="Baseline controller label (default: greedy).")
    parser.add_argument("--metrics", nargs="+", default=list(DEFAULT_METRICS), help="Metric column names to compare.")
    parser.add_argument("--higher-is-better", nargs="*", default=["throughput"], help="Metrics where larger values are better.")
    parser.add_argument("--match-columns", nargs="+", default=None, help="Pairing columns; seed is always required. Defaults to available standard context columns.")
    parser.add_argument("--output-dir", type=Path, help="Output directory (default: INPUT parent/greedy_comparison).")
    parser.add_argument("--fail-on-unfair", action="store_true", help="Return exit status 1 if pairs are missing or fairness metadata is incomplete.")
    return parser.parse_args(argv)


def finite_number(value: object) -> Optional[float]:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def read_input(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row")
            headers = [header.strip() for header in reader.fieldnames if header]
            rows = [{(key or "").strip(): (value or "").strip() for key, value in row.items()} for row in reader]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"Unable to read {path}: {exc}") from exc
    return rows, headers


def safe_mean(values: List[float]) -> Optional[float]:
    return statistics.mean(values) if values else None


def safe_sd(values: List[float]) -> Optional[float]:
    return statistics.stdev(values) if len(values) >= 2 else None


def compare(rows: List[Dict[str, str]], headers: Sequence[str], args: argparse.Namespace
            ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[str], List[str]]:
    algorithm_column = resolve_column(headers, "algorithm")
    seed_column = resolve_column(headers, "seed")
    if not algorithm_column:
        raise ValueError("Input must have an algorithm/agent/controller/method column.")
    if not seed_column:
        raise ValueError("Input must have a seed column; this comparison requires per-seed pairing.")
    if normalize(args.learned) == normalize(args.baseline):
        raise ValueError("Learned and baseline labels must differ.")

    if args.match_columns:
        requested = args.match_columns
    else:
        requested = [name for name in DEFAULT_MATCH if resolve_column(headers, name)]
    match_columns: List[str] = []
    missing_requested: List[str] = []
    for name in requested:
        resolved = resolve_column(headers, name)
        if resolved and resolved not in match_columns:
            match_columns.append(resolved)
        elif not resolved:
            missing_requested.append(name)
    if seed_column not in match_columns:
        match_columns.insert(0, seed_column)

    metric_columns = {}
    for metric in args.metrics:
        column = resolve_column(headers, metric)
        if column:
            metric_columns[metric] = column
    if not metric_columns:
        raise ValueError("None of the requested metric columns are present in the input CSV.")

    learned_label = normalize(args.learned)
    baseline_label = normalize(args.baseline)
    indexed: Dict[str, Dict[Tuple[str, ...], List[Dict[str, str]]]] = {learned_label: {}, baseline_label: {}}
    dropped_missing = 0
    for row in rows:
        label = normalize(row.get(algorithm_column, ""))
        if label not in indexed:
            continue
        key = tuple(row.get(column, "").strip() for column in match_columns)
        if any(not value for value in key):
            dropped_missing += 1
            continue
        indexed[label].setdefault(key, []).append(row)

    issues: List[str] = []
    if missing_requested:
        issues.append("Requested matching fields were absent: " + ", ".join(missing_requested))
    context_needed = {"scenario", "demandid", "demandfile", "network", "simulator", "simulatorversion", "confighash"}
    absent_context = sorted(context_needed - {normalize(name) for name in match_columns})
    if absent_context:
        issues.append("Fairness metadata is incomplete; missing matching fields: " + ", ".join(absent_context))
    if dropped_missing:
        issues.append(f"Excluded {dropped_missing} relevant row(s) with missing matching-key values.")

    common = set(indexed[learned_label]) & set(indexed[baseline_label])
    paired_keys = []
    duplicate_keys = 0
    for key in sorted(common):
        if len(indexed[learned_label][key]) == 1 and len(indexed[baseline_label][key]) == 1:
            paired_keys.append(key)
        else:
            duplicate_keys += 1
    if duplicate_keys:
        issues.append(f"Excluded {duplicate_keys} duplicate matching key(s); each controller must have exactly one row per key.")
    if not paired_keys:
        issues.append(f"No unambiguous per-seed pairs found for {args.learned} versus {args.baseline}.")

    higher_is_better = {normalize(metric) for metric in args.higher_is_better}
    paired_rows: List[Dict[str, object]] = []
    summaries: List[Dict[str, object]] = []
    fairness = "complete" if not absent_context and not missing_requested else "incomplete"
    for metric, column in metric_columns.items():
        improvements: List[float] = []
        learned_values: List[float] = []
        baseline_values: List[float] = []
        undefined_percent = 0
        for key in paired_keys:
            learned_row = indexed[learned_label][key][0]
            baseline_row = indexed[baseline_label][key][0]
            learned_value = finite_number(learned_row.get(column, ""))
            baseline_value = finite_number(baseline_row.get(column, ""))
            if learned_value is None or baseline_value is None:
                continue
            is_higher = normalize(metric) in higher_is_better
            delta = learned_value - baseline_value if is_higher else baseline_value - learned_value
            percent = None if baseline_value == 0 else delta / abs(baseline_value) * 100.0
            if percent is None:
                undefined_percent += 1
            else:
                improvements.append(percent)
            learned_values.append(learned_value)
            baseline_values.append(baseline_value)
            record: Dict[str, object] = {
                "learned": args.learned, "baseline": args.baseline, "metric": metric,
                "direction": "higher_is_better" if is_higher else "lower_is_better",
                "learned_value": learned_value, "baseline_value": baseline_value,
                "improvement_percent": percent,
                "pair_status": "paired" if fairness == "complete" else "paired_metadata_incomplete",
            }
            record.update({name: value for name, value in zip(match_columns, key)})
            paired_rows.append(record)
        summaries.append({
            "learned": args.learned, "baseline": args.baseline, "metric": metric,
            "direction": "higher_is_better" if normalize(metric) in higher_is_better else "lower_is_better",
            "paired_n": len(learned_values), "mean_learned": safe_mean(learned_values),
            "mean_baseline": safe_mean(baseline_values),
            "mean_improvement_percent": safe_mean(improvements),
            "sample_sd_improvement_percent": safe_sd(improvements),
            "zero_baseline_percent_undefined": undefined_percent,
            "fairness_metadata": fairness,
        })
    return paired_rows, summaries, issues, match_columns


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        # Still create a useful, parseable output file when no pairs exist.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n", encoding="utf-8")
        return
    columns: List[str] = []
    for row in rows:
        for name in row:
            if name not in columns:
                columns.append(name)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: object) -> str:
    return "NA" if value is None else f"{float(value):.2f}"


def write_report(path: Path, input_path: Path, args: argparse.Namespace, match_columns: Sequence[str],
                 summaries: List[Dict[str, object]], issues: Sequence[str]) -> None:
    lines = [
        "# Learned policy vs greedy baseline", "",
        f"- Input results: `{input_path}`", f"- Learned policy label: `{args.learned}`",
        f"- Baseline label: `{args.baseline}`", f"- Pairing columns: {', '.join(f'`{x}`' for x in match_columns)}", "",
        "> This report uses only observed CSV rows. It does not run the simulator or establish that a run completed. A positive improvement means the learned policy is better in the metric's stated direction. Validate the underlying experiment settings before interpreting the comparison.", "",
        "## Paired results summary", "",
        "| Metric | Direction | Paired n | Learned mean | Greedy mean | Mean improvement (%) | Sample SD (%) | Fairness metadata |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summaries:
        lines.append(f"| {row['metric']} | {row['direction']} | {row['paired_n']} | {fmt(row['mean_learned'])} | {fmt(row['mean_baseline'])} | {fmt(row['mean_improvement_percent'])} | {fmt(row['sample_sd_improvement_percent'])} | {row['fairness_metadata']} |")
    lines.extend(["", "## Data and fairness checks", ""])
    lines.extend([f"- **Check:** {item}" for item in issues] if issues else ["- No pairing issues detected for the configured fields. This is not proof of fairness."])
    lines.extend([
        "", "## Interpretation notes", "",
        "- Travel time, waiting time, and queue length default to lower-is-better; throughput defaults to higher-is-better.",
        "- Improvement is computed per paired seed against greedy: `(greedy - learned) / |greedy| × 100` for lower-is-better, and `(learned - greedy) / |greedy| × 100` for higher-is-better.",
        "- Zero baseline values make percentage improvement undefined. Sample SD is NA with fewer than two defined paired improvements.",
        "- Pairing requires exactly one row for each controller per matching key. Duplicated keys are excluded, not averaged.",
        "- Fairness metadata is marked complete only when scenario, demand, network, simulator/version, and config-hash fields are present as matching columns. Matching values do not prove identical execution.",
        "- Only the learned and greedy labels are analyzed. Add no other baseline to the report unless it has actually been run and its results are included in the CSV.", "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    input_path = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else input_path.parent / "greedy_comparison"
    try:
        rows, headers = read_input(input_path)
        paired, summaries, issues, match_columns = compare(rows, headers, args)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "paired_results.csv", paired)
    write_csv(output_dir / "summary.csv", summaries)
    write_report(output_dir / "report.md", input_path, args, match_columns, summaries, issues)
    print(f"Paired result rows: {len(paired)}")
    print(f"Summary: {output_dir / 'summary.csv'}")
    print(f"Report: {output_dir / 'report.md'}")
    return 1 if args.fail_on_unfair and (issues or not paired) else 0


if __name__ == "__main__":
    raise SystemExit(main())
