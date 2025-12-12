# train_baseline.py
"""
Train baseline statistics from baseline.csv

Valentina Wu, 15/11/2025
"""

import pandas as pd
from utils import save_json

INPUT_FILE = "baseline.csv"
OUTPUT_FILE = "baseline_stats.json"

# z-score multiplier for setting tolerances
Z_TOL = 3.0  # 3σ covers most normal noise


def main():
    df = pd.read_csv(INPUT_FILE)

    # columns to use for stats: errors + actuators
    cols = [
        "temp_error", "ph_error", "rpm_error",
        "heater_pwm", "motor_pwm", "acid_pwm", "base_pwm"
    ]

    stats = {}
    for c in cols:
        if c not in df.columns:
            continue
        mean = df[c].mean()
        std = df[c].std()
        stats[c] = {
            "mean": float(mean) if pd.notna(mean) else None,
            "std": float(std) if pd.notna(std) else None,
        }

    # derive tolerances from error stds, but don't go below spec-like minimums
    temp_std = stats.get("temp_error", {}).get("std", None)
    ph_std = stats.get("ph_error", {}).get("std", None)
    rpm_std = stats.get("rpm_error", {}).get("std", None)

    temp_tol = max(0.5, (Z_TOL * temp_std) if temp_std is not None else 0.5)
    ph_tol = max(0.25, (Z_TOL * ph_std) if ph_std is not None else 0.25)
    rpm_tol = max(20.0, (Z_TOL * rpm_std) if rpm_std is not None else 20.0)

    stats["_specs"] = {
        "temperature_tol_C": temp_tol,
        "rpm_tol": rpm_tol,
        "ph_tol": ph_tol,
        "z_tol": Z_TOL,
    }

    save_json(OUTPUT_FILE, stats)
    print("Saved baseline stats to", OUTPUT_FILE)
    print("Tolerances:")
    print(f"  temp_tol = {temp_tol:.3f} °C")
    print(f"  ph_tol   = {ph_tol:.3f} pH")
    print(f"  rpm_tol  = {rpm_tol:.3f} RPM")


if __name__ == "__main__":
    main()
