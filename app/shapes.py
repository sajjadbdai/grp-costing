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


def box_area(length_mm, width_mm, height_mm, open_top=True):
    """Rectangular tank / enclosure: four walls plus bottom, optional lid.

    Used for water tanks, septic chambers, cabinets and kiosks.
    """
    length = _positive("length", length_mm) / 1000.0
    width = _positive("width", width_mm) / 1000.0
    height = _positive("height", height_mm) / 1000.0
    walls = 2 * (length * height + width * height)
    bottom = length * width
    top = 0.0 if open_top else length * width
    return {
        "area_m2": walls + bottom + top,
        "parts": [
            {"label": "Four walls", "area_m2": walls},
            {"label": "Bottom", "area_m2": bottom},
            {"label": "Lid", "area_m2": top},
        ],
        "warnings": [],
    }


def custom_area(area_m2):
    """Measured surface area for free-form parts (boat hulls, guards).

    The area comes from the mould, plug or drawings - no geometry is assumed.
    """
    area = _positive("surface area", area_m2)
    return {
        "area_m2": area,
        "parts": [{"label": "Measured surface", "area_m2": area}],
        "warnings": [],
    }
def _cap_area(diameter_m, height_m):
    """Spherical-cap surface from base diameter and rise (2*pi*R*h)."""
    radius = diameter_m / 2.0
    sphere_r = (radius * radius + height_m * height_m) / (2.0 * height_m)
    return 2.0 * math.pi * sphere_r * height_m


def _cap_meridian(diameter_m, height_m):
    """Meridian arc length from base to crown of a spherical cap."""
    radius = diameter_m / 2.0
    sphere_r = (radius * radius + height_m * height_m) / (2.0 * height_m)
    cosine = (sphere_r - height_m) / sphere_r
    return sphere_r * math.acos(max(-1.0, min(1.0, cosine)))


def _optional_mm(name, value):
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        raise ShapeError("%s: expected a number, got %r" % (name, value))
    if number < 0:
        raise ShapeError("%s must not be negative" % name)
    return number / 1000.0


def dome_area(diameter_mm, height_mm, diameter_inner_mm=0.0, ring_mm=0.0,
              base_dia_mm=0.0, base_mm=0.0, joints_n=0, joint_w_mm=0.0):
    """Dome / spherical cap: sandwich skins, ring beam and site joints.

    The outer skin follows the spherical-cap area from base diameter and
    rise; the inner skin (when its diameter is given) sits concentrically
    on PU foam board. A ring beam (cylindrical wall below the spring line),
    a base ring and the site-laminated panel joint strips are added when
    their sizes are given. Hemispheres are domes with rise = diameter / 2.
    Skins carry a paint finish (no gelcoat); the PU core is the mean area
    between the two skins.
    """
    outer = _positive("diameter", diameter_mm) / 1000.0
    rise = _positive("height", height_mm) / 1000.0
    inner_d = _optional_mm("inner diameter", diameter_inner_mm)
    ring_h = _optional_mm("ring beam height", ring_mm)
    base_h = _optional_mm("base ring height", base_mm)
    base_d = _optional_mm("base ring diameter", base_dia_mm)
    joint_w = _optional_mm("joint strip width", joint_w_mm)
    try:
        joints = int(joints_n or 0)
    except (TypeError, ValueError):
        raise ShapeError("joints count: expected a whole number, got %r"
                         % (joints_n,))
    if joints < 0:
        raise ShapeError("joints count must not be negative")
    outer_area = _cap_area(outer, rise)
    parts = [{"label": "Dome - outer skin", "area_m2": outer_area,
              "layup": "dome_outer", "coat": "paint", "wall": True}]
    inner_area = 0.0
    if inner_d > 0:
        if inner_d >= outer:
            raise ShapeError("inner diameter must be smaller than the outer "
                             "diameter for a sandwich dome")
        buildup = (outer - inner_d) / 2.0
        if rise - buildup <= 0:
            raise ShapeError("dome rise is too small for that sandwich "
                             "build-up")
        inner_area = _cap_area(inner_d, rise - buildup)
        parts.append({"label": "Dome - inner skin", "area_m2": inner_area,
                      "layup": "dome_inner", "coat": "paint", "wall": True,
                      "core": {"material": "pufoam",
                               "area_m2": (outer_area + inner_area) / 2.0}})
    if ring_h > 0:
        ring_outer = math.pi * outer * ring_h
        parts.append({"label": "Ring beam - outer", "area_m2": ring_outer,
                      "layup": "dome_outer", "coat": "paint", "wall": True})
        if inner_d > 0:
            ring_inner = math.pi * inner_d * ring_h
            parts.append({"label": "Ring beam - inner",
                          "area_m2": ring_inner, "layup": "dome_inner",
                          "coat": "paint", "wall": True,
                          "core": {"material": "pufoam",
                                   "area_m2": (ring_outer + ring_inner) / 2.0}})
    if base_h > 0:
        base_ring_d = base_d if base_d > 0 else outer
        parts.append({"label": "Base ring flashing",
                      "area_m2": math.pi * base_ring_d * base_h,
                      "layup": "dome_outer", "coat": "paint"})
    warnings = []
    if joints > 0:
        if joint_w <= 0:
            joint_w = 0.15
            warnings.append("Joint strip width not given; 150 mm used - "
                            "confirm against the site joint detail.")
        strips = joints * _cap_meridian(outer, rise) * joint_w
        parts.append({"label": "Site joint strips", "area_m2": strips,
                      "layup": "cabin_inner", "coat": "none"})
    return {
        "area_m2": sum(p["area_m2"] for p in parts),
        "parts": parts,
        "warnings": warnings,
    }


