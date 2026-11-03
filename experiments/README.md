# Experiments

This directory holds experiment outputs, evaluation artifacts, analysis utilities, and a presentation related to the repository’s multi-agent reinforcement-learning traffic-signal experiments. The project’s simulator, environment setup, and training instructions are documented in the [root README](../README.md).

## Directory contents

| Path | Purpose |
| --- | --- |
| [`greedy/`](greedy/) | Greedy-controller experiment artifacts. |
| [`ia2c/`](ia2c/) | IA2C experiment artifacts. |
| [`iqld/`](iqld/) | IQL-D experiment artifacts. |
| [`iqll/`](iqll/) | IQL-L experiment artifacts. |
| [`ma2c/`](ma2c/) | MA2C experiment artifacts. |
| [`test/`](test/) | Test-run artifacts. |
| [`eva_log/`](eva_log/) | Evaluation logs. |
| [`MARL_Traffic_Flow_Presentation_With_Graphs.pdf`](MARL_Traffic_Flow_Presentation_With_Graphs.pdf) | Presentation with traffic-flow graphs. |
| [`run_experiment.py`](run_experiment.py) | Python helper to launch documented runs, parse supported logs, plot metrics, and create a qualitative evidence audit. |
| [`compare_baselines.py`](compare_baselines.py) | Compare per-seed result CSVs for a learned controller and baseline controllers. |
| [`compare_baselines.R`](compare_baselines.R) | Base-R alternative for paired multi-seed baseline comparison. |
| [`flag_segments.R`](flag_segments.R) | Add threshold-based traffic-condition flags to per-segment CSV records. |
| [`summarize_environment_results.R`](summarize_environment_results.R) | Summarize metrics grouped by environment and controller. |

Experiment subdirectories may contain `data/`, `log/`, and `eva_log/` folders. Their presence does not by itself prove a run completed or that its results are valid.

## Analysis tools

### Summarize environment results

Prepare a CSV with environment, algorithm/controller, and metric columns. Each row should represent a clearly identified evaluation observation, preferably with a seed column.

```bash
Rscript experiments/summarize_environment_results.R --input evaluation.csv
```

The script writes `environment_summary.csv` and `environment_report.md` to an `environment_summary/` folder beside the input CSV by default. It reports per-group counts, means, sample standard deviations, medians, minima, and maxima. To use different column names or metrics:

```bash
Rscript experiments/summarize_environment_results.R \
  --input evaluation.csv \
  --environment-column scenario \
  --algorithm-column agent \
  --seed-column evaluation_seed \
  --metrics mean_travel_time mean_waiting_time throughput
```

The output summarizes only the values in the input; it does not run SUMO, fill missing values, test significance, or establish that observations are independent.

### Compare controllers

The Python and R baseline tools require actual per-seed results for the learned controller and the baselines. Their CSV should include a controller label, seed, metrics, and ideally scenario, demand/network, simulator/version, and configuration identifiers.

```bash
python experiments/compare_baselines.py --input evaluation.csv
Rscript experiments/compare_baselines.R --input evaluation.csv
```

Both produce paired results, a summary, and a Markdown report. See each script’s help and header comments for supported options and column names. A comparison is not fair solely because the tool found matching rows; validate that simulator, demand, network, policy, and configuration conditions really match.

### Flag road-segment conditions

Provide a segment ID, a metric, and thresholds chosen for the metric’s units and environment:

```bash
Rscript experiments/flag_segments.R \
  --input segment_metrics.csv \
  --segment-column segment_id \
  --metric mean_queue_length \
  --warning-threshold 8 \
  --critical-threshold 14
```

The script writes a row-level flagged CSV. Add `--time-column timestamp` to also write a latest-row snapshot per segment. Thresholds are user-defined and should not be treated as universal traffic standards.

### Launch, parse, plot, and audit

The Python experiment helper can analyze existing artifacts without starting any process:

```bash
python experiments/run_experiment.py \
  --base-dir experiments --skip-train --skip-evaluate
```

It can also launch the training/evaluation commands documented in the root README, if the expected root `main.py` entry point and dependencies are available. See `python experiments/run_experiment.py --help` for options. The evidence audit uses heuristic artifact matching; “evidence found” is not proof of algorithm effectiveness or experiment validity.

## Reproducible comparisons

For comparisons, keep the environment/network, traffic demand, simulator and version, evaluation policy, metric definitions, and evaluation seeds consistent across controllers. Preserve configuration files, checkpoints, logs, and per-seed result rows. Report units and how metrics are aggregated. Treat tool-generated summaries as analysis aids, and inspect the underlying experiment artifacts before making scientific or operational claims.
