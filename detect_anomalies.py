"""
detect_anomalies.py
Run anomaly detection on MQTT stream and keep TP/TN/FP/FN scores.

Valentina Wu, 15/11/2025
"""

import paho.mqtt.client as mqtt
import json
import csv
from collections import deque
from datetime import datetime, timedelta

from utils import safe_get, load_json

BROKER = "engf0001.cs.ucl.ac.uk"
PORT = 1883

# ======= CONFIG =======
# Set which simulator stream to use:
# "nofaults", "single_fault", "three_faults", "variable_setpoints"
STREAM = "variable_setpoints"
TOPIC = f"bioreactor_sim/{STREAM}/telemetry/summary"

BASELINE_FILE = "baseline_stats.json"
LOG_FILE = f"detection_log_{STREAM}.csv"

# Number of consecutive raw anomalies needed to flag a true anomaly
CONSEC_REQUIRED = 3

# Grace period after any setpoint change
GRACE_PERIOD = timedelta(seconds=10)

# Which field holds the active fault labels inside payload["faults"]
FAULTS_KEY = "last_active"   

# Whether to print the first 'faults' dict to inspect its structure
PRINT_FIRST_FAULTS = True
# =======================


# Load baseline stats
baseline = load_json(BASELINE_FILE)

# Specs tolerances (now trained from baseline)
TEMP_TOL =  1.0  #changed from baseline.get("_specs", {}).get("temperature_tol_C", 0.5) to match errors in fault stream, raises fewer FPs
RPM_TOL = baseline.get("_specs", {}).get("rpm_tol", 20.0)
PH_TOL = baseline.get("_specs", {}).get("ph_tol", 0.25)
Z_TOL = baseline.get("_specs", {}).get("z_tol", 3.0)  # only for logging now

# Baseline stats for z-score (diagnostic only)
STATS = {
    "temp_error": baseline.get("temp_error", {}),
    "ph_error": baseline.get("ph_error", {}),
    "rpm_error": baseline.get("rpm_error", {}),
}

# Setpoint change tracking
last_setpoints = {"temperature_C": None, "pH": None, "rpm": None}
last_change_time = {"temperature_C": None, "pH": None, "rpm": None}

# Scoring counters
TP = TN = FP = FN = 0

# Smoothing: raw anomaly history
raw_anomaly_history = deque(maxlen=CONSEC_REQUIRED)

