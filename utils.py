# utils.py
import json


def safe_get(d, *keys, default=None):
    """
    Safely get nested keys from a dict.
    Example: safe_get(payload, "setpoints", "temperature_C", default=None)
    """
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def save_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def load_json(path):
    with open(path) as f:
        return json.load(f)
