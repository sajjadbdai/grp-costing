"""Deterministic material and cost engine.

Formulas preserve the original GFPF MVP conventions; geometry comes from
the shape library. No network or AI calls here.
"""

from __future__ import annotations

import re

from . import layup as layups
from . import shapes

CURRENCY = "BD"

#: Factory material rates (DEMO values - replace with verified rates).
DEFAULT_RATES = {
    "resin": 0.950,  # BD per kg GP/ortho polyester resin (MVP legacy)
    "resin_iso": 0.950,  # BD per kg isophthalic resin
    "resin_ve": 1.350,  # BD per kg vinyl ester resin
    "fiber": 1.200,  # BD per kg generic fiberglass (legacy classic recipe)
    "mekp": 2.000,  # BD per kg catalyst (MVP legacy)
    "labour": 2.000,  # BD per labour hour
    "machine": 2.000,  # BD per machine hour
    "csm300": 0.550,  # BD per kg CSM 300 g/m2
    "csm450": 0.530,  # BD per kg CSM 450 g/m2
    "csm600": 0.510,  # BD per kg CSM 600 g/m2
    "wr600": 0.750,  # BD per kg woven roving 600 g/m2
    "wr800": 0.750,  # BD per kg woven roving 800 g/m2
    "gelcoat": 1.500,  # BD per kg gelcoat
    "tissue": 0.090,  # BD per m2 surface tissue 30 g/m2
    "pigment": 1.900,  # BD per kg pigment paste
    "paint": 2.500,  # BD per kg paint / topcoat
    "paste": 1.500,  # BD per kg bonding paste / filler
    "plywood": 4.000,  # BD per m2 marine plywood 18 mm (supports)
    "steel": 0.280,  # BD per kg mild steel (supports)
    "foam": 4.500,  # BD per m2 PU foam board 20 mm (sandwich core)
}

#: Recipe field labels for forms.
RECIPE_LABELS = {
    "density_kg_m3": "Density (kg/m3)",
    "resin_pct": "Resin %",
    "fiber_pct": "Fiber %",
    "mekp_pct": "MEKP %",
    "pigment_pct": "Pigment %",
    "iso_share_pct": "ISO skin-coat share %",
    "wastage_pct": "Wastage %",
    "consumables_pct": "Consumables %",
    "labour_hours": "Labour hrs/pc",
    "machine_hours": "Machine hrs/pc",
    "overhead_pct": "Overhead %",
}

#: Resin selector: id -> (label, rate key).
RESIN_TYPES = {
    "gp": ("GP / ortho polyester", "resin"),
    "iso": ("Isophthalic", "resin_iso"),
    "ve": ("Vinyl ester", "resin_ve"),
}

