"""Standard GRP laminate schedules for hand lay-up products.

Glass data follows the factory material catalogue (per-glass resin uptake
matching trade estimating guides: CSM450 ~1.0 kg resin/m2, CSM600 ~1.4 kg,
CSM300 ~0.65 kg). Product recipes mirror the catalogue schedules with their
own gelcoat coverage and nominal thickness. Cured ply thicknesses are
workshop-typical values for consolidating by hand roller.
"""

from __future__ import annotations


class LayupError(ValueError):
    """Unknown schedule or reinforcement."""


#: Reinforcement catalogue: glass weight, resin uptake and cured thickness.
REINFORCEMENTS = {
    "csm300": {"label": "CSM 300 g/m2", "gsm": 300, "resin_ratio": 2.2, "mm": 0.8},
    "csm450": {"label": "CSM 450 g/m2", "gsm": 450, "resin_ratio": 2.2, "mm": 1.1},
    "csm600": {"label": "CSM 600 g/m2", "gsm": 600, "resin_ratio": 2.3, "mm": 1.4},
    "wr600": {"label": "Woven roving 600 g/m2", "gsm": 600, "resin_ratio": 1.3, "mm": 0.8},
    "wr800": {"label": "Woven roving 800 g/m2", "gsm": 800, "resin_ratio": 1.3, "mm": 1.0},
}

#: Default gelcoat coverage when a schedule does not set its own.
GELCOAT_KG_M2 = 0.55
GELCOAT_MM = 0.5

#: Paint/topcoat coverage per m2.
PAINT_KG_M2 = 0.15

#: Workshop-typical hand lay-up output for labour estimating (single worker).
MOULD_PREP_HR = 0.5  # base mould prep per part
MOULD_PREP_HR_M2 = 0.10  # extra prep per m2
GELCOAT_M2_PER_HR = 20.0  # spray/brush output
PLY_M2_PER_HR = 12.0  # wet-out output per ply m2
FINISH_HR = 0.5  # base demould/trim per part
FINISH_HR_M2 = 0.15  # extra finishing per m2


def estimate_labour_hours(area_m2, schedule_id, with_gelcoat=None):
    """Estimated single-worker hours from part area and ply count.

    Mould prep + gelcoat + wet-out per ply + trim/finish. The review page
    pre-fills this and the user can overwrite it.
    """
    spec = get_schedule(schedule_id)
    if with_gelcoat is None:
        with_gelcoat = spec["gelcoat"]
    if schedule_id == "classic":
        plies = 3  # generic allowance when no ply schedule is picked
    else:
        plies = len(spec["layers"])
    hours = MOULD_PREP_HR + MOULD_PREP_HR_M2 * area_m2
    if with_gelcoat:
        hours += area_m2 / GELCOAT_M2_PER_HR
    hours += area_m2 * plies / PLY_M2_PER_HR
    hours += FINISH_HR + FINISH_HR_M2 * area_m2
    return max(0.5, round(hours, 1))