# Create CSV log file
with open(LOG_FILE, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([
        "time",
        "temp", "temp_sp", "temp_err",
        "ph", "ph_sp", "ph_err",
        "rpm", "rpm_sp", "rpm_err",
        "heater_pwm", "motor_pwm", "acid_pwm", "base_pwm",
        "faults_active", "anomaly_flag", "raw_anomaly", "reason",
        "score", "TP", "TN", "FP", "FN"
    ])


def extract_fields(payload):
    t = safe_get(payload, "temperature_C", "mean", default=None)
    sp_t = safe_get(payload, "setpoints", "temperature_C", default=None)
    ph = safe_get(payload, "pH", "mean", default=None)
    sp_ph = safe_get(payload, "setpoints", "pH", default=None)
    rpm = safe_get(payload, "rpm", "mean", default=None)
    sp_rpm = safe_get(payload, "setpoints", "rpm", default=None)

    temp_err = None if (t is None or sp_t is None) else (t - sp_t)
    ph_err = None if (ph is None or sp_ph is None) else (ph - sp_ph)
    rpm_err = None if (rpm is None or sp_rpm is None) else (rpm - sp_rpm)

    actuators = safe_get(payload, "actuators_avg", default={})
    heater = actuators.get("heater_pwm", None)
    motor = actuators.get("motor_pwm", None)
    acid = actuators.get("acid_pwm", None)
    base = actuators.get("base_pwm", None)

    return {
        "t": t, "sp_t": sp_t, "temp_err": temp_err,
        "ph": ph, "sp_ph": sp_ph, "ph_err": ph_err,
        "rpm": rpm, "sp_rpm": sp_rpm, "rpm_err": rpm_err,
        "heater": heater, "motor": motor, "acid": acid, "base": base,
    }


def z_score(value, stat_dict):
    """
    Diagnostic only: compute z-score of error vs baseline.
    This is logged as 'score' but NOT used as a hard trigger now.
    """
    mu = stat_dict.get("mean", None)
    sd = stat_dict.get("std", None)
    if value is None or mu is None or sd is None or sd == 0:
        return 0.0
    return (value - mu) / sd


def decide_raw_anomaly(fields):
    """
    Decide anomaly based on instantaneous errors vs tolerances.
    Also compute a z-score-based 'score' for logging, but we
    no longer use score > Z_TOL as a detection rule.
    """
    reasons = []

    # 1) Hard tolerances based on baseline + spec
    if fields["temp_err"] is not None and abs(fields["temp_err"]) > TEMP_TOL:
        reasons.append(f"temp_err {fields['temp_err']:+.2f} > tol {TEMP_TOL:.2f}")
    if fields["ph_err"] is not None and abs(fields["ph_err"]) > PH_TOL:
        reasons.append(f"ph_err {fields['ph_err']:+.2f} > tol {PH_TOL:.2f}")
    if fields["rpm_err"] is not None and abs(fields["rpm_err"]) > RPM_TOL:
        reasons.append(f"rpm_err {fields['rpm_err']:+.1f} > tol {RPM_TOL:.1f}")

    # 2) Diagnostic z-score for logging / analysis
    z_temp = z_score(fields["temp_err"], STATS["temp_error"])
    z_ph = z_score(fields["ph_err"], STATS["ph_error"])
    z_rpm = z_score(fields["rpm_err"], STATS["rpm_error"])
    score = max(abs(z_temp), abs(z_ph), abs(z_rpm))

    is_raw_anom = len(reasons) > 0
    if not reasons:
        reasons.append("within_tolerance")

    # Optionally, append score info to reason just for human interpretation
    reasons.append(f"(score={score:.2f}, Z_TOL={Z_TOL:.2f})")

    return is_raw_anom, "; ".join(reasons), score


def on_message(client, userdata, message):
    global TP, TN, FP, FN, PRINT_FIRST_FAULTS

    try:
        payload = json.loads(message.payload.decode())
    except Exception as e:
        print("Bad payload:", e)
        return

    fields = extract_fields(payload)
    now = datetime.now()

    # Detect setpoint changes
    for key, field_key in [("temperature_C", "sp_t"), ("pH", "sp_ph"), ("rpm", "sp_rpm")]:
        current_sp = fields[field_key]
        if current_sp is not None:
            if last_setpoints[key] is not None and current_sp != last_setpoints[key]:
                last_change_time[key] = now
            last_setpoints[key] = current_sp

    # Suppress anomaly detection if within grace period after any setpoint change
    suppress = any(
        last_change_time[k] is not None and now - last_change_time[k] < GRACE_PERIOD
        for k in last_change_time
    )

    if suppress:
        raw_is_anom = False
        reason = "Suppressed due to recent setpoint change"
        score = 0.0
    else:
        raw_is_anom, reason, score = decide_raw_anomaly(fields)

    # Smoothing: update history and decide final anomaly flag
    raw_anomaly_history.append(raw_is_anom)
    is_anom = all(raw_anomaly_history) and len(raw_anomaly_history) == CONSEC_REQUIRED

    # Get ground-truth faults for scoring
    faults_dict = safe_get(payload, "faults", default={})

    if PRINT_FIRST_FAULTS:
        print("Faults dict example:\n", json.dumps(faults_dict, indent=2))
        PRINT_FIRST_FAULTS = False

    faults = faults_dict.get(FAULTS_KEY, [])
    if faults is None:
        faults = []
    if isinstance(faults, dict):
        faults = list(faults.values())
    elif isinstance(faults, str):
        faults = [faults]

    fault_active = len(faults) > 0

    # Update confusion matrix
    if is_anom and fault_active:
        TP += 1
    elif not is_anom and not fault_active:
        TN += 1
    elif is_anom and not fault_active:
        FP += 1
    elif not is_anom and fault_active:
        FN += 1

    # Print status (assuming non-None values)
    print(
        f"Temp={fields['t']:.2f} (SP={fields['sp_t']:.2f}) Err={fields['temp_err']:+.2f} | "
        f"pH={fields['ph']:.2f} (SP={fields['sp_ph']:.2f}) Err={fields['ph_err']:+.2f} | "
        f"RPM={fields['rpm']:.0f} (SP={fields['sp_rpm']:.0f}) Err={fields['rpm_err']:+.1f} | "
        f"Faults={faults} | Anomaly={is_anom} (raw={raw_is_anom}) | Score={score:.2f} | Reason={reason}"
    )
    print(f"TP={TP} TN={TN} FP={FP} FN={FN}\n")

    # Append to CSV log
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            now.isoformat(),
            fields["t"], fields["sp_t"], fields["temp_err"],
            fields["ph"], fields["sp_ph"], fields["ph_err"],
            fields["rpm"], fields["sp_rpm"], fields["rpm_err"],
            fields["heater"], fields["motor"], fields["acid"], fields["base"],
            ";".join(str(x) for x in faults),
            is_anom, raw_is_anom, reason,
            score, TP, TN, FP, FN,
        ])


def main():
    print("Running detector on", TOPIC)
    print(f"TEMP_TOL={TEMP_TOL:.3f}, PH_TOL={PH_TOL:.3f}, RPM_TOL={RPM_TOL:.3f}")
    print(f"CONSEC_REQUIRED={CONSEC_REQUIRED}, GRACE_PERIOD={GRACE_PERIOD}")
    print("(z-score 'score' is logged for analysis but not used as a trigger.)")

    client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe(TOPIC)
    client.loop_forever()


if __name__ == "__main__":
    main()