def sphere_area(diameter_mm, diameter_inner_mm=0.0):
    """Full sphere (4*pi*R^2): outer skin plus optional inner sandwich skin."""
    outer = _positive("diameter", diameter_mm) / 1000.0
    try:
        inner_d = float(diameter_inner_mm or 0.0) / 1000.0
    except (TypeError, ValueError):
        raise ShapeError("inner diameter: expected a number, got %r"
                         % (diameter_inner_mm,))
    if inner_d < 0:
        raise ShapeError("inner diameter must not be negative")
    parts = [{"label": "Sphere - outer skin",
              "area_m2": math.pi * outer * outer,
              "layup": "dome_outer", "coat": "gelcoat", "wall": True}]
    if inner_d > 0:
        if inner_d >= outer:
            raise ShapeError("inner diameter must be smaller than the outer "
                             "diameter for a sandwich sphere")
        inner_area = math.pi * inner_d * inner_d
        parts.append({"label": "Sphere - inner skin", "area_m2": inner_area,
                      "layup": "dome_inner", "coat": "gelcoat", "wall": True,
                      "core": {"material": "pufoam", "area_m2": inner_area}})
    return {
        "area_m2": sum(p["area_m2"] for p in parts),
        "parts": parts,
        "warnings": [],
    }


#: Sandwich build-ups for the cabin shape (metres, per side unless stated).
CABIN_WALL_M = 0.025  # wall sandwich each side: 50 mm off plan dims
CABIN_FLOOR_ROOF_M = 0.200  # floor + roof sandwich off the height
CABIN_ROOF_OVERHANG_M = 0.100  # roof overhang per side
CABIN_HOOD_M2 = 0.35  # rain hood laminate per door/window opening