#: Standard layups in application order after the gelcoat. Woven roving is
#: always sandwiched between CSM skins, per boat-building practice.
SCHEDULES = {
    "classic": {
        "label": "Classic (resin/fibre %)",
        "blurb": "Legacy percentage recipe instead of a ply schedule.",
        "layers": [],
        "gelcoat": False,
        "gelcoat_kg_m2": GELCOAT_KG_M2,
    },
    "cover_light": {
        "label": "Light cover (CSM450+300+450)",
        "blurb": "Dust bins, small covers and trims.",
        "layers": ["csm450", "csm300", "csm450"],
        "gelcoat": True,
        "gelcoat_kg_m2": 0.55,
    },
    "enclosure": {
        "label": "Enclosure (CSM+WR600)",
        "blurb": "Electrical enclosures, cabinets and kiosks.",
        "layers": ["csm450", "csm300", "csm300", "wr600", "csm450"],
        "gelcoat": True,
        "gelcoat_kg_m2": 0.60,
    },
    "tank_medium": {
        "label": "Water tank standard (6 mm)",
        "blurb": "Above-ground water tanks.",
        "layers": ["csm450", "csm300", "wr600", "wr600", "wr600", "csm450"],
        "gelcoat": True,
        "gelcoat_kg_m2": 0.55,
    },
    "tank_heavy": {
        "label": "Water tank heavy (10 mm)",
        "blurb": "Large, underground or sewerage tanks.",
        "layers": ["csm450", "csm300", "wr600", "wr600", "wr600", "csm600",
                   "csm600", "wr600", "wr600", "wr600", "csm450"],
        "gelcoat": True,
        "gelcoat_kg_m2": 0.65,
    },
    "boat_hull": {
        "label": "Boat hull (CSM/WR800 alternating)",
        "blurb": "Small boat hulls: CSM skins with WR800 core.",
        "layers": ["csm300", "csm450", "wr800", "csm450", "wr800", "csm450"],
        "gelcoat": True,
        "gelcoat_kg_m2": 0.65,
    },
    "panel_struct": {
        "label": "Structural panel (CSM+WR600)",
        "blurb": "Load-bearing flat panels and cabinet walls.",
        "layers": ["csm450", "csm300", "wr600", "csm450"],
        "gelcoat": True,
        "gelcoat_kg_m2": 0.55,
    },
    "cabin_outer": {
        "label": "Cabin outer skin (3xCSM450)",
        "blurb": "Cabin/enclosure outer sandwich skin with beige gelcoat.",
        "layers": ["csm450", "csm450", "csm450"],
        "gelcoat": True,
        "gelcoat_kg_m2": 0.60,
    },
    "cabin_inner": {
        "label": "Cabin inner skin (2xCSM450)",
        "blurb": "Cabin/enclosure inner sandwich skin with white flowcoat.",
        "layers": ["csm450", "csm450"],
        "gelcoat": True,
        "gelcoat_kg_m2": 0.40,
    },
    "cabin_roof": {
        "label": "Cabin roof (4xCSM450+WR600)",
        "blurb": "Cabin roof laminate on PU foam with beige gelcoat.",
        "layers": ["csm450", "csm450", "wr600", "csm450", "csm450"],
        "gelcoat": True,
        "gelcoat_kg_m2": 0.60,
    },
    "cabin_floor": {
        "label": "Cabin floor (4xCSM450+WR600)",
        "blurb": "Cabin floor laminate on plywood with white flowcoat.",
        "layers": ["csm450", "csm450", "wr600", "csm450", "csm450"],
        "gelcoat": True,
        "gelcoat_kg_m2": 0.40,
    },
    "dome_outer": {
        "label": "Dome outer skin (6xCSM450+WR600)",
        "blurb": "Dome/sphere outer sandwich skin, paint finish.",
        "layers": ["csm450", "csm450", "csm450", "wr600",
                   "csm450", "csm450", "csm450"],
        "gelcoat": False,
        "gelcoat_kg_m2": 0.60,
    },
    "dome_inner": {
        "label": "Dome inner skin (4xCSM450)",
        "blurb": "Dome/sphere inner sandwich skin, paint finish.",
        "layers": ["csm450", "csm450", "csm450", "csm450"],
        "gelcoat": False,
        "gelcoat_kg_m2": 0.40,
    },
}

#: Workshop-typical rates for fitted-assembly labour (single worker).
#: Shared by cabins, domes and spheres: fixed shop hours plus per-m2,
#: per-opening and per-electrical-point rates from the standard book.
CABIN_PREP_HR = 6.0  # mould preparation, wax & release per unit
CABIN_LAMINATE_HR_M2 = 1.062  # gelcoat + hand lay-up per m2
CABIN_ASSEMBLY_HR_M2 = 0.531  # core fitting, panel assembly & bonding
CABIN_TRIM_HR_M2 = 0.3185  # demoulding, trimming, grinding
CABIN_FINISH_HR_M2 = 0.4247  # filling, flowcoat, polishing
CABIN_FIT_HR_OPENING = 2.667  # door/window fixing & sealing each
CABIN_ELEC_HR_POINT = 1.333  # electrical installation per point
CABIN_QC_HR = 4.0  # QC, cleaning & packing per unit


