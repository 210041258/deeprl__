#!/usr/bin/env python3
"""Run a traffic-control experiment, collect evaluation metrics, and plot them.

Run from any directory with:
    python experiments/run_experiment.py --agent ma2c --scenario large

The project README documents the expected ``main.py`` commands. This helper
checks that entry point exists, launches training/evaluation, then scans the
experiment output for CSV and text log metrics. Matplotlib is only needed for
plot generation; parsed data is also written as CSV.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("experiment_runner")

# Matches metrics in common text-log forms, for example "reward: -1.2" and
# "average_wait=45.0". CSV files are preferred whenever present.
METRIC_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9_ ./-]{0,60}?)\s*(?:=|:)\s*"
    r"(?P<value>-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train/evaluate an agent, parse its results, and create plots."
    )
    parser.add_argument("--agent", choices=("greedy", "ia2c", "ma2c", "iqll", "iqld"), default="ma2c")
    parser.add_argument("--scenario", choices=("large", "real", "gym"), default="large")
    parser.add_argument("--config-dir", type=Path, default=ROOT / "config")
    parser.add_argument(
        "--base-dir", type=Path, default=ROOT / "experiments" / "runs",
        help="Output root; training goes under BASE_DIR/AGENT.",
    )
    parser.add_argument("--seeds", nargs="+", default=["10000", "20000"], help="Evaluation seeds.")
    parser.add_argument("--python", default=sys.executable, help="Python executable for main.py.")
    parser.add_argument("--skip-train", action="store_true", help="Evaluate an existing trained agent.")
    parser.add_argument("--skip-evaluate", action="store_true", help="Only train, then parse available results.")
    parser.add_argument("--demo", action="store_true", help="Pass --demo to evaluation (opens SUMO GUI).")
    parser.add_argument("--metric", help="Optional metric name to plot; default plots discovered metrics.")
    parser.add_argument("--output-dir", type=Path, help="Where parsed CSV and plots are written.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def build_commands(args: argparse.Namespace, base_dir: Path, config_dir: Path) -> List[List[str]]:
    main_py = ROOT / "main.py"
    if not main_py.is_file():
        raise FileNotFoundError(
            f"Expected project entry point at {main_py}. The repository README documents "
            "main.py, but it is not present in this checkout; add/restore it before launching."
        )

    commands: List[List[str]] = []
    if not args.skip_train:
        train_base = base_dir / args.agent
        commands.append([
            args.python, str(main_py), "--base-dir", str(train_base), "train",
            "--config-dir", str(config_dir), "--test-mode", "no_test",
        ])
    if not args.skip_evaluate:
        evaluate = [
            args.python, str(main_py), "--base-dir", str(base_dir), "evaluate",
            "--agents", args.agent, "--evaluation-seeds", *args.seeds,
        ]
        if args.demo:
            evaluate.append("--demo")
        commands.append(evaluate)
    return commands


def run_commands(commands: Iterable[List[str]], dry_run: bool) -> None:
    for command in commands:
        LOG.info("$ %s", " ".join(command))
        if not dry_run:
            subprocess.run(command, cwd=ROOT, check=True)


def read_csv_metrics(path: Path) -> List[Dict[str, object]]:
    """Read numeric CSV columns and retain a source/row identifier."""
    rows: List[Dict[str, object]] = []
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                return rows
            for row_number, row in enumerate(reader, start=1):
                record: Dict[str, object] = {"source": str(path), "row": row_number}
                for name, value in row.items():
                    if not name or value is None:
                        continue
                    try:
                        number = float(value.strip())
                    except (AttributeError, ValueError):
                        continue
                    if number == number and abs(number) != float("inf"):
                        record[name.strip()] = number
                if len(record) > 2:
                    rows.append(record)
    except (OSError, UnicodeError, csv.Error) as exc:
        LOG.warning("Could not read CSV %s: %s", path, exc)
    return rows


def read_text_metrics(path: Path) -> List[Dict[str, object]]:
    """Extract simple key/value numeric metrics from text log lines."""
    rows: List[Dict[str, object]] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            values: Dict[str, object] = {"source": str(path), "row": line_number}
            for match in METRIC_RE.finditer(line):
                key = re.sub(r"\s+", "_", match.group("name").strip()).strip("_-/.")
                if key:
                    try:
                        values[key] = float(match.group("value"))
                    except ValueError:
                        continue
            if len(values) > 2:
                rows.append(values)
    except OSError as exc:
        LOG.warning("Could not read log %s: %s", path, exc)
    return rows


def collect_metrics(base_dir: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    if not base_dir.exists():
        LOG.warning("No experiment output directory found: %s", base_dir)
        return rows
    for path in sorted(base_dir.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".csv":
            rows.extend(read_csv_metrics(path))
        elif suffix in {".log", ".txt"}:
            rows.extend(read_text_metrics(path))
    return rows


def write_metrics(rows: List[Dict[str, object]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row})
    if not columns:
        LOG.warning("No numeric metrics found; not writing an empty CSV.")
        return
    with output_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    LOG.info("Wrote %d parsed rows to %s", len(rows), output_csv)


def plot_metrics(rows: List[Dict[str, object]], output_dir: Path, selected_metric: Optional[str]) -> None:
    numeric_keys = sorted({
        key for row in rows for key, value in row.items()
        if key not in {"source", "row"} and isinstance(value, (int, float))
    })
    if selected_metric:
        numeric_keys = [key for key in numeric_keys if key.lower() == selected_metric.lower()]
        if not numeric_keys:
            LOG.warning("Metric '%s' was not found in parsed results.", selected_metric)
            return
    if not numeric_keys:
        LOG.warning("No numeric metrics available to plot.")
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        LOG.warning("Matplotlib is not installed; parsed CSV is available, but plots were skipped.")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    for metric in numeric_keys:
        points = [(row.get("row", i), row[metric]) for i, row in enumerate(rows) if isinstance(row.get(metric), (int, float))]
        if not points:
            continue
        x_values, y_values = zip(*points)
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.plot(x_values, y_values, marker=".", linewidth=1)
        ax.set(title=metric.replace("_", " ").title(), xlabel="Row / step", ylabel=metric)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", metric).strip("_.") or "metric"
        destination = output_dir / f"{safe_name}.png"
        fig.savefig(destination, dpi=150)
        plt.close(fig)
        LOG.info("Saved plot: %s", destination)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    base_dir = resolve(args.base_dir)
    config_dir = resolve(args.config_dir)
    output_dir = resolve(args.output_dir) if args.output_dir else base_dir / "analysis"

    if not config_dir.is_dir() and not args.skip_train:
        LOG.error("Config directory does not exist: %s", config_dir)
        return 2
    try:
        commands = build_commands(args, base_dir, config_dir)
        run_commands(commands, args.dry_run)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        LOG.error("Experiment command failed: %s", exc)
        return 1

    rows = collect_metrics(base_dir)
    if not rows:
        LOG.warning("No numeric CSV/log metrics discovered under %s", base_dir)
        return 0
    write_metrics(rows, output_dir / "metrics.csv")
    plot_metrics(rows, output_dir, args.metric)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
