# Experiments

This directory contains experiment outputs and supporting materials for the traffic-signal-control algorithms in this repository. The training and evaluation code lives at the repository root; algorithm configuration templates are in [`../config`](../config).

## Contents

| Path | Description |
| --- | --- |
| [`greedy/`](greedy/) | Greedy-baseline experiment artifacts, including data and logs. |
| [`ia2c/`](ia2c/) | Independent Advantage Actor-Critic (IA2C) experiment artifacts. |
| [`iqld/`](iqld/) | Independent Q-learning with decentralized execution (IQLD) experiment artifacts. |
| [`iqll/`](iqll/) | Independent Q-learning with local information (IQ**L**L) experiment artifacts. |
| [`ma2c/`](ma2c/) | Multi-agent Advantage Actor-Critic (MA2C) experiment artifacts. |
| [`test/`](test/) | Test-run data and logs. |
| [`eva_log/`](eva_log/) | Evaluation log files. |
| [`MARL_Traffic_Flow_Presentation_With_Graphs.pdf`](MARL_Traffic_Flow_Presentation_With_Graphs.pdf) | Presentation with traffic-flow experiment graphs. |

The algorithm directories may contain `data/`, `log/`, and `eva_log/` subdirectories for their respective runs. These are run artifacts, not the source code or configuration templates.

## Running experiments

See the repository’s [usage instructions](../README.md#usages) for environment setup, training, TensorBoard, and evaluation commands. Configure a run using the corresponding files in [`../config`](../config), then place its outputs under the desired experiment directory.

Experiment results depend on the SUMO version, configuration, and evaluation seeds. Record those alongside any new results so runs can be compared reproducibly.