def cabin_area(length_mm, width_mm, height_mm, openings_count=0,
               openings=(), plinth_mm=200.0, overhang_mm=100.0,
               cornice_mm=350.0, sandwich=True):
    """Fitted GRP cabin / enclosure: sandwich skins, cores and trims.

    Outer and inner wall skins carry their own laminate schedules; the
    inner walls and roof sit on PU foam board and the floor on plywood.
    Cornice, plinth and one rain hood per opening are costed as trims,
    plus reveals around the openings and corner bonding strips. Each part
    names its layup, surface coat and core (if any); wall skins are
    flagged so openings deduct from every skin they pierce. Plinth,
    overhang and cornice sizes (0 = none) and the sandwich flag mirror
    the drawing details the user confirms on review.
    """
    length = _positive("length", length_mm) / 1000.0
    width = _positive("width", width_mm) / 1000.0
    height = _positive("height", height_mm) / 1000.0
    inner_l = length - 2 * CABIN_WALL_M
    inner_w = width - 2 * CABIN_WALL_M
    inner_h = height - CABIN_FLOOR_ROOF_M
    if min(inner_l, inner_w, inner_h) <= 0:
        raise ShapeError("Cabin is too small for the 25 mm wall / 200 mm "
                         "floor+roof sandwich build-up.")
    try:
        hoods = max(0, int(openings_count))
    except (TypeError, ValueError):
        raise ShapeError("openings_count: expected a whole number, got %r"
                         % (openings_count,))
    plinth_h = _optional_mm("plinth height", plinth_mm)
    overhang = _optional_mm("roof overhang", overhang_mm)
    cornice_h = _optional_mm("cornice height", cornice_mm)
    sandwich = bool(sandwich)
    perimeter = 0.0
    for opening in openings or []:
        try:
            perimeter += (2 * (float(opening.get("width_m", 0.0))
                               + float(opening.get("height_m", 0.0)))
                          * float(opening.get("qty", 0.0)))
        except (TypeError, ValueError):
            raise ShapeError("cabin openings: size/qty must be numbers")
    outer = 2 * (length + width) * inner_h
    inner = 2 * (inner_l + inner_w) * inner_h if sandwich else 0.0
    roof = (length + 2 * overhang) * (width + 2 * overhang)
    floor = inner_l * inner_w
    ceiling = floor if sandwich else 0.0
    parts = [
        {"label": "Walls - outer skin", "area_m2": outer,
         "layup": "cabin_outer", "coat": "gelcoat", "wall": True},
        {"label": "Walls - inner skin", "area_m2": inner,
         "layup": "cabin_inner", "coat": "flowcoat", "wall": True,
         "core": {"material": "pufoam", "area_m2": inner}},
        {"label": "Roof - top skin", "area_m2": roof,
         "layup": "cabin_roof", "coat": "gelcoat",
         "core": {"material": "pufoam", "area_m2": roof}},
        {"label": "Ceiling - inner skin", "area_m2": ceiling,
         "layup": "cabin_inner", "coat": "flowcoat"},
        {"label": "Floor - top laminate", "area_m2": floor,
         "layup": "cabin_floor", "coat": "flowcoat",
         "core": {"material": "plywood", "area_m2": floor}},
        {"label": "Base - underside skin",
         "area_m2": (length + 0.04) * (width + 0.04),  # 20 mm drip edge/side
         "layup": "cabin_inner", "coat": "none"},
        {"label": "Plinth",
         "area_m2": (2 * (length + width) + 0.16) * plinth_h,
         "layup": "cabin_outer", "coat": "gelcoat"},
        {"label": "Cornice moulding",
         "area_m2": (2 * (length + width) + 0.8) * cornice_h,
         "layup": "cabin_outer", "coat": "gelcoat"},
        {"label": "Hoods over openings",
         "area_m2": hoods * 1.0 * CABIN_HOOD_M2,
         "layup": "cabin_outer", "coat": "gelcoat"},
        {"label": "Reveals around openings",
         "area_m2": perimeter * 0.05,
         "layup": "cabin_inner", "coat": "flowcoat"},
        {"label": "Joint / corner bonding strips",
         "area_m2": (4 * inner_h + 4 * (length + width)) * 0.15,
         "layup": "cabin_inner", "coat": "none"},
    ]
    return {
        "area_m2": sum(p["area_m2"] for p in parts),
        "parts": parts,
        "warnings": [],
    }


