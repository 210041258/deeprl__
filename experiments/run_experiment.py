#!/usr/bin/env python3
"""Run traffic-control experiments and make a transparent evidence report.

This utility can launch the repository's documented train/evaluate commands,
parse CSV and text logs, plot available numeric series, and write a qualitative
Markdown evidence audit. Evidence statuses describe files/signals found; they
are not scores and do not prove that a method works or that a reported claim is
valid. Review the linked artifacts before drawing conclusions.

Audit existing runs without launching anything:
    python experiments/run_experiment.py --base-dir experiments --skip-train --skip-evaluate

Launch a run and then audit:
    python experiments/run_experiment.py --agent ma2c --scenario large --seeds 11 22 33
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("experiment_runner")
METRIC_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9_ ./-]{0,60}?)\s*(?:=|:)\s*"
    r"(?P<value>-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
)

ALGORITHM_NOTES = {
    "greedy": "Greedy action-selection baseline. The label alone does not establish that it is fixed-time, adaptive, or MaxPressure; inspect its implementation and configuration.",
    "ia2c": "Independent Advantage Actor-Critic (IA2C), an actor-critic method with decentralized agents. This is a method description, not a result claim.",
    "ma2c": "Multi-Agent Advantage Actor-Critic (MA2C), the stabilized IA2C variant described by this project. This is a method description, not a result claim.",
    "iqll": "IQL-L configuration label for an independent Q-learning variant. Verify the exact local-information behavior in the code and config before interpreting it.",
    "iqld": "IQL-D configuration label for an independent Q-learning variant. Verify the exact decentralized behavior in the code and config before interpreting it.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run experiments, parse results, plot metrics, and audit evidence.")
    parser.add_argument("--agent", choices=tuple(ALGORITHM_NOTES), default="ma2c")
    parser.add_argument("--scenario", choices=("large", "real", "gym"), default="large")
    parser.add_argument("--config-dir", type=Path, default=ROOT / "config")
    parser.add_argument("--base-dir", type=Path, default=ROOT / "experiments" / "runs", help="Experiment output root.")
    parser.add_argument("--seeds", nargs="+", default=["10000", "20000"], help="Evaluation seeds.")
    parser.add_argument("--python", default=sys.executable, help="Python executable for main.py.")
    parser.add_argument("--skip-train", action="store_true", help="Do not launch training.")
    parser.add_argument("--skip-evaluate", action="store_true", help="Do not launch evaluation.")
    parser.add_argument("--demo", action="store_true", help="Pass --demo to evaluation (opens SUMO GUI).")
    parser.add_argument("--metric", help="Optional metric name to plot; default plots discovered metrics.")
    parser.add_argument("--output-dir", type=Path, help="Where parsed CSV, plots, and report go.")
    parser.add_argument("--report", type=Path, help="Report path; defaults to OUTPUT_DIR/evidence_report.md.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def build_commands(args: argparse.Namespace, base_dir: Path, config_dir: Path) -> List[List[str]]:
    main_py = ROOT / "main.py"
    if not main_py.is_file():
        raise FileNotFoundError(f"Expected {main_py}; the README documents main.py, but it is not present in this checkout.")
    commands: List[List[str]] = []
    if not args.skip_train:
        commands.append([args.python, str(main_py), "--base-dir", str(base_dir / args.agent), "train",
                         "--config-dir", str(config_dir), "--test-mode", "no_test"])
    if not args.skip_evaluate:
        command = [args.python, str(main_py), "--base-dir", str(base_dir), "evaluate",
                   "--agents", args.agent, "--evaluation-seeds", *args.seeds]
        if args.demo:
            command.append("--demo")
        commands.append(command)
    return commands


def run_commands(commands: Iterable[List[str]], dry_run: bool) -> None:
    for command in commands:
        LOG.info("$ %s", " ".join(command))
        if not dry_run:
            subprocess.run(command, cwd=ROOT, check=True)


def read_csv_metrics(path: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                return rows
            for row_number, row in enumerate(reader, 1):
                record: Dict[str, object] = {"source": str(path), "row": row_number}
                for name, value in row.items():
                    if not name or value is None:
                        continue
                    try:
                        number = float(value.strip())
                    except (AttributeError, ValueError):
                        continue
                    if math.isfinite(number):
                        record[name.strip()] = number
                if len(record) > 2:
                    rows.append(record)
    except (OSError, UnicodeError, csv.Error) as exc:
        LOG.warning("Could not read CSV %s: %s", path, exc)
    return rows


def read_text_metrics(path: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            record: Dict[str, object] = {"source": str(path), "row": line_number}
            for match in METRIC_RE.finditer(line):
                key = re.sub(r"\s+", "_", match.group("name").strip()).strip("_-/.")
                try:
                    number = float(match.group("value"))
                except ValueError:
                    continue
                if key and math.isfinite(number):
                    record[key] = number
            if len(record) > 2:
                rows.append(record)
    except OSError as exc:
        LOG.warning("Could not read log %s: %s", path, exc)
    return rows


def collect_metrics(base_dir: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    if not base_dir.exists():
        LOG.warning("No experiment output directory found: %s", base_dir)
        return rows
    for path in sorted(base_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() == ".csv":
            rows.extend(read_csv_metrics(path))
        elif path.is_file() and path.suffix.lower() in {".log", ".txt"}:
            rows.extend(read_text_metrics(path))
    return rows


def write_metrics(rows: List[Dict[str, object]], output_csv: Path) -> None:
    if not rows:
        return
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row})
    with output_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    LOG.info("Wrote %d parsed rows to %s", len(rows), output_csv)


def plot_metrics(rows: List[Dict[str, object]], output_dir: Path, selected_metric: Optional[str]) -> None:
    keys = sorted({key for row in rows for key, value in row.items()
                   if key not in {"source", "row"} and isinstance(value, (int, float))})
    if selected_metric:
        keys = [key for key in keys if key.lower() == selected_metric.lower()]
        if not keys:
            LOG.warning("Metric '%s' was not found.", selected_metric)
            return
    if not keys:
        LOG.warning("No numeric metrics available to plot.")
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        LOG.warning("Matplotlib is not installed; skipping plots.")
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    for metric in keys:
        points = [(row.get("row", i), row[metric]) for i, row in enumerate(rows)
                  if isinstance(row.get(metric), (int, float))]
        if not points:
            continue
        x_values, y_values = zip(*points)
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.plot(x_values, y_values, marker=".", linewidth=1)
        ax.set(title=metric.replace("_", " ").title(), xlabel="Row / step", ylabel=metric)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", metric).strip("_.") or "metric"
        fig.savefig(output_dir / f"{safe_name}.png", dpi=150)
        plt.close(fig)


def scan_files(roots: Sequence[Path]) -> List[Path]:
    found: Set[Path] = set()
    for root in roots:
        try:
            if root.is_file():
                found.add(root.resolve())
            elif root.is_dir():
                found.update(path.resolve() for path in root.rglob("*") if path.is_file())
        except OSError as exc:
            LOG.debug("Could not scan %s: %s", root, exc)
    return sorted(found)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def evidence_rows(args: argparse.Namespace, base_dir: Path, config_dir: Path) -> List[Tuple[str, str, str, str, List[str]]]:
    roots = [base_dir, config_dir, ROOT / "large_grid", ROOT / "real_net", ROOT / "small_grid", ROOT / "experiments"]
    files = scan_files(roots)
    text: Dict[Path, str] = {}
    readable = {".csv", ".log", ".txt", ".ini", ".yaml", ".yml", ".json", ".xml", ".py", ".md"}
    for path in files:
        if path.suffix.lower() in readable:
            try:
                text[path] = path.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                pass

    def find(pattern: str, include_content: bool = True) -> List[str]:
        regex = re.compile(pattern, re.IGNORECASE)
        hits = [path for path in files if regex.search(path.name)]
        if include_content:
            hits.extend(path for path, body in text.items() if regex.search(body) and path not in hits)
        return sorted({display_path(path) for path in hits})

    training_pattern = r"episode.?reward|train.?reward|global_step|training.?step|converg"
    eval_pattern = r"travel.?time|waiting.?time|wait_time|queue.?length|throughput|eva_data|evaluation"
    training = find(training_pattern)
    evaluation = find(eval_pattern)
    baseline = find(r"fixed.?time|max.?pressure|maxpressure|adaptive|baseline")
    seed_artifacts = find(r"seed|evaluation|eva")
    configured_seeds = {str(seed) for seed in args.seeds}
    for body in text.values():
        for match in re.finditer(r"\bseeds?\b\s*(?:=|:|\s)\s*([0-9][0-9, ]*)", body):
            configured_seeds.update(re.findall(r"\d+", match.group(1)))
    multiple_seeds = len(configured_seeds) >= 2 and bool(seed_artifacts or not args.skip_evaluate)

    simulator = find(r"\.sumocfg$|\.net\.xml$|\.rou\.xml$|\.flow\.xml$|\.netccfg$|cityflow|roadnet|traffic\.json")
    simulator_mentioned = any(any(term in body for term in ("sumo", "cityflow", "simulator", "roadnet")) for body in text.values())
    policies = find(r"\.pkl$|\.pickle$|\.ckpt(?:\.index)?$|\.index$|\.meta$|\.pt$|\.pth$|\.h5$|\.weights$")
    configs = find(r"\.ini$|\.ya?ml$|\.json$|config")
    scripts = find(r"evaluate|eval|run_experiment|\.py$")

    def state(items: List[str]) -> str:
        return "Evidence found" if items else "Not found"

    return [
        ("Training logs", "Episode rewards, training steps, convergence curves", "Whether learning appears to occur", state(training), training[:8]),
        ("Evaluation results", "Mean travel time, waiting time, queue length, throughput", "Whether traffic performance improves", state(evaluation), evaluation[:8]),
        ("Baseline comparison", "Fixed-time, adaptive, and MaxPressure controllers", "Whether the learned method outperforms alternatives", state(baseline), baseline[:8]),
        ("Multiple random seeds", "Mean and standard deviation across independent runs", "Whether improvements are consistent", "Evidence found" if multiple_seeds else ("Partial" if len(configured_seeds) > 1 else "Not found"), seed_artifacts[:8]),
        ("Real simulator execution", "CityFlow engine, road network, demand files", "Whether results represent simulated traffic rather than a mock environment", "Evidence found" if simulator and simulator_mentioned else ("Partial" if simulator_mentioned else "Not found"), simulator[:8]),
        ("Reproducibility", "Configurations, seeds, saved policies, evaluation scripts", "Whether results can be independently reproduced", "Evidence found" if configs and seed_artifacts and policies and scripts else ("Partial" if configs or seed_artifacts or policies or scripts else "Not found"), sorted(set(configs + seed_artifacts + policies + scripts))[:10]),
    ]


def write_evidence_report(args: argparse.Namespace, base_dir: Path, config_dir: Path, report_path: Path) -> None:
    findings = evidence_rows(args, base_dir, config_dir)
    lines = [
        "# Experiment evidence audit", "",
        f"- Selected algorithm: `{args.agent}`",
        f"- Qualitative algorithm note: {ALGORITHM_NOTES[args.agent]}",
        f"- Scenario option: `{args.scenario}`",
        f"- Experiment directory: `{base_dir}`",
        f"- Requested evaluation seeds: `{', '.join(args.seeds)}`", "",
        "> This is a qualitative artifact inventory, not a score or proof of effectiveness. ‘Evidence found’ means the scan found matching files or text; it does not validate their quality, correctness, independence, or conclusions. Verify the artifacts and actual run settings before making claims.", "",
        "## Evidence checklist", "",
        "| Evidence | What to look for | What it establishes | Status | Located evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for category, look_for, establishes, status, evidence in findings:
        refs = ", ".join(f"`{item}`" for item in evidence) if evidence else "None located"
        lines.append(f"| {category} | {look_for} | {establishes} | **{status}** | {refs} |")
    lines.extend([
        "", "## Qualitative algorithm summary", "",
        f"**{args.agent}:** {ALGORITHM_NOTES[args.agent]}", "",
        "No algorithms are ranked and no performance claims are inferred. To establish improvement, compare the learned method with fixed-time, adaptive, and MaxPressure baselines under the same network, traffic demand, simulator version, and evaluation seeds. Calculate and report per-seed metrics and their mean and standard deviation from validated evaluation data; this tool deliberately does not calculate them.", "",
        "## Limitations", "",
        "- The repository documents SUMO. Finding SUMO assets does not prove a run completed, and does not establish CityFlow execution.",
        "- File names and text matches are heuristic; inspect the linked artifacts and execution configuration.",
        "- ‘Not found’ means this scan found no matching artifacts in the configured run, config, and repository environment folders; it is not proof that evidence does not exist elsewhere.",
        "- This report does not compute convergence, travel-time improvement, statistical significance, or mean/standard deviation.", "",
    ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    LOG.info("Wrote qualitative evidence audit to %s", report_path)


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")
    base_dir = resolve(args.base_dir)
    config_dir = resolve(args.config_dir)
    output_dir = resolve(args.output_dir) if args.output_dir else base_dir / "analysis"
    report_path = resolve(args.report) if args.report else output_dir / "evidence_report.md"

    if not config_dir.is_dir() and not args.skip_train:
        LOG.error("Config directory does not exist: %s", config_dir)
        return 2
    try:
        run_commands(build_commands(args, base_dir, config_dir), args.dry_run)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        LOG.error("Experiment command failed: %s", exc)
        return 1

    metrics = collect_metrics(base_dir)
    if metrics:
        write_metrics(metrics, output_dir / "metrics.csv")
        plot_metrics(metrics, output_dir, args.metric)
    else:
        LOG.warning("No numeric CSV/log metrics discovered under %s", base_dir)
    write_evidence_report(args, base_dir, config_dir, report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
