"""Deterministic material and cost engine.

Formulas preserve the original GFPF MVP conventions; geometry comes from
the shape library. No network or AI calls here.
"""

from __future__ import annotations

from . import shapes

CURRENCY = "BD"

#: Factory material rates (DEMO values - replace with verified rates).
DEFAULT_RATES = {
    "resin": 0.950,  # BD per kg polyester resin
    "fiber": 1.200,  # BD per kg fiberglass
    "mekp": 2.000,  # BD per kg catalyst
    "labour": 2.000,  # BD per labour hour
    "consumables": 0.400,  # BD flat per piece
}

#: Laminate recipe / factory assumptions (all editable inputs).
DEFAULT_RECIPE = {
    "density_kg_m3": 1500.0,
    "resin_pct": 70.0,
    "fiber_pct": 30.0,
    "mekp_pct": 1.5,  # of resin mass including wastage (MVP convention)
    "wastage_pct": 10.0,  # applied to fibre and resin
    "labour_hours": 1.0,  # per piece
    "overhead_pct": 10.0,  # on subtotal including labour
}

#: Cost elements the engine never charges; shown on every estimate.
EXCLUSIONS = [
    "Mould / tooling manufacture or amortisation",
    "Delivery, packing and installation",
    "Testing, inspection and certification",
    "Surface extras (gelcoat upgrades, painting) unless added as consumables",
    "Profit margin, markup and selling price (cost estimate only)",
    "Taxes and duties",
]

RATE_LABELS = {
    "resin": "Polyester resin (BD/kg)",
    "fiber": "Fiberglass (BD/kg)",
    "mekp": "MEKP catalyst (BD/kg)",
    "labour": "Labour (BD/hour)",
    "consumables": "Consumables (BD/pc flat)",
}


class CostingError(ValueError):
    """Invalid recipe, rates or quantities."""


def _merge(values, defaults, name):
    merged = dict(defaults)
    for key, value in (values or {}).items():
        if key not in merged:
            raise CostingError("Unknown %s field %r" % (name, key))
        try:
            merged[key] = float(value)
        except (TypeError, ValueError):
            raise CostingError("%s.%s: expected a number, got %r" % (name, key, value))
    return merged


def _check_non_negative(mapping, name):
    for key, value in mapping.items():
        if value < 0:
            raise CostingError("%s.%s must not be negative (got %s)" % (name, key, value))


def _fmt(number):
    text = "%.3f" % number
    return text.rstrip("0").rstrip(".") if "." in text else text


def calculate(shape_id, dims_mm, qty=1, recipe=None, rates=None, options=None):
    """Full material + cost breakdown. Raises ShapeError/CostingError."""
    spec = shapes.get_shape(shape_id)
    recipe = _merge(recipe, DEFAULT_RECIPE, "recipe")
    rates = _merge(rates, DEFAULT_RATES, "rates")
    _check_non_negative(recipe, "recipe")
    _check_non_negative(rates, "rates")
    if recipe["density_kg_m3"] <= 0:
        raise CostingError("recipe.density_kg_m3 must be greater than zero")
    if abs(recipe["resin_pct"] + recipe["fiber_pct"] - 100.0) > 0.01:
        raise CostingError(
            "resin %% + fiber %% must equal 100 (got %.2f)"
            % (recipe["resin_pct"] + recipe["fiber_pct"])
        )
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise CostingError("qty: expected a whole number, got %r" % (qty,))
    if qty < 1:
        raise CostingError("qty must be at least 1 (got %s)" % qty)

    thickness_mm = float(dims_mm["thickness"])
    if thickness_mm <= 0:
        raise CostingError("thickness must be greater than zero")
    area = shapes.compute_area(shape_id, dims_mm, options)
    area_m2 = area["area_m2"]

    laminate_kg = area_m2 * (thickness_mm / 1000.0) * recipe["density_kg_m3"]
    uplift = 1.0 + recipe["wastage_pct"] / 100.0
    fiber_kg = laminate_kg * (recipe["fiber_pct"] / 100.0) * uplift
    resin_kg = laminate_kg * (recipe["resin_pct"] / 100.0) * uplift
    mekp_kg = resin_kg * (recipe["mekp_pct"] / 100.0)

    resin_bd = resin_kg * rates["resin"]
    fiber_bd = fiber_kg * rates["fiber"]
    mekp_bd = mekp_kg * rates["mekp"]
    consumables_bd = rates["consumables"]
    material_bd = resin_bd + fiber_bd + mekp_bd + consumables_bd
    labour_bd = recipe["labour_hours"] * rates["labour"]
    subtotal_pc_bd = material_bd + labour_bd
    batch_bd = subtotal_pc_bd * qty
    overhead_bd = batch_bd * recipe["overhead_pct"] / 100.0
    total_bd = batch_bd + overhead_bd

    lines = [
        {
            "label": "Polyester resin",
            "qty": resin_kg,
            "unit": "kg",
            "rate": rates["resin"],
            "amount": resin_bd,
        },
        {
            "label": "Fiberglass",
            "qty": fiber_kg,
            "unit": "kg",
            "rate": rates["fiber"],
            "amount": fiber_bd,
        },
        {
            "label": "MEKP catalyst",
            "qty": mekp_kg,
            "unit": "kg",
            "rate": rates["mekp"],
            "amount": mekp_bd,
        },
        {
            "label": "Consumables (flat per piece)",
            "qty": 1.0,
            "unit": "pc",
            "rate": consumables_bd,
            "amount": consumables_bd,
        },
        {
            "label": "Labour",
            "qty": recipe["labour_hours"],
            "unit": "hr",
            "rate": rates["labour"],
            "amount": labour_bd,
        },
    ]

    assumptions = list(spec["assumptions"]) + [
        "Laminate density %.0f kg/m3; uniform %s mm laminate."
        % (recipe["density_kg_m3"], _fmt(thickness_mm)),
        "Resin/fibre %s/%s with %.1f%% wastage on both."
        % (_fmt(recipe["resin_pct"]), _fmt(recipe["fiber_pct"]), recipe["wastage_pct"]),
        "MEKP %.2f%% of resin mass (after wastage)." % recipe["mekp_pct"],
        "Overhead %.1f%% on subtotal including labour; batch of %d."
        % (recipe["overhead_pct"], qty),
        "Material rates are DEMO values unless replaced with verified factory rates.",
        "Material and cost estimate only - not a structural, pressure or certification rating.",
    ]

    return {
        "shape_id": shape_id,
        "shape_label": spec["label"],
        "dims_mm": {k: float(v) for k, v in dims_mm.items()},
        "options": dict(options or {}),
        "qty": qty,
        "recipe": recipe,
        "rates": rates,
        "currency": CURRENCY,
        "area_m2": area_m2,
        "area_parts": area["parts"],
        "laminate_kg": laminate_kg,
        "fiber_kg": fiber_kg,
        "resin_kg": resin_kg,
        "mekp_kg": mekp_kg,
        "lines": lines,
        "material_bd": material_bd,
        "labour_bd": labour_bd,
        "subtotal_pc_bd": subtotal_pc_bd,
        "batch_bd": batch_bd,
        "overhead_bd": overhead_bd,
        "total_bd": total_bd,
        "per_piece_bd": total_bd / qty,
        "assumptions": assumptions,
        "exclusions": list(EXCLUSIONS),
        "warnings": list(area.get("warnings", [])),
    }