#: Field metadata per shape: key, label, required, default for optionals.
#: A field may carry "kind": "area" (square metres, no unit choice).
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
    "box": {
        "label": "Box tank / enclosure",
        "blurb": "Rectangular tank, chamber, cabinet or kiosk.",
        "fields": [
            {"key": "length", "label": "Length", "required": True},
            {"key": "width", "label": "Width", "required": True},
            {"key": "height", "label": "Height", "required": True},
            {"key": "thickness", "label": "Target laminate thickness", "required": True},
        ],
        "options": [
            {"key": "open_top", "label": "Open top (no lid)", "default": True},
        ],
        "assumptions": [
            "Four walls plus bottom; lid only when open top is off.",
            "No internal baffles, frames or lid stiffeners included.",
        ],
    },
    "custom": {
        "label": "Free-form part (measured area)",
        "blurb": "Boat hulls and guards: surface measured from mould or plug.",
        "fields": [
            {"key": "area", "label": "Measured surface area", "required": True,
             "kind": "area"},
            {"key": "thickness", "label": "Target laminate thickness", "required": True},
        ],
        "options": [
        ],
        "assumptions": [
            "Surface area is measured, not computed - verify it against the mould.",
            "No stringers, transom core or fit-out included.",
            "For domes or spheres use the Dome / Sphere shape - it computes the area.",
        ],
    },
    "cabin": {
        "label": "GRP cabin / fitted enclosure",
        "blurb": "Security cabins and kiosks: sandwich walls, cores and trims.",
        "fields": [
            {"key": "length", "label": "Overall length", "required": True},
            {"key": "width", "label": "Overall width", "required": True},
            {"key": "height", "label": "Overall height", "required": True},
            {"key": "thickness", "label": "Outer skin target", "required": True},
        ],
        "options": [
        ],
        "assumptions": [
            "Sandwich walls: outer skin 3xCSM450, inner skin 2xCSM450 on PU foam.",
            "Inner dims 50 mm inside plan, 200 mm off height (floor + roof).",
            "Roof/floor heavy laminate; floor core is 18 mm marine plywood.",
            "Cornice, plinth and one rain hood per opening included as trims.",
        ],
    },
    "dome": {
        "label": "Dome / spherical cap",
        "blurb": "Mosque and building domes: cap area from diameter and rise.",
        "fields": [
            {"key": "diameter", "label": "Base diameter (outer)", "required": True},
            {"key": "height", "label": "Rise (cap height, outer)", "required": True},
            {"key": "diameter_inner", "label": "Inner skin diameter (blank = single skin)",
             "required": False},
            {"key": "thickness", "label": "Outer skin target", "required": True},
            {"key": "ring_mm", "label": "Ring beam height (blank = none)",
             "required": False, "default": 0.0},
            {"key": "base_dia_mm", "label": "Base ring diameter (blank = base dia)",
             "required": False, "default": 0.0},
            {"key": "base_mm", "label": "Base ring height (blank = none)",
             "required": False, "default": 0.0},
            {"key": "joints_n", "label": "Site-laminated panel joints (count)",
             "required": False, "kind": "count", "default": 0},
            {"key": "joint_w_mm", "label": "Joint strip width (blank = 150 mm)",
             "required": False, "default": 0.0},
        ],
        "options": [
        ],
        "assumptions": [
            "Spherical-cap surface 2*pi*R*h from base diameter and rise.",
            "Hemisphere = rise of half the diameter.",
            "Inner skin (when given) sits concentrically on PU foam board.",
            "Ring beam, base ring and site joint strips added when sized.",
            "Paint finish both faces (no gelcoat); steel weighed separately.",
        ],
    },
    "sphere": {
        "label": "Sphere (full ball)",
        "blurb": "Ornamental GRP spheres: full-ball area from diameter.",
        "fields": [
            {"key": "diameter", "label": "Diameter (outer)", "required": True},
            {"key": "diameter_inner", "label": "Inner skin diameter (blank = single skin)",
             "required": False},
            {"key": "thickness", "label": "Outer skin target", "required": True},
        ],
        "options": [
        ],
        "assumptions": [
            "Full-sphere surface 4*pi*R^2 from the outer diameter.",
            "Inner skin (when given) sits concentrically on PU foam board.",
            "Support frame and fixings are not included.",
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
    if shape_id == "box":
        return box_area(dims_mm["length"], dims_mm["width"], dims_mm["height"],
                        open_top=bool(options.get("open_top", True)))
    if shape_id == "custom":
        return custom_area(dims_mm["area"])
    if shape_id == "cabin":
        return cabin_area(dims_mm["length"], dims_mm["width"],
                          dims_mm["height"],
                          openings_count=options.get("openings_count", 0),
                          openings=options.get("openings") or (),
                          plinth_mm=options.get("plinth_mm", 200.0),
                          overhang_mm=options.get("overhang_mm", 100.0),
                          cornice_mm=options.get("cornice_mm", 350.0),
                          sandwich=options.get("sandwich", True))
    if shape_id == "dome":
        return dome_area(dims_mm["diameter"], dims_mm["height"],
                         dims_mm.get("diameter_inner") or 0.0,
                         ring_mm=dims_mm.get("ring_mm") or 0.0,
                         base_dia_mm=dims_mm.get("base_dia_mm") or 0.0,
                         base_mm=dims_mm.get("base_mm") or 0.0,
                         joints_n=dims_mm.get("joints_n") or 0,
                         joint_w_mm=dims_mm.get("joint_w_mm") or 0.0)
    if shape_id == "sphere":
        return sphere_area(dims_mm["diameter"],
                           dims_mm.get("diameter_inner") or 0.0)
    raise ShapeError("No area function for shape %r" % shape_id)  # unreachable


def required_fields(shape_id):
    return [f["key"] for f in get_shape(shape_id)["fields"] if f["required"]]