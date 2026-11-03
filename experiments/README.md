# Experiments

This folder contains experiment artifacts and analysis utilities for the repository's multi-agent reinforcement-learning traffic-signal project. Training and evaluation depend on the environment configuration and simulator setup described in the [root README](../README.md).

## Contents

### Experiment artifacts

| Path | Description |
| --- | --- |
| [`greedy/`](greedy/) | Greedy-controller experiment artifacts. |
| [`ia2c/`](ia2c/) | IA2C experiment artifacts. |
| [`iqld/`](iqld/) | IQL-D experiment artifacts. |
| [`iqll/`](iqll/) | IQL-L experiment artifacts. |
| [`ma2c/`](ma2c/) | MA2C experiment artifacts. |
| [`test/`](test/) | Test-run artifacts. |
| [`eva_log/`](eva_log/) | Evaluation logs. |
| [`MARL_Traffic_Flow_Presentation_With_Graphs.pdf`](MARL_Traffic_Flow_Presentation_With_Graphs.pdf) | Presentation containing traffic-flow graphs. |

### Analysis tools

| Script | Purpose |
| --- | --- |
| [`run_experiment.py`](run_experiment.py) | Launch documented runs and analyze supported experiment artifacts. Use its help and `--skip-train --skip-evaluate` for analysis-only operation. |
| [`compare_baselines.py`](compare_baselines.py) | Compare a learned controller against baseline results from a per-seed CSV. |
| [`compare_baselines.R`](compare_baselines.R) | Base-R alternative for paired controller comparisons. |
| [`compare_policy_to_greedy.py`](compare_policy_to_greedy.py) | Compare a learned policy with actual greedy-baseline results. |
| [`summarize_environment_results.R`](summarize_environment_results.R) | Summarize metrics grouped by environment and controller. |
| [`flag_segments.R`](flag_segments.R) | Apply user-specified traffic-condition thresholds to segment metrics. |
| [`visualize_flagged_segments.py`](visualize_flagged_segments.py) | Plot status counts and segment metrics from flagged segment data; optional coordinates produce a point map. |
| [`validate_results.py`](validate_results.py) | Check an evaluation CSV for missing/invalid values, duplicate run keys, and missing metadata. |
| [`analyze_operational_factors.py`](analyze_operational_factors.py) | Describe how recorded operational factor levels correspond to outcome metrics. |

## Common workflows

### Validate a results CSV

```bash
python experiments/validate_results.py --input evaluation.csv
```

The script writes a Markdown validation report and a row-level issues CSV under `validation/` beside the input file by default. A clean validation checks data structure; it does not prove that the simulator ran correctly or that an experiment is scientifically valid.

### Compare a learned controller with greedy

Provide actual results for both controllers, with matching evaluation seeds and as much context metadata as possible (scenario, demand, network, simulator/version, and configuration identifier).

```bash
python experiments/compare_policy_to_greedy.py \
  --input evaluation.csv \
  --learned ma2c
```

The script writes paired rows, a summary, and a Markdown report to `greedy_comparison/` by default. It will not synthesize missing greedy results. Add other baselines only when you have actually run them and included their results.

### Summarize environment results

```bash
Rscript experiments/summarize_environment_results.R --input evaluation.csv
```

The input should include environment, algorithm/controller, and numeric metric columns. The script writes per-group counts and descriptive statistics to `environment_summary/` by default. You can override column names and metrics with the script's command-line options.

### Examine operational factors

```bash
python experiments/analyze_operational_factors.py --input evaluation.csv
```

Factor columns can be selected explicitly, for example:

```bash
python experiments/analyze_operational_factors.py \
  --input evaluation.csv \
  --factors scenario demand_level peak_period control_interval_sec \
  --metrics mean_travel_time mean_waiting_time throughput
```

This produces factor-level descriptive summaries. Associations are not evidence of causation; ensure other experiment settings are comparable before interpreting differences.

### Flag and visualize segment conditions

First flag segment metrics with thresholds appropriate to your metric units and environment:

```bash
Rscript experiments/flag_segments.R \
  --input segment_metrics.csv \
  --segment-column segment_id \
  --metric mean_queue_length \
  --warning-threshold 8 \
  --critical-threshold 14
```

Then visualize the flagged CSV:

```bash
python experiments/visualize_flagged_segments.py \
  --input segment_metrics_flagged.csv \
  --metric mean_queue_length
```

The visualizer requires Matplotlib for PNG charts. Optional `--x-column` and `--y-column` arguments create a coordinate point map; they do not render road geometry. Threshold values are user-defined, not universal standards.

## Reproducibility and interpretation

- Keep network, demand profile, simulator/version, evaluation policy, metric definitions, and seed sets consistent when comparing controllers.
- Preserve per-seed results, configuration files, checkpoints, logs, and version information.
- Record metric units and how metrics are aggregated. Check for duplicate runs and missing values before analysis.
- Report the actual controllers and runs used. Do not list or compare a baseline unless it was executed and its results are present.
- These utilities analyze supplied artifacts; they do not establish causal effects, statistical significance, or operational readiness unless a tool explicitly performs such an analysis.
