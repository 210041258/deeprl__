# Deep RL for traffic signal control

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

This repository implements multi-agent deep reinforcement-learning algorithms for traffic-signal control in SUMO-simulated environments. It includes centralized and decentralized cooperation settings, fully connected and LSTM network layers, and IQL, IA2C, and stabilized IA2C (MA2C) methods.

## Environments

The project documents three traffic environments:

- A six-intersection benchmark network.
- A 5 × 5 traffic grid.
- A modified Monaco traffic network with 30 signalized intersections.

Environment files and configuration templates are organized in [`small_grid/`](small_grid/), [`large_grid/`](large_grid/), [`real_net/`](real_net/), and [`config/`](config/).

## Requirements and setup

The original training environment specifies Python 3.5, TensorFlow 1.12.0, and SUMO 1.1.0 or later. Install the project dependencies using [`setup_mac.sh`](setup_mac.sh) or [`setup_ubuntu.sh`](setup_ubuntu.sh). The original code targets SUMO >= 1.1.0; consult the upstream [`sumo-0.32.0` branch](https://github.com/cts198859/deeprl_signal_control/tree/sumo-0.32.0) if you need that older SUMO release.

## Training and evaluation

Prepare the selected environment files and a configuration file in [`config/`](config/) before running. The commands documented by the project are:

```bash
# Train an agent (ia2c, ma2c, iqll, or iqld)
python3 main.py --base-dir [base_dir]/[agent] train \
  --config-dir [config_dir] --test-mode no_test

# View training logs
 tensorboard --logdir=[base_dir]/log

# Evaluate one or more trained agents on held-out seeds
python3 main.py --base-dir [base_dir] evaluate \
  --agents [agents] --evaluation-seeds [seeds]
```

Evaluation seeds should be distinct from training seeds. The project documents `default`, `stochastic`, and `deterministic` evaluation policy types; deterministic inference for an on-policy A2C agent may affect performance. See the [original usage notes](README.md#usages) and environment configuration files for details. To launch the SUMO GUI for a demo, add `--demo` to an evaluation command.

## Experiment analysis tools

The [`experiments/`](experiments/) directory contains run artifacts and two helper scripts. They analyze artifacts/results; they do not create missing evaluation data or establish that a scientific claim is true.

### Run, parse, plot, and audit artifacts

[`experiments/run_experiment.py`](experiments/run_experiment.py) can launch the repository's documented training/evaluation commands, parse numeric CSV/text logs, plot available metrics, and write a qualitative `evidence_report.md`.

```bash
# Audit existing files only; do not launch training/evaluation
python experiments/run_experiment.py \
  --base-dir experiments --skip-train --skip-evaluate

# Request a training/evaluation run and then analyze its outputs
python experiments/run_experiment.py \
  --agent ma2c --scenario large --seeds 11 22 33
```

The launcher expects a root-level `main.py` as described in the original project instructions. If it is unavailable in your checkout, use the analysis-only mode or restore the project's entry point first. Matplotlib is optional; without it, CSV parsing and the evidence report still work. The evidence audit uses heuristic file/text matching. “Evidence found” is an inventory status, not proof of completed runs, fair comparisons, convergence, or improved traffic performance.

### Compare a learned controller with baselines

[`experiments/compare_baselines.py`](experiments/compare_baselines.py) analyzes a CSV of **actual per-seed evaluation results**. It pairs the learned method with fixed-time, adaptive, and MaxPressure controller rows, checks available matching context, and writes `paired_results.csv`, `summary.csv`, and `report.md`.

The input needs one row per controller and evaluation seed, including an algorithm label, a seed, and metric columns. For example:

```csv
algorithm,seed,scenario,demand_id,simulator,simulator_version,config_hash,mean_travel_time,mean_waiting_time,mean_queue_length,throughput
ma2c,11,large,weekday,SUMO,1.1,abc123,120,25,8,900
fixed_time,11,large,weekday,SUMO,1.1,abc123,150,35,12,850
adaptive,11,large,weekday,SUMO,1.1,abc123,140,31,10,870
maxpressure,11,large,weekday,SUMO,1.1,abc123,130,28,9,890
```

Run the comparison with:

```bash
python experiments/compare_baselines.py --input evaluation.csv
```

Use the labels in your CSV with `--learned` and `--baselines` if they differ from the defaults. The default metrics are travel time, waiting time, queue length, and throughput. Lower is treated as better for the first three; throughput is treated as higher-is-better. Specify other directions with `--higher-is-better`. Percentage improvements and sample standard deviations are computed across unambiguously paired seeds; a single seed has no sample standard deviation. Missing baseline results are never fabricated.

For a meaningful fairness check, provide and match context columns such as `scenario`, `demand_id` (or `demand_file`), `network`, `simulator`, `simulator_version`, and `config_hash`, in addition to `seed`. Matching metadata helps identify mismatches but does not prove that the simulator was run correctly or that all other conditions were equivalent. Review the generated report and underlying per-seed results before making claims.

The helper scripts use modern Python features and should be run with Python 3.9 or newer. This is separate from the legacy Python/TensorFlow version specified for the original training code.

## Reproducibility and interpretation

For comparisons, keep the network, traffic demand, simulator version, evaluation policy, and evaluation seeds consistent across controllers. Preserve configuration files, checkpoints/policies, logs, and per-seed results. Report metric definitions and units. Do not infer statistical significance or general performance from plots, filenames, or aggregate values alone.

The repository's historical reproducibility discussion and reference training plots are below. They describe the original project's experiments and should not be confused with new results produced by the analysis tools.

## Citation

If you use the project in research, cite the paper “Multi-Agent Deep Reinforcement Learning for Large-Scale Traffic Signal Control”:

```bibtex
@article{chu2019multi,
  title={Multi-Agent Deep Reinforcement Learning for Large-Scale Traffic Signal Control},
  author={Chu, Tianshu and Wang, Jie and Codec{\`a}, Lara and Li, Zhaojian},
  journal={IEEE Transactions on Intelligent Transportation Systems},
  year={2019},
  publisher={IEEE}
}
```
