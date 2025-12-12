"""
collect_baseline.py
Collect baseline (fault-free) data from the 'nofaults' topic.

Valentina Wu, 12/11/2025
"""

import paho.mqtt.client as mqtt
import json
import csv
import os
from datetime import datetime
from utils import safe_get

BROKER = "engf0001.cs.ucl.ac.uk"
PORT = 1883
TOPIC = "bioreactor_sim/nofaults/telemetry/summary"
OUTPUT_FILE = "baseline.csv"

# CSV header: record measurement, setpoint, and error (measurement - setpoint)
HEADER = [
    "time",
    "temperature", "temperature_setpoint", "temp_error",
    "pH", "pH_setpoint", "ph_error",
    "rpm", "rpm_setpoint", "rpm_error",
    "heater_pwm", "motor_pwm", "acid_pwm", "base_pwm"
]

# Create file & header if needed
if not os.path.exists(OUTPUT_FILE) or os.path.getsize(OUTPUT_FILE) == 0:
    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)


def extract_row(payload):
    # measurements (means)
    t = safe_get(payload, "temperature_C", "mean", default=None)
    ph = safe_get(payload, "pH", "mean", default=None)
    rpm = safe_get(payload, "rpm", "mean", default=None)

    # setpoints
    sp_t = safe_get(payload, "setpoints", "temperature_C", default=None)
    sp_ph = safe_get(payload, "setpoints", "pH", default=None)
    sp_rpm = safe_get(payload, "setpoints", "rpm", default=None)

    # errors
    temp_err = None if (t is None or sp_t is None) else (t - sp_t)
    ph_err = None if (ph is None or sp_ph is None) else (ph - sp_ph)
    rpm_err = None if (rpm is None or sp_rpm is None) else (rpm - sp_rpm)

    # actuators
    actuators = safe_get(payload, "actuators_avg", default={})
    heater = actuators.get("heater_pwm", None)
    motor = actuators.get("motor_pwm", None)
    acid = actuators.get("acid_pwm", None)
    base = actuators.get("base_pwm", None)

    return [
        datetime.now().isoformat(),
        t, sp_t, temp_err,
        ph, sp_ph, ph_err,
        rpm, sp_rpm, rpm_err,
        heater, motor, acid, base
    ]


def on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())
    except Exception as e:
        print("Failed to parse payload:", e)
        return

    row = extract_row(payload)

    # Only save rows where temperature measurement and setpoint exist
    if row[1] is None or row[2] is None:
        print("Skipping sample (missing measurement or setpoint)")
        return

    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(row)

    print(
        f"Saved: Temp={row[1]:.2f} (SP={row[2]:.2f}) Err={row[3]:+.2f} | "
        f"pH={row[4]:.2f} (SP={row[5]:.2f}) Err={row[6]:+.2f} | "
        f"RPM={row[7]:.0f} (SP={row[8]:.0f}) Err={row[9]:+.1f}"
    )


def main():
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe(TOPIC)
    print("Collecting baseline data from", TOPIC)
    client.loop_forever()


if __name__ == "__main__":
    main()
