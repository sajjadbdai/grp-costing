"""Persistent material price store. Stdlib only.

Central place to view and update the factory's default material rates.
Updates change the defaults used for NEW estimates only: saved estimates
keep their own rate snapshots, so history is never rewritten.
"""

from __future__ import annotations

import json
import math
import os
import time

from . import costing


class MaterialsError(Exception):
    """Price store unavailable or update rejected."""


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_path():
    override = os.environ.get("GFPF_RATES_PATH")
    if override:
        return override
    return os.path.join(_project_root(), "data", "rates.json")


def _load_file():
    """Saved prices plus metadata, or None when never saved."""
    path = data_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise MaterialsError("Saved material prices file is unreadable (%s)." % exc)
    if not isinstance(data, dict) or not isinstance(data.get("rates"), dict):
        raise MaterialsError("Saved material prices file has an unexpected format.")
    rates = {}
    for key, value in data["rates"].items():
        if key not in costing.DEFAULT_RATES:
            continue  # retired key (e.g. flat consumables) - keep old files working
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise MaterialsError("Saved rate %r is not a number (%r)." % (key, value))
        if not math.isfinite(number) or number < 0:
            raise MaterialsError("Saved rate %r is not a valid price (%r)." % (key, value))
        rates[key] = number
    return {"rates": rates, "updated_at": data.get("updated_at")}


def get_state():
    """Current effective rates plus save metadata.

    Raises MaterialsError when the file exists but cannot be used.
    """
    merged = dict(costing.DEFAULT_RATES)
    data = _load_file()
    if data is None:
        return {"rates": merged, "updated_at": None, "customized": False}
    merged.update(data["rates"])
    return {"rates": merged, "updated_at": data["updated_at"], "customized": True}


def get_rates():
    """Current effective rates as a plain dict."""
    return get_state()["rates"]


def update_rates(values):
    """Validate and persist new prices; returns the new state.

    Only known rate keys are accepted; every new price must be a
    finite, non-negative number. Keys not mentioned keep their values.
    Raises MaterialsError when nothing valid was given.
    """
    if not values:
        raise MaterialsError("No new prices given.")
    state = get_state()
    merged = dict(state["rates"])
    for key, value in values.items():
        if key not in costing.DEFAULT_RATES:
            raise MaterialsError("Unknown material rate %r." % (key,))
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise MaterialsError("Rate %r: expected a number, got %r." % (key, value))
        if not math.isfinite(number):
            raise MaterialsError("Rate %r: expected a finite number." % (key,))
        if number < 0:
            raise MaterialsError("Rate %r must not be negative (got %s)." % (key, value))
        merged[key] = number
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    path = data_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"rates": merged, "updated_at": now}, handle, indent=2)
    os.replace(tmp, path)
    return {"rates": merged, "updated_at": now, "customized": True}
