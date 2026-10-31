"""Length units: parse mm/cm/m, convert, preserve originals, flag conflicts."""

from __future__ import annotations

import re

MM_PER_UNIT = {
    "mm": 1.0,
    "millimetre": 1.0,
    "millimetres": 1.0,
    "millimeter": 1.0,
    "millimeters": 1.0,
    "cm": 10.0,
    "centimetre": 10.0,
    "centimetres": 10.0,
    "centimeter": 10.0,
    "centimeters": 10.0,
    "m": 1000.0,
    "metre": 1000.0,
    "metres": 1000.0,
    "meter": 1000.0,
    "meters": 1000.0,
}

_MEASURE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)?\s*$")


class UnitError(ValueError):
    """Unknown unit or unparsable measurement."""


def normalize_unit(unit):
    """Map aliases to mm, cm or m (blank defaults to mm)."""
    if unit is None or str(unit).strip() == "":
        return "mm"
    key = str(unit).strip().lower()
    if key not in MM_PER_UNIT:
        raise UnitError("Unknown length unit %r (use mm, cm or m)" % (unit,))
    factor = MM_PER_UNIT[key]
    if factor == 1.0:
        return "mm"
    if factor == 10.0:
        return "cm"
    return "m"


def to_mm(value, unit="mm"):
    return float(value) * MM_PER_UNIT[normalize_unit(unit)]


def from_mm(mm_value, unit="mm"):
    return float(mm_value) / MM_PER_UNIT[normalize_unit(unit)]


def parse_measurement(text, default_unit="mm"):
    """Parse '675', '67.5 cm' or '0.675m' into value + canonical unit."""
    match = _MEASURE_RE.match(str(text))
    if not match:
        raise UnitError("Could not read a measurement from %r" % (text,))
    number = float(match.group(1))
    unit = normalize_unit(match.group(2) or default_unit)
    return {"value": number, "unit": unit, "mm": number * MM_PER_UNIT[unit]}


def conflict(field_label, first_mm, second_mm, first_desc, second_desc, tolerance=0.005):
    """Describe a mismatch between two readings of one dimension, or None."""
    if first_mm <= 0 or second_mm <= 0:
        return None
    relative = abs(first_mm - second_mm) / max(first_mm, second_mm)
    if relative <= tolerance:
        return None
    return (
        "%s conflicts: %s but %s (relative difference %.1f%%). "
        "Confirm which reading is correct before calculating."
        % (field_label, first_desc, second_desc, relative * 100.0)
    )