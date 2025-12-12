# engf0001-challenge2-data-analysis
This repository contains a simple data-analysis subsystem for a **simulated bioreactor**.  
It subscribes to MQTT telemetry streams, learns a baseline from a fault-free run, and then
detects sensor anomalies in live data (temperature, pH and stirrer RPM).

The main components are:

- `collect_baseline.py` – subscribes to the `nofaults` MQTT topic and logs a few minutes of
  fault-free operation to `baseline.csv` (measurements, set-points and control errors).
- `train_baseline.py` – reads `baseline.csv`, computes mean/std for each error signal, and
  writes `baseline_stats.json` with those statistics and derived tolerances. 
- `detect_anomalies.py` – subscribes to a chosen simulator stream (`nofaults`, `single_fault`,
  `three_faults`, or `variable_setpoints`), applies the baseline residual detector in real time,
  and logs anomaly decisions plus TP/TN/FP/FN counts to `detection_log_<stream>.csv`. 
- `utils.py` – small helper functions for safe nested dict access and JSON I/O.

---

## Requirements

- Python 3.9+ (any recent 3.x should be fine)
- Packages:
  - `paho-mqtt`
  - `pandas` (only needed for `train_baseline.py`)
- Network access to the course MQTT broker:
  - Host: `engf0001.cs.ucl.ac.uk`
  - Port: `1883`

Install dependencies, for example:

```bash
pip install paho-mqtt pandas