def estimate_cabin_labour(net_area_m2, n_openings=0, elec_points=0):
    """Assembly labour as operation lines [(label, hours)].

    Hours scale from the net laminate area (openings deducted), the
    opening count and the electrical point count. The electrical
    operation is omitted when the unit has no wired points. Cabins,
    domes and spheres share this table.
    """
    area = max(0.0, float(net_area_m2))
    try:
        openings = max(0, int(n_openings))
    except (TypeError, ValueError):
        openings = 0
    try:
        points = max(0, int(elec_points))
    except (TypeError, ValueError):
        points = 0
    ops = [
        ("Mould preparation, wax & release", CABIN_PREP_HR),
        ("Gelcoat + lamination", CABIN_LAMINATE_HR_M2 * area),
        ("Core fitting, assembly & bonding", CABIN_ASSEMBLY_HR_M2 * area),
        ("Demoulding, trimming, grinding", CABIN_TRIM_HR_M2 * area),
        ("Finishing: filling, flowcoat, polishing",
         CABIN_FINISH_HR_M2 * area),
        ("Fixing door, windows & sealing",
         CABIN_FIT_HR_OPENING * openings),
        ("QC, cleaning & packing", CABIN_QC_HR),
    ]
    if points:
        ops.insert(6, ("Electrical installation",
                       CABIN_ELEC_HR_POINT * points))
    return [(label, round(hours, 1)) for label, hours in ops]

SCHEDULE_IDS = tuple(SCHEDULES)


def get_schedule(schedule_id):
    try:
        return SCHEDULES[schedule_id]
    except KeyError:
        raise LayupError(
            "Unknown laminate schedule %r (expected one of %s)"
            % (schedule_id, ", ".join(SCHEDULE_IDS))
        )


def schedule_thickness(schedule_id, with_gelcoat=None):
    """Cured thickness in mm for a schedule (gelcoat included by default)."""
    spec = get_schedule(schedule_id)
    if with_gelcoat is None:
        with_gelcoat = spec["gelcoat"]
    total = sum(REINFORCEMENTS[layer]["mm"] for layer in spec["layers"])
    if with_gelcoat:
        total += GELCOAT_MM
    return total


def schedule_glass_per_m2(schedule_id):
    """Glass kg/m2 per reinforcement for one ply schedule."""
    spec = get_schedule(schedule_id)
    glass = {}
    for layer in spec["layers"]:
        glass[layer] = glass.get(layer, 0.0) + REINFORCEMENTS[layer]["gsm"] / 1000.0
    return glass


def schedule_resin_per_m2(schedule_id):
    """Resin kg/m2 (before wastage) to wet out a ply schedule."""
    spec = get_schedule(schedule_id)
    resin = 0.0
    for layer in spec["layers"]:
        info = REINFORCEMENTS[layer]
        resin += (info["gsm"] / 1000.0) * info["resin_ratio"]
    return resin


def schedule_gelcoat_per_m2(schedule_id):
    """Gelcoat kg/m2 for a schedule."""
    return get_schedule(schedule_id).get("gelcoat_kg_m2", GELCOAT_KG_M2)


def schedule_label(schedule_id, with_gelcoat=None):
    """Select label with cured thickness, e.g. '... (~4.9 mm)'."""
    spec = get_schedule(schedule_id)
    if schedule_id == "classic":
        return spec["label"]
    return "%s (~%.1f mm)" % (spec["label"], schedule_thickness(schedule_id, with_gelcoat))
