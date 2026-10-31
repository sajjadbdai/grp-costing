"""Shape library: deterministic laminate-area geometry.

All internal dimensions are millimetres; areas are square metres.
Muse proposes values; this module only computes from confirmed values.
"""

from __future__ import annotations

import math


class ShapeError(ValueError):
    """Missing or invalid shape dimensions."""


def _number(name, value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ShapeError("%s: expected a number, got %r" % (name, value))
    if not math.isfinite(number):
        raise ShapeError("%s: must be finite" % name)
    return number


def _positive(name, value):
    number = _number(name, value)
    if number <= 0:
        raise ShapeError("%s: must be greater than zero (got %s)" % (name, value))
    return number


def _non_negative(name, value):
    number = _number(name, value)
    if number < 0:
        raise ShapeError("%s: must not be negative (got %s)" % (name, value))
    return number


def panel_area(length_mm, width_mm, flange_mm=0.0):
    """Flat panel with optional all-round planar flange border.

    Preserves the original GFPF MVP formula: the border adds
    ``2*l*f + 2*w*f + 4*f*f`` to the base rectangle.
    """
    length = _positive("length", length_mm) / 1000.0
    width = _positive("width", width_mm) / 1000.0
    flange = _non_negative("flange", flange_mm) / 1000.0
    base = length * width
    border = 2 * length * flange + 2 * width * flange + 4 * flange * flange if flange else 0.0
    return {
        "area_m2": base + border,
        "parts": [
            {"label": "Panel face", "area_m2": base},
            {"label": "All-round flange border", "area_m2": border},
        ],
        "warnings": [],
    }


def cylinder_area(diameter_mm, height_mm, closed_bottom=True, closed_top=False):
    """Straight cylindrical shell (tank, pipe section, round duct).

    Lateral area pi*D*H plus optional flat ends measured by outer diameter.
    """
    diameter = _positive("diameter", diameter_mm) / 1000.0
    height = _positive("height", height_mm) / 1000.0
    lateral = math.pi * diameter * height
    end = math.pi * diameter * diameter / 4.0
    bottom = end if closed_bottom else 0.0
    top = end if closed_top else 0.0
    return {
        "area_m2": lateral + bottom + top,
        "parts": [
            {"label": "Cylindrical wall", "area_m2": lateral},
            {"label": "Bottom disc", "area_m2": bottom},
            {"label": "Top disc", "area_m2": top},
        ],
        "warnings": [],
    }


def reducer_area(d_large_mm, d_small_mm, height_mm):
    """Concentric conical reducer (frustum), open at both ends.

    Lateral area pi*(R+r)*s with slant height s from the axial height.
    """
    large = _positive("large diameter", d_large_mm)
    small = _positive("small diameter", d_small_mm)
    warnings = []
    if small > large:
        large, small = small, large
        warnings.append("Diameters were swapped so that large >= small.")
    radius_large = large / 2000.0
    radius_small = small / 2000.0
    height = _positive("height", height_mm) / 1000.0
    slant = math.hypot(radius_large - radius_small, height)
    lateral = math.pi * (radius_large + radius_small) * slant
    return {
        "area_m2": lateral,
        "parts": [{"label": "Reducer cone wall", "area_m2": lateral}],
        "warnings": warnings,
    }


#: Field metadata per shape: key, label, required, default for optionals.
SHAPES = {
    "panel": {
        "label": "Flat panel / plate",
        "blurb": "Rectangular laminate with an optional all-round flange border.",
        "fields": [
            {"key": "length", "label": "Length", "required": True},
            {"key": "width", "label": "Width", "required": True},
            {"key": "thickness", "label": "Laminate thickness", "required": True},
            {"key": "flange", "label": "All-round flange width", "required": False, "default": 0.0},
        ],
        "options": [
        ],
        "assumptions": [
            "Flange is an all-round planar border: 2*l*f + 2*w*f + 4*f*f.",
            "Single flat laminate of uniform thickness; no ribs or returns.",
        ],
    },
    "cylinder": {
        "label": "Cylinder (tank / pipe / duct)",
        "blurb": "Straight cylindrical shell with optional flat ends.",
        "fields": [
            {"key": "diameter", "label": "Outer diameter", "required": True},
            {"key": "height", "label": "Height / length", "required": True},
            {"key": "thickness", "label": "Laminate thickness", "required": True},
        ],
        "options": [
            {"key": "closed_bottom", "label": "Closed bottom", "default": True},
            {"key": "closed_top", "label": "Closed top", "default": False},
        ],
        "assumptions": [
            "Wall area pi*D*H using the outer diameter.",
            "Flat ends (when selected) are discs by outer diameter.",
            "No stiffeners, nozzles or rim flanges included.",
        ],
    },
    "reducer": {
        "label": "Reducer (concentric cone)",
        "blurb": "Conical reducer between two diameters, open at both ends.",
        "fields": [
            {"key": "d_large", "label": "Large-end diameter", "required": True},
            {"key": "d_small", "label": "Small-end diameter", "required": True},
            {"key": "height", "label": "Axial height", "required": True},
            {"key": "thickness", "label": "Laminate thickness", "required": True},
        ],
        "options": [
        ],
        "assumptions": [
            "Concentric frustum; lateral area pi*(R+r)*slant height.",
            "Both ends open; end rings or mating flanges excluded.",
        ],
    },
}

SHAPE_IDS = tuple(SHAPES)


def get_shape(shape_id):
    try:
        return SHAPES[shape_id]
    except KeyError:
        raise ShapeError(
            "Unknown shape %r (expected one of %s)" % (shape_id, ", ".join(SHAPE_IDS))
        )


def compute_area(shape_id, dims_mm, options=None):
    """Return an area breakdown for validated millimetre dimensions."""
    get_shape(shape_id)
    options = options or {}
    if shape_id == "panel":
        return panel_area(dims_mm["length"], dims_mm["width"], dims_mm.get("flange", 0.0))
    if shape_id == "cylinder":
        return cylinder_area(
            dims_mm["diameter"],
            dims_mm["height"],
            closed_bottom=bool(options.get("closed_bottom", True)),
            closed_top=bool(options.get("closed_top", False)),
        )
    if shape_id == "reducer":
        return reducer_area(dims_mm["d_large"], dims_mm["d_small"], dims_mm["height"])
    raise ShapeError("No area function for shape %r" % shape_id)  # unreachable


def required_fields(shape_id):
    return [f["key"] for f in get_shape(shape_id)["fields"] if f["required"]]