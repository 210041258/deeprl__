import os
import subprocess
from pathlib import Path

# ===============================
# Project Paths
# ===============================
# Path to the directory where this script lives (deeprl__)
project_root = Path(__file__).resolve().parent
config_dir = project_root / "config"
experiments_dir = project_root / "experiments/i"

# Make sure the experiments directory exists
experiments_dir.mkdir(parents=True, exist_ok=True)

# ===============================
# Find all .ini config files
# ===============================
config_files = list(config_dir.glob("config_ild_*.ini"))

if not config_files:
    raise FileNotFoundError(f"No .ini files found in {config_dir}")

print(f"Found {len(config_files)} config files:")
for f in config_files:
    print(f" - {f.name}")

# ===============================
# Run each training in parallel with separate logs
# ===============================
processes = []
for config_file in config_files:
    log_file = experiments_dir / f"{config_file.stem}.log"  # e.g., config_ia2c_large.log


    main_py_path = str(project_root / "main.py").encode('utf-8', errors='ignore').decode('ascii', errors='ignore')
    config_path = str(config_file).encode('utf-8', errors='ignore').decode('ascii', errors='ignore')
    experiments_path = str(experiments_dir).encode('utf-8', errors='ignore').decode('ascii', errors='ignore')
    log_path = str(log_file).encode('utf-8', errors='ignore').decode('ascii', errors='ignore')


    cmd = [
        "python",  # or "python3" depending on your setup
        str(project_root / "main.py"),
        "--base-dir", str(experiments_dir),
        "train",
        "--config-dir", str(config_file),
        "--test-mode", "no_test"
    ]

    print(f"Launching: {' '.join(cmd)}")
    print(f"Logging to: {log_file}\n")

    # Open log file and redirect stdout and stderr
    with open(log_file, "w") as f:
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
        processes.append(p)

# ===============================
# Wait for all processes to finish
# ===============================
for p in processes:
    p.wait()

print("All IA2C trainings completed!")
