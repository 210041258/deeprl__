#!/usr/bin/env python3
"""Compare a learned traffic controller with fixed-time/adaptive/MaxPressure.

Input is a CSV of per-seed evaluation results. This tool does not run a traffic
simulator or invent missing baseline results. It pairs rows only when seed and
available environment/configuration columns match, flags incomplete metadata,
then computes per-seed percentage improvement and across-seed mean/sample SD.

Minimal CSV example:
    algorithm,seed,scenario,demand_id,simulator,simulator_version,mean_travel_time,mean_waiting_time,mean_queue_length,throughput
    ma2c,1,large,weekday,SUMO,1.1,120,25,8,900
    fixed_time,1,large,weekday,SUMO,1.1,150,35,12,850

Usage:
    python experiments/compare_baselines.py --input evaluation.csv
    python experiments/compare_baselines.py --input evaluation.csv --learned ia2c \\
        --higher-is-better throughput --match-columns seed scenario demand_id simulator simulator_version

The default assumes lower travel time, waiting time, and queue length are better;
throughput is treated as higher-is-better. Specify direction explicitly for any
additional metric. Standard deviation is the sample SD (n-1); it is undefined
for a single paired seed and is reported as NA.
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

LOG = logging.getLogger("baseline_comparison")

DEFAULT_METRICS = ["mean_travel_time", "mean_waiting_time", "mean_queue_length", "throughput"]
DEFAULT_MATCH_COLUMNS = [
    "seed", "scenario", "demand_id", "demand_file", "network", "simulator",
    "simulator_version", "config_hash", "control_interval_sec", "objective",
    "episode_length_sec",
]
ALIASES = {
    "algorithm": {"algorithm", "agent", "controller", "method"},
    "seed": {"seed", "randomseed", "evaluationseed"},
    "mean_travel_time": {"meantraveltime", "averagetraveltime", "avgtraveltime", "traveltime"},
    "mean_waiting_time": {"meanwaitingtime", "averagewaitingtime", "avgwaitingtime", "waitingtime", "waittime"},
    "mean_queue_length": {"meanqueuelength", "averagequeuelength", "avgqueuelength", "queuelength"},
    "throughput": {"throughput", "vehiclescompleted", "completedvehicles", "departedvehicles"},
}


def norm(value: object) -> str:
    """Normalize a label/header without changing its semantic spelling elsewhere."""
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="CSV containing per-seed results for each controller.")
    parser.add_argument("--learned", default="ma2c", help="Learned algorithm label in the CSV (default: ma2c).")
    parser.add_argument("--baselines", nargs="+", default=["fixed_time", "adaptive", "maxpressure"],
                        help="Baseline labels expected in the CSV.")
    parser.add_argument("--metrics", nargs="+", default=DEFAULT_METRICS,
                        help="Metric column names; defaults to travel time, wait, queue length, throughput.")
    parser.add_argument("--higher-is-better", nargs="*", default=["throughput"],
                        help="Metrics where higher values indicate improvement.")
    parser.add_argument("--match-columns", nargs="+", default=None,
                        help="Columns that must match to pair rows. Seed is always required; defaults to seed plus available standard context columns.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory (default: INPUT parent/baseline_comparison).")
    parser.add_argument("--fail-on-unfair", action="store_true", help="Exit nonzero if any baseline lacks paired comparable rows or context metadata is incomplete.")
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
        raise ValueError(f"Cannot read input CSV {path}: {exc}") from exc
    return rows, headers


def resolve_column(headers: Sequence[str], requested: str) -> Optional[str]:
    wanted = norm(requested)
    candidates = ALIASES.get(wanted, {wanted})
    for header in headers:
        if norm(header) == wanted or norm(header) in candidates:
            return header
    return None


def number(value: str) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: List[str] = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(column)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def compare(
    rows: List[Dict[str, str]], headers: Sequence[str], learned: str, baselines: Sequence[str],
    metrics: Sequence[str], higher_is_better: Iterable[str], match_columns: Sequence[str],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[str], List[str]]:
    algorithm_col = resolve_column(headers, "algorithm")
    if not algorithm_col:
        raise ValueError("Missing algorithm/controller column. Use one of: algorithm, agent, controller, method.")
    seed_col = resolve_column(headers, "seed")
    if not seed_col:
        raise ValueError("Missing seed column. Use seed, random_seed, or evaluation_seed; per-seed pairing is required.")

    resolved_match: List[str] = []
    for requested in match_columns:
        column = resolve_column(headers, requested)
        if column and column not in resolved_match:
            resolved_match.append(column)
        elif not column:
            LOG.warning("Requested matching column '%s' is absent; it cannot be checked.", requested)
    if seed_col not in resolved_match:
        resolved_match.insert(0, seed_col)
    if len(resolved_match) == 1:
        LOG.warning("Only seed is available for pairing; environment/demand/simulator fairness cannot be verified from this CSV.")

    metric_columns: Dict[str, str] = {}
    for metric in metrics:
        column = resolve_column(headers, metric)
        if column:
            metric_columns[metric] = column
        else:
            LOG.warning("Metric column '%s' was not found; skipping it.", metric)
    if not metric_columns:
        raise ValueError("None of the requested metric columns were found in the CSV.")

    higher = {norm(metric) for metric in higher_is_better}
    requested_algorithms = [learned, *baselines]
    algorithm_values = {norm(name): name for name in requested_algorithms}
    indexed: Dict[str, Dict[Tuple[str, ...], List[Dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    dropped_missing_key = 0
    for row in rows:
        label = norm(row.get(algorithm_col, ""))
        if label not in algorithm_values:
            continue
        key_values = tuple(row.get(column, "").strip() for column in resolved_match)
        if any(value == "" for value in key_values):
            dropped_missing_key += 1
            continue
        indexed[label][key_values].append(row)
    if dropped_missing_key:
        LOG.warning("Skipped %d relevant row(s) with missing matching-key values.", dropped_missing_key)

    paired_rows: List[Dict[str, object]] = []
    summary_rows: List[Dict[str, object]] = []
    issues: List[str] = []
    expected_context = {"scenario", "demandid", "demandfile", "network", "simulator", "simulatorversion", "confighash"}
    present_context = {norm(column) for column in resolved_match}
    absent_context = sorted(expected_context - present_context)
    fairness_metadata = "complete" if not absent_context else "incomplete; absent: " + ", ".join(absent_context)

    learned_label = norm(learned)
    for baseline in baselines:
        baseline_label = norm(baseline)
        if baseline_label == learned_label:
            issues.append(f"Baseline '{baseline}' is the same label as learned controller '{learned}'.")
            continue
        learned_keys = indexed.get(learned_label, {})
        baseline_keys = indexed.get(baseline_label, {})
        common_keys = sorted(set(learned_keys) & set(baseline_keys))
        unique_pairs: List[Tuple[Tuple[str, ...], Dict[str, str], Dict[str, str]]] = []
        duplicate_keys = 0
        for key in common_keys:
            left, right = learned_keys[key], baseline_keys[key]
            if len(left) != 1 or len(right) != 1:
                duplicate_keys += 1
                continue
            unique_pairs.append((key, left[0], right[0]))
        if not unique_pairs:
            issues.append(f"No unambiguous paired rows found for {learned} vs {baseline}.")
        if duplicate_keys:
            issues.append(f"{learned} vs {baseline}: excluded {duplicate_keys} matching key(s) with duplicate rows.")
        if absent_context:
            issues.append(f"{learned} vs {baseline}: fairness metadata incomplete ({fairness_metadata}).")

        for metric, metric_col in metric_columns.items():
            improvements: List[float] = []
            raw_learned: List[float] = []
            raw_baseline: List[float] = []
            valid_seeds = 0
            for key, learned_row, baseline_row in unique_pairs:
                learned_value = number(learned_row.get(metric_col, ""))
                baseline_value = number(baseline_row.get(metric_col, ""))
                if learned_value is None or baseline_value is None:
                    continue
                if norm(metric) in higher:
                    change = learned_value - baseline_value
                else:
                    change = baseline_value - learned_value
                improvement_pct = None if baseline_value == 0 else change / abs(baseline_value) * 100.0
                output: Dict[str, object] = {
                    "learned": learned, "baseline": baseline, "metric": metric,
                    "higher_is_better": norm(metric) in higher,
                    "learned_value": learned_value, "baseline_value": baseline_value,
                    "improvement_percent": improvement_pct,
                    "match_status": "paired" if not absent_context else "paired_metadata_incomplete",
                }
                output.update({column: value for column, value in zip(resolved_match, key)})
                paired_rows.append(output)
                raw_learned.append(learned_value)
                raw_baseline.append(baseline_value)
                valid_seeds += 1
                if improvement_pct is not None:
                    improvements.append(improvement_pct)
            summary_rows.append({
                "learned": learned,
                "baseline": baseline,
                "metric": metric,
                "direction": "higher_is_better" if norm(metric) in higher else "lower_is_better",
                "paired_n": valid_seeds,
                "mean_learned": statistics.mean(raw_learned) if raw_learned else None,
                "mean_baseline": statistics.mean(raw_baseline) if raw_baseline else None,
                "mean_improvement_percent": statistics.mean(improvements) if improvements else None,
                "sample_sd_improvement_percent": statistics.stdev(improvements) if len(improvements) >= 2 else None,
                "fairness_metadata": fairness_metadata,
            })
    return paired_rows, summary_rows, issues, resolved_match


def fmt(value: object, digits: int = 2) -> str:
    if value is None or value == "":
        return "NA"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def write_report(
    path: Path, input_path: Path, learned: str, baselines: Sequence[str], match_columns: Sequence[str],
    paired: List[Dict[str, object]], summaries: List[Dict[str, object]], issues: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Baseline comparison report", "",
        f"- Input data: `{input_path}`",
        f"- Learned controller: `{learned}`",
        f"- Requested baselines: {', '.join(f'`{name}`' for name in baselines)}",
        f"- Pairing columns: {', '.join(f'`{name}`' for name in match_columns)}", "",
        "> Results are calculated only from rows present in the input CSV. A positive improvement means the learned controller is better in the configured metric direction. This report does not establish that the experiment itself was valid; confirm simulator, demand, network, and configuration metadata.", "",
        "## Summary across paired runs", "",
        "| Learned | Baseline | Metric | Paired n | Learned mean | Baseline mean | Mean improvement (%) | Sample SD (%) | Fairness metadata |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    if summaries:
        for row in summaries:
            lines.append(
                f"| {row['learned']} | {row['baseline']} | {row['metric']} | {row['paired_n']} | "
                f"{fmt(row['mean_learned'])} | {fmt(row['mean_baseline'])} | "
                f"{fmt(row['mean_improvement_percent'])} | {fmt(row['sample_sd_improvement_percent'])} | {row['fairness_metadata']} |"
            )
    else:
        lines.append("| — | — | — | 0 | NA | NA | NA | NA | No comparisons generated |")
    lines.extend(["", "## Fairness and data checks", ""])
    if issues:
        lines.extend(f"- **Check:** {issue}" for issue in issues)
    else:
        lines.append("- No pairing issues detected for the configured columns. This is not a guarantee of experimental fairness.")
    lines.extend([
        "", "## Interpretation", "",
        "- Travel time, waiting time, and queue length use lower-is-better by default; throughput uses higher-is-better. Override directions with `--higher-is-better` when appropriate.",
        "- Improvement is computed per paired seed relative to the baseline: `(baseline - learned) / |baseline| * 100` for lower-is-better, or `(learned - baseline) / |baseline| * 100` for higher-is-better. A zero baseline makes the percentage undefined.",
        "- The reported mean and sample standard deviation summarize per-seed percentage improvements. SD is NA with fewer than two valid paired seeds.",
        "- A row is paired only when matching-column values agree and exactly one row exists for each controller/key. Duplicated keys are excluded rather than silently averaged.",
        "- Fairness metadata is considered complete only when scenario, demand, network, simulator, simulator version, and config hash columns are available as matching fields. Review the values yourself; matching labels do not prove identical execution.",
        "- Missing baselines or metrics are not synthesized. Add actual per-seed evaluation results for fixed-time, adaptive, and MaxPressure before drawing comparisons.", "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")
    input_path = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else input_path.parent / "baseline_comparison"
    try:
        rows, headers = load_csv(input_path)
        match_columns = args.match_columns or [column for column in DEFAULT_MATCH_COLUMNS if resolve_column(headers, column)]
        paired, summaries, issues, resolved_match = compare(
            rows, headers, args.learned, args.baselines, args.metrics, args.higher_is_better, match_columns,
        )
    except (OSError, ValueError) as exc:
        LOG.error("%s", exc)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "paired_results.csv", paired)
    write_csv(output_dir / "summary.csv", summaries)
    write_report(output_dir / "report.md", input_path, args.learned, args.baselines,
                 resolved_match, paired, summaries, issues)
    LOG.info("Paired rows: %d; summary rows: %d", len(paired), len(summaries))
    LOG.info("Wrote comparison outputs to %s", output_dir)
    if args.fail_on_unfair and (issues or any(row["paired_n"] == 0 for row in summaries)):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