#: Laminate recipe / factory assumptions (all editable inputs).
DEFAULT_RECIPE = {
    "density_kg_m3": 1500.0,
    "resin_pct": 70.0,
    "fiber_pct": 30.0,
    "mekp_pct": 1.5,  # of resin + gelcoat mass including wastage
    "pigment_pct": 0.0,  # of gelcoat mass
    "iso_share_pct": 15.0,  # of resin as ISO skin coat behind gelcoat
    "wastage_pct": 10.0,  # applied to fibre, resin and gelcoat
    "consumables_pct": 5.0,  # of GRP materials (rollers, acetone, wax...)
    "labour_hours": 1.0,  # per piece
    "machine_hours": 0.0,  # per piece
    "overhead_pct": 10.0,  # on direct cost incl. mould + delivery/testing
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
    "resin": "GP polyester resin (BD/kg)",
    "resin_iso": "Isophthalic resin (BD/kg)",
    "resin_ve": "Vinyl ester resin (BD/kg)",
    "fiber": "Fiberglass generic (BD/kg, classic)",
    "mekp": "MEKP catalyst (BD/kg)",
    "labour": "Labour (BD/hour)",
    "machine": "Machine (BD/hour)",
    "csm300": "CSM 300 (BD/kg)",
    "csm450": "CSM 450 (BD/kg)",
    "csm600": "CSM 600 (BD/kg)",
    "wr600": "Woven roving 600 (BD/kg)",
    "wr800": "Woven roving 800 (BD/kg)",
    "gelcoat": "Gelcoat (BD/kg)",
    "tissue": "Surface tissue 30g (BD/m2)",
    "pigment": "Pigment paste (BD/kg)",
    "paint": "Paint / topcoat (BD/kg)",
    "paste": "Bonding paste / filler (BD/kg)",
    "plywood": "Marine plywood 18mm (BD/m2)",
    "steel": "Mild steel supports (BD/kg)",
    "foam": "PU foam board 20mm (BD/m2)",
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


def _lump(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise CostingError("%s: expected a number, got %r" % (name, value))
    if number < 0:
        raise CostingError("%s must not be negative (got %s)" % (name, value))
    return number


#: Bought-in labels that mark a cabin as electrically wired.
_ELEC_RE = re.compile(r"light|socket|switch|\bdb\b|distribution|split|a/c|"
                      r"air\s*cond", re.IGNORECASE)


def _is_wired(label):
    """True when a bought-in label means site wiring work (the lightning
    arrester is a specialist supply item, not a wiring point)."""
    text = str(label or "")
    return bool(_ELEC_RE.search(text)) and "arrester" not in text.lower()


def _clean_openings(openings):
    """Validated opening rows [{label, width_m, height_m, qty}]."""
    cleaned = []
    for entry in openings or []:
        if not isinstance(entry, dict):
            raise CostingError("Openings must be label/size rows, got %r."
                               % (entry,))
        try:
            width = float(entry.get("width_m", 0.0))
            height = float(entry.get("height_m", 0.0))
            qty = float(entry.get("qty", 0.0))
        except (TypeError, ValueError):
            raise CostingError("Opening %r: size/qty must be numbers."
                               % (entry.get("label") or "?",))
        if min(width, height, qty) < 0:
            raise CostingError("Opening %r: size/qty must not be negative."
                               % (entry.get("label") or "?",))
        cleaned.append({"label": str(entry.get("label") or "Opening"),
                        "width_m": width, "height_m": height, "qty": qty})
    return [o for o in cleaned
            if o["width_m"] > 0 and o["height_m"] > 0 and o["qty"] > 0]


def calculate(shape_id, dims_mm, qty=1, recipe=None, rates=None, options=None,
              layup="classic", gelcoat=None, mould_option="have", mould_cost=0.0,
              plywood_m2=0.0, steel_kg=0.0, resin_type="gp", mould_life_qty=None,
              hardware_cost=0.0, paint=False, extra_area_m2=0.0, delivery_bd=0.0,
              testing_bd=0.0, markup_pct=0.0, tax_pct=0.0, bought_ins=None,
              openings_m2=0.0, openings=None, paste_kg=0.0,
              mekp_on_coat=True, consumables_flat=0.0):
    """Full material + cost breakdown. Raises ShapeError/CostingError."""
    spec = shapes.get_shape(shape_id)
    try:
        schedule = layups.get_schedule(layup)
    except layups.LayupError as exc:
        raise CostingError(str(exc))
    if mould_option not in ("have", "need"):
        raise CostingError("mould_option: expected 'have' or 'need', got %r"
                           % (mould_option,))
    if resin_type not in RESIN_TYPES:
        raise CostingError("resin_type: expected one of %s, got %r"
                           % (", ".join(sorted(RESIN_TYPES)), resin_type))
    mould_cost = _lump(mould_cost, "mould_cost")
    plywood_m2 = _lump(plywood_m2, "plywood_m2")
    steel_kg = _lump(steel_kg, "steel_kg")
    hardware_cost = _lump(hardware_cost, "hardware_cost")
    extra_area_m2 = _lump(extra_area_m2, "extra_area_m2")
    delivery_bd = _lump(delivery_bd, "delivery_bd")
    testing_bd = _lump(testing_bd, "testing_bd")
    markup_pct = _lump(markup_pct, "markup_pct")
    tax_pct = _lump(tax_pct, "tax_pct")
    openings_m2 = _lump(openings_m2, "openings_m2")
    paste_kg = _lump(paste_kg, "paste_kg")
    consumables_flat = _lump(consumables_flat, "consumables_flat")
    mekp_on_coat = bool(mekp_on_coat)
    paint = bool(paint)
    bought_ins = list(bought_ins or [])
    for item in bought_ins:
        if not str(item.get("label") or "").strip():
            raise CostingError("Bought-in item needs a label.")
        for field in ("qty", "rate"):
            try:
                item[field] = float(item.get(field, 0.0))
            except (TypeError, ValueError):
                raise CostingError("Bought-in %r: %s is not a number."
                                   % (item.get("label"), field))
            if item[field] < 0:
                raise CostingError("Bought-in %r: %s must not be negative."
                                   % (item.get("label"), field))
        item["unit"] = str(item.get("unit") or "no")
        item["by_client"] = bool(item.get("by_client", False))
        item["basis"] = str(item.get("basis") or "")
    if gelcoat is None:
        gelcoat = schedule["gelcoat"]
    gelcoat = bool(gelcoat)
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
    if mould_life_qty is None:
        mould_life_qty = qty
    try:
        mould_life_qty = int(mould_life_qty)
    except (TypeError, ValueError):
        raise CostingError("mould_life_qty: expected a whole number, got %r"
                           % (mould_life_qty,))
    if mould_life_qty < 1:
        raise CostingError("mould_life_qty must be at least 1 (got %s)"
                           % mould_life_qty)

    thickness_mm = float(dims_mm["thickness"])
    if thickness_mm <= 0:
        raise CostingError("thickness must be greater than zero")
    openings = _clean_openings(openings)
    if openings:
        openings_m2 = round(sum(o["width_m"] * o["height_m"] * o["qty"]
                                for o in openings), 4)
    area_options = dict(options or {})
    if shape_id == "cabin":
        area_options["openings_count"] = len(openings)
        area_options["openings"] = openings
    area = shapes.compute_area(shape_id, dims_mm, area_options)
    area_m2 = area["area_m2"]
    warnings = list(area.get("warnings", []))
    area_parts = list(area["parts"])
    wall_parts = [p for p in area_parts if p.get("wall")]
    per_part = layup != "classic" and any("layup" in p for p in area_parts)
    if extra_area_m2 > 0:
        area_parts.append({"label": "Extra stiffening / nozzles / flanges (entered)",
                           "area_m2": extra_area_m2})
    if openings_m2 > 0 and wall_parts:
        for part in wall_parts:
            area_parts.append({"label": "Less openings (%s)" % part["label"],
                               "area_m2": -openings_m2})
    elif openings_m2 > 0:
        area_parts.append({"label": "Less door / window openings",
                           "area_m2": -openings_m2})
    n_wall_skins = len(wall_parts) or 1
    area_eff = area_m2 + extra_area_m2 - openings_m2 * n_wall_skins
    if area_eff < 0:
        warnings.append("Openings exceed the shell area - check the openings value.")
        area_eff = 0.0

    uplift = 1.0 + recipe["wastage_pct"] / 100.0
    glass_kg = {}
    core_m2 = {"pufoam": 0.0, "plywood": 0.0}
    tissue_m2 = 0.0
    if layup == "classic":
        laminate_kg = area_eff * (thickness_mm / 1000.0) * recipe["density_kg_m3"]
        fiber_kg = laminate_kg * (recipe["fiber_pct"] / 100.0) * uplift
        resin_kg = laminate_kg * (recipe["resin_pct"] / 100.0) * uplift
        schedule_mm = None
        if gelcoat:
            tissue_m2 = area_eff * uplift
    elif per_part:
        resin_kg, gelcoat_kg = 0.0, 0.0
        for part in area["parts"]:
            net = part["area_m2"] - (openings_m2 if part.get("wall") else 0.0)
            net = max(0.0, net)
            try:
                part_layup = part.get("layup") or layup
                layups.get_schedule(part_layup)
            except layups.LayupError as exc:
                raise CostingError(str(exc))
            per_m2 = layups.schedule_glass_per_m2(part_layup)
            for key, value in per_m2.items():
                glass_kg[key] = glass_kg.get(key, 0.0) + value * net * uplift
            resin_kg += layups.schedule_resin_per_m2(part_layup) * net * uplift
            if gelcoat and part.get("coat", "gelcoat") != "none":
                gelcoat_kg += (layups.schedule_gelcoat_per_m2(part_layup)
                               * net * uplift)
            if gelcoat and part.get("coat", "gelcoat") == "gelcoat":
                tissue_m2 += net * uplift
            core = part.get("core") or {}
            if core.get("material") in core_m2:
                core_area = core.get("area_m2", net)
                try:
                    core_net = float(core_area)
                except (TypeError, ValueError):
                    core_net = net
                if part.get("wall"):
                    core_net = max(0.0, core_net - openings_m2)
                core_m2[core["material"]] += core_net * uplift
        if extra_area_m2 > 0:
            per_m2 = layups.schedule_glass_per_m2(layup)
            for key, value in per_m2.items():
                glass_kg[key] = glass_kg.get(key, 0.0) + value * extra_area_m2 * uplift
            resin_kg += layups.schedule_resin_per_m2(layup) * extra_area_m2 * uplift
            if gelcoat:
                gelcoat_kg += (layups.schedule_gelcoat_per_m2(layup)
                               * extra_area_m2 * uplift)
        fiber_kg = sum(glass_kg.values())
        laminate_kg = fiber_kg + resin_kg
        schedule_mm = layups.schedule_thickness(layup, gelcoat)
        if schedule_mm > 0:
            drift = abs(thickness_mm - schedule_mm) / schedule_mm
            if drift > 0.15:
                warnings.append(
                    "Target thickness %s mm differs from the %s schedule (~%.1f mm) "
                    "by %.0f%% - confirm the layup or the thickness before ordering."
                    % (_fmt(thickness_mm), schedule["label"], schedule_mm, drift * 100.0)
                )
    else:
        per_m2 = layups.schedule_glass_per_m2(layup)
        glass_kg = {key: value * area_eff * uplift for key, value in per_m2.items()}
        fiber_kg = sum(glass_kg.values())
        resin_kg = layups.schedule_resin_per_m2(layup) * area_eff * uplift
        laminate_kg = fiber_kg + resin_kg
        schedule_mm = layups.schedule_thickness(layup, gelcoat)
        if schedule_mm > 0:
            drift = abs(thickness_mm - schedule_mm) / schedule_mm
            if drift > 0.15:
                warnings.append(
                    "Target thickness %s mm differs from the %s schedule (~%.1f mm) "
                    "by %.0f%% - confirm the layup or the thickness before ordering."
                    % (_fmt(thickness_mm), schedule["label"], schedule_mm, drift * 100.0)
                )
    if per_part:
        coverage = 0.0
    else:
        coverage = layups.schedule_gelcoat_per_m2(layup)
        gelcoat_kg = coverage * area_eff * uplift if gelcoat else 0.0
        if gelcoat and layup != "classic":
            tissue_m2 = area_eff * uplift
    pigment_kg = gelcoat_kg * (recipe["pigment_pct"] / 100.0)
    paint_kg = layups.PAINT_KG_M2 * area_eff * uplift if paint else 0.0
    if mekp_on_coat:
        mekp_kg = (resin_kg + gelcoat_kg) * (recipe["mekp_pct"] / 100.0)
    else:
        mekp_kg = resin_kg * (recipe["mekp_pct"] / 100.0)

    resin_rate = rates[RESIN_TYPES[resin_type][1]]
    if resin_type == "gp" and gelcoat and recipe["iso_share_pct"] > 0:
        iso_kg = resin_kg * recipe["iso_share_pct"] / 100.0
    else:
        iso_kg = 0.0
    gp_kg = resin_kg - iso_kg
    resin_bd = gp_kg * resin_rate + iso_kg * rates["resin_iso"]
    if layup == "classic":
        fiber_bd = fiber_kg * rates["fiber"]
        glass_lines = [{"label": "Fiberglass", "qty": fiber_kg, "unit": "kg",
                        "rate": rates["fiber"], "amount": fiber_bd}]
    else:
        glass_lines = []
        fiber_bd = 0.0
        for key, kg in glass_kg.items():
            amount = kg * rates[key]
            fiber_bd += amount
            glass_lines.append({"label": "Glass - " + layups.REINFORCEMENTS[key]["label"],
                                "qty": kg, "unit": "kg", "rate": rates[key],
                                "amount": amount})
    tissue_bd = tissue_m2 * rates["tissue"]
    mekp_bd = mekp_kg * rates["mekp"]
    gelcoat_bd = gelcoat_kg * rates["gelcoat"]
    pigment_bd = pigment_kg * rates["pigment"]
    paint_bd = paint_kg * rates["paint"]
    paste_bd = paste_kg * rates["paste"]
    plywood_bd = plywood_m2 * rates["plywood"]
    steel_bd = steel_kg * rates["steel"]
    foam_bd = core_m2["pufoam"] * rates["foam"]
    plycore_bd = core_m2["plywood"] * rates["plywood"]
    grp_basket_bd = (resin_bd + fiber_bd + tissue_bd + mekp_bd + gelcoat_bd
                     + pigment_bd + paint_bd + paste_bd + foam_bd
                     + plycore_bd)
    consumables_bd = (grp_basket_bd * recipe["consumables_pct"] / 100.0
                      + consumables_flat)
    bought_ins_bd = 0.0
    for item in bought_ins:
        if item["by_client"]:
            item["amount"] = 0.0
        else:
            item["amount"] = item["qty"] * item["rate"]
            bought_ins_bd += item["amount"]
    material_bd = (grp_basket_bd + plywood_bd + steel_bd + hardware_cost
                   + bought_ins_bd + consumables_bd)
    labour_ops = None
    if shape_id in ("cabin", "dome", "sphere") and per_part:
        elec_points = sum(int(item["qty"]) for item in bought_ins
                          if _is_wired(item.get("label")))
        ops = layups.estimate_cabin_labour(area_eff, len(openings),
                                           elec_points)
        ops_total = round(sum(hours for _, hours in ops), 1)
        if abs(recipe["labour_hours"] - ops_total) <= 0.05:
            labour_ops = []
            for label, hours in ops:
                if shape_id in ("dome", "sphere"):
                    label = label.replace("Gelcoat + lamination",
                                          "Lamination + paint")
                    label = label.replace("flowcoat, polishing",
                                          "painting, polishing")
                labour_ops.append({"label": label, "hours": hours})
    labour_bd = recipe["labour_hours"] * rates["labour"]
    machine_bd = recipe["machine_hours"] * rates["machine"]
    subtotal_pc_bd = material_bd + labour_bd + machine_bd
    batch_bd = subtotal_pc_bd * qty
    mould_pc_bd = mould_cost / mould_life_qty if mould_option == "need" else 0.0
    mould_bd = mould_pc_bd * qty
    ship_bd = (delivery_bd + testing_bd) * qty
    overhead_bd = (batch_bd + mould_bd + ship_bd) * recipe["overhead_pct"] / 100.0
    total_bd = batch_bd + overhead_bd + mould_bd + ship_bd
    markup_bd = total_bd * markup_pct / 100.0
    selling_bd = total_bd + markup_bd
    tax_bd = selling_bd * tax_pct / 100.0
    grand_total_bd = selling_bd + tax_bd

    lines = list(glass_lines)
    if tissue_m2 > 0:
        lines.append({"label": "Surface tissue", "qty": tissue_m2,
                      "unit": "m2", "rate": rates["tissue"],
                      "amount": tissue_bd})
    lines.append({"label": "Resin (%s)" % RESIN_TYPES[resin_type][0],
                  "qty": gp_kg, "unit": "kg", "rate": resin_rate,
                  "amount": gp_kg * resin_rate})
    if iso_kg > 0:
        lines.append({"label": "ISO resin (skin coat)", "qty": iso_kg,
                      "unit": "kg", "rate": rates["resin_iso"],
                      "amount": iso_kg * rates["resin_iso"]})
    if gelcoat:
        if per_part:
            coat_label = "Gelcoat + flowcoat (per part schedule)"
        else:
            coat_label = "Gelcoat (%.2f kg/m2)" % coverage
        lines.append({"label": coat_label, "qty": gelcoat_kg,
                      "unit": "kg", "rate": rates["gelcoat"], "amount": gelcoat_bd})
    if pigment_kg > 0:
        lines.append({"label": "Pigment paste", "qty": pigment_kg, "unit": "kg",
                      "rate": rates["pigment"], "amount": pigment_bd})
    lines.append({"label": "MEKP catalyst", "qty": mekp_kg, "unit": "kg",
                  "rate": rates["mekp"], "amount": mekp_bd})
    if paint:
        lines.append({"label": "Paint / topcoat", "qty": paint_kg, "unit": "kg",
                      "rate": rates["paint"], "amount": paint_bd})
    if core_m2["pufoam"] > 0:
        lines.append({"label": "PU foam core 20 mm", "qty": core_m2["pufoam"],
                      "unit": "m2", "rate": rates["foam"], "amount": foam_bd})
    if core_m2["plywood"] > 0:
        lines.append({"label": "Plywood floor core 18 mm", "qty": core_m2["plywood"],
                      "unit": "m2", "rate": rates["plywood"], "amount": plycore_bd})
    if paste_kg > 0:
        lines.append({"label": "Bonding paste / filler", "qty": paste_kg,
                      "unit": "kg", "rate": rates["paste"], "amount": paste_bd})
    if plywood_m2 > 0:
        lines.append({"label": "Plywood supports", "qty": plywood_m2, "unit": "m2",
                      "rate": rates["plywood"], "amount": plywood_bd})
    if steel_kg > 0:
        lines.append({"label": "Steel supports", "qty": steel_kg, "unit": "kg",
                      "rate": rates["steel"], "amount": steel_bd})
    if hardware_cost > 0:
        lines.append({"label": "Hardware / fittings", "qty": 1.0, "unit": "pc",
                      "rate": hardware_cost, "amount": hardware_cost})
    for item in bought_ins:
        label = "Bought-in: " + str(item["label"]).strip()
        if item["by_client"]:
            label += " (by client - not charged)"
        lines.append({"label": label, "qty": item["qty"], "unit": item["unit"],
                      "rate": item["rate"], "amount": item["amount"]})
    lines.append({"label": "Consumables (% of GRP materials)",
                  "qty": recipe["consumables_pct"], "unit": "%",
                  "rate": grp_basket_bd, "amount": consumables_bd})
    if labour_ops:
        for op in labour_ops:
            lines.append({
                "label": "Labour - " + op["label"],
                "qty": op["hours"],
                "unit": "hr",
                "rate": rates["labour"],
                "amount": op["hours"] * rates["labour"],
            })
    else:
        lines += [
            {
                "label": "Labour",
                "qty": recipe["labour_hours"],
                "unit": "hr",
                "rate": rates["labour"],
                "amount": labour_bd,
            },
        ]
    if recipe["machine_hours"] > 0:
        lines.append({"label": "Machine time", "qty": recipe["machine_hours"],
                      "unit": "hr", "rate": rates["machine"], "amount": machine_bd})

    if layup == "classic":
        laminate_note = (
            "Laminate density %.0f kg/m3; uniform %s mm laminate."
            % (recipe["density_kg_m3"], _fmt(thickness_mm))
        )
        mix_note = (
            "Resin/fibre %s/%s with %.1f%% wastage on both."
            % (_fmt(recipe["resin_pct"]), _fmt(recipe["fiber_pct"]), recipe["wastage_pct"])
        )
    else:
        laminate_note = (
            "Laminate schedule: %s, cured ~%.1f mm (gelcoat %s)."
            % (schedule["label"], schedule_mm, "yes" if gelcoat else "no")
        )
        mix_note = (
            "CSM wets out at 2.2-2.3:1, woven roving at 1.3:1 resin-to-glass; "
            "%.1f%% wastage on resin, glass and gelcoat." % recipe["wastage_pct"]
        )
    assumptions = list(spec["assumptions"]) + [
        laminate_note,
        mix_note,
        "Resin: %s." % RESIN_TYPES[resin_type][0],
        "MEKP %.2f%% of resin + gelcoat mass (after wastage)."
        % recipe["mekp_pct"],
        "Consumables %.1f%% of GRP materials (rollers, acetone, wax, "
        "release)." % recipe["consumables_pct"],
        "Overhead %.1f%% on direct cost (batch + amortised mould + "
        "delivery/testing); batch of %d." % (recipe["overhead_pct"], qty),
    ]
    if iso_kg > 0:
        assumptions.append(
            "ISO resin skin coat %.1f%% of resin (%s kg) behind the gelcoat."
            % (recipe["iso_share_pct"], _fmt(iso_kg)))
    if tissue_m2 > 0:
        assumptions.append("Surface tissue %s m2 behind the outside gelcoat."
                           % _fmt(tissue_m2))
    if paste_kg > 0:
        assumptions.append("Bonding paste / filler %s kg per piece (corner "
                           "joints, filling)." % _fmt(paste_kg))
    if mould_option == "need":
        assumptions.append(
            "New mould BD %.3f spread over %d pieces (BD %.3f/pc)."
            % (mould_cost, mould_life_qty, mould_pc_bd)
        )
    else:
        assumptions.append("Existing mould - no mould cost included.")
    if plywood_m2 > 0 or steel_kg > 0 or hardware_cost > 0:
        assumptions.append(
            "Supports per piece: %s m2 plywood, %s kg steel, BD %s hardware."
            % (_fmt(plywood_m2), _fmt(steel_kg), _fmt(hardware_cost))
        )
    if extra_area_m2 > 0:
        assumptions.append(
            "Extra stiffening / nozzles / flanges: %s m2 entered and costed "
            "with the same laminate schedule." % _fmt(extra_area_m2)
        )
    if paint:
        assumptions.append("Paint / topcoat at %.2f kg/m2 included." % layups.PAINT_KG_M2)
    if openings_m2 > 0 and n_wall_skins > 1:
        assumptions.append("Less door / window openings: %s m2 deducted from each "
                           "of the %d wall skins." % (_fmt(openings_m2), n_wall_skins))
    elif openings_m2 > 0:
        assumptions.append("Less door / window openings: %s m2 deducted from shell area."
                           % _fmt(openings_m2))
    if core_m2["pufoam"] > 0 or core_m2["plywood"] > 0:
        assumptions.append(
            "Sandwich cores per piece: %s m2 PU foam board, %s m2 plywood floor core."
            % (_fmt(core_m2["pufoam"]), _fmt(core_m2["plywood"])))
    if labour_ops:
        assumptions.append(
            "Labour %s hr/pc across %d assembly operations (prefilled estimate)."
            % (_fmt(recipe["labour_hours"]), len(labour_ops)))
    if bought_ins:
        client_n = sum(1 for item in bought_ins if item["by_client"])
        note = ("Bought-in items (%d) per piece: BD %.3f."
                % (len(bought_ins), bought_ins_bd))
        if client_n:
            note += " (%d by client - not charged)." % client_n
        assumptions.append(note)
    if delivery_bd > 0:
        assumptions.append("Delivery, packing and installation BD %.3f/pc included."
                           % delivery_bd)
    if testing_bd > 0:
        assumptions.append("Testing, inspection and certification BD %.3f/pc included."
                           % testing_bd)
    if markup_pct > 0:
        assumptions.append("Margin / markup %.2f%% included (selling price)." % markup_pct)
    if tax_pct > 0:
        assumptions.append("Taxes / duties %.2f%% on the selling price included."
                           % tax_pct)
    assumptions += [
        "Material rates are DEMO values unless replaced with verified factory rates.",
        "Material and cost estimate only - not a structural, pressure or certification rating.",
    ]
    exclusions = list(EXCLUSIONS)
    if mould_option == "need" and mould_cost > 0:
        exclusions = [e for e in exclusions if not e.startswith("Mould")]
    if delivery_bd > 0:
        exclusions = [e for e in exclusions if not e.startswith("Delivery")]
    if testing_bd > 0:
        exclusions = [e for e in exclusions if not e.startswith("Testing")]
    if paint:
        exclusions = [e for e in exclusions if not e.startswith("Surface extras")]
    if markup_pct > 0:
        exclusions = [e for e in exclusions if not e.startswith("Profit margin")]
    if tax_pct > 0:
        exclusions = [e for e in exclusions if not e.startswith("Taxes")]

    return {
        "shape_id": shape_id,
        "shape_label": spec["label"],
        "dims_mm": {k: float(v) for k, v in dims_mm.items()},
        "options": dict(options or {}),
        "qty": qty,
        "recipe": recipe,
        "rates": rates,
        "currency": CURRENCY,
        "layup": layup,
        "layup_label": schedule["label"],
        "gelcoat": gelcoat,
        "resin_type": resin_type,
        "resin_label": RESIN_TYPES[resin_type][0],
        "schedule_mm": schedule_mm,
        "area_m2": area_m2,
        "area_parts": area_parts,
        "extra_area_m2": extra_area_m2,
        "laminate_kg": laminate_kg,
        "fiber_kg": fiber_kg,
        "glass_kg": glass_kg,
        "resin_kg": resin_kg,
        "gp_kg": gp_kg,
        "iso_kg": iso_kg,
        "mekp_kg": mekp_kg,
        "gelcoat_kg": gelcoat_kg,
        "tissue_m2": tissue_m2,
        "pigment_kg": pigment_kg,
        "paint": paint,
        "paint_kg": paint_kg,
        "paste_kg": paste_kg,
        "lines": lines,
        "grp_basket_bd": grp_basket_bd,
        "consumables_bd": consumables_bd,
        "material_bd": material_bd,
        "labour_bd": labour_bd,
        "machine_bd": machine_bd,
        "hardware_bd": hardware_cost,
        "bought_ins": bought_ins,
        "bought_ins_bd": bought_ins_bd,
        "openings_m2": openings_m2,
        "openings": openings,
        "core_m2": core_m2,
        "labour_ops": labour_ops,
        "subtotal_pc_bd": subtotal_pc_bd,
        "batch_bd": batch_bd,
        "overhead_bd": overhead_bd,
        "mould_bd": mould_bd,
        "mould_pc_bd": mould_pc_bd,
        "mould_life_qty": mould_life_qty,
        "supports_bd": plywood_bd + steel_bd,
        "total_bd": total_bd,
        "per_piece_bd": total_bd / qty,
        "delivery_bd": delivery_bd,
        "testing_bd": testing_bd,
        "delivery_batch_bd": delivery_bd * qty,
        "testing_batch_bd": testing_bd * qty,
        "markup_pct": markup_pct,
        "markup_bd": markup_bd,
        "selling_bd": selling_bd,
        "tax_pct": tax_pct,
        "tax_bd": tax_bd,
        "grand_total_bd": grand_total_bd,
        "assumptions": assumptions,
        "exclusions": exclusions,
        "warnings": warnings,
    }