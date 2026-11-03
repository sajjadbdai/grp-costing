"""Bought-in schedule reader. Stdlib only.

Drawings and descriptions name the bought-in items (doors, windows, lights,
switches, DB, AC) in legends and notes. This module finds them with keyword
rules, reads nearby quantities and opening sizes, and prices them from the
default book. Everything it finds lands on the review page for the user to
confirm - nothing is silently assumed.
"""

from __future__ import annotations

import itertools
import re

#: Detection rules: label, unit, default rate (BD), kind, standard opening
#: size, and keyword variants - every word of ONE variant must appear close
#: together for the rule to fire. Kinds: door, window, ac, elec, other.
#: Doors and windows carry a per-m2 supply rate: the review price is that
#: rate times the opening area, so drawing sizes price themselves.
#: Default rates are internet-approximate Bahrain supply prices (Nov 2026:
#: eXtra/Labeb/SharafDG/noon/microless listings, China factory windows/doors
#: plus local fabrication) - confirm with supplier quotes on review.
RULES = [
    {"variants": [("sliding window",)], "label": "Aluminium sliding window",
     "unit": "no", "rate": 56.25, "per_m2": True, "kind": "window",
     "std": (0.8, 1.0)},
    {"variants": [("fixed window",)], "label": "Aluminium fixed window",
     "unit": "no", "rate": 43.75, "per_m2": True, "kind": "window",
     "std": (0.8, 1.0)},
    {"variants": [("split", "a/c"), ("split", "ac"),
                ("split", "air condition")],
     "label": "Split AC 1.5 ton (0 if client supplies)",
     "unit": "no", "rate": 185.0, "kind": "ac", "std": None},
    {"variants": [("down light",), ("downlight",), ("led",)],
     "label": "LED recessed down light",
     "unit": "no", "rate": 2.5, "kind": "elec", "std": None},
    {"variants": [("socket",)], "label": "13A 2-gang switched socket",
     "unit": "no", "rate": 4.5, "kind": "elec", "std": None},
    {"variants": [("distribution board",), ("db-single",)],
     "label": "Single-phase DB with MCBs/RCD", "unit": "no", "rate": 35.0,
     "kind": "elec", "std": None},
    {"variants": [("1 way switch",), ("1-way switch",)], "label": "1-way switch",
     "unit": "no", "rate": 2.5, "kind": "elec", "std": None},
    {"variants": [("45a",), ("double pole", "switch")],
     "label": "45A DP switch with neon (AC)",
     "unit": "no", "rate": 9.0, "kind": "elec", "std": None},
    {"variants": [("door",)], "label": "GRP door",
     "unit": "no", "rate": 81.0, "per_m2": True, "kind": "door",
     "std": (0.8, 1.85)},
    {"variants": [("lightning", "arrester")],
     "label": "Lightning arrester",
     "unit": "no", "rate": 6.0, "kind": "other", "std": None},
]

#: Estimator allowances appended after the detected items. Each fires only
#: when the drawing shows the related work; all are editable on review.
#: The wiring allowance prices per electrical point detected.
ALLOWANCES = [
    {"label": "Cables, conduits, boxes (per electrical point)",
     "unit": "point", "rate": 4.167, "needs": ("elec", "ac"),
     "per_point": True},
    {"label": "AC installation (copper pipe, bracket, drain)", "unit": "lot",
     "rate": 25.0, "needs": ("ac",)},
    {"label": "Silicone sealant, fixings, anchor bolts", "unit": "lot",
     "rate": 15.0, "needs": ("door", "window")},
]

#: Item quantity: a bare number after QTY - not a rating like "13A" and
#: not the title-block job quantity ("QTY 2 NOS").
_QTY_RE = re.compile(r"qty\s*:?\s*(\d{1,3})(?![0-9A-Za-z])(?!\s*nos\b)",
                     re.IGNORECASE)
_DIM_RE = re.compile(r"(\d{3,4})\s*[xX\xd7]\s*(\d{3,4})")
_JOB_QTY_RE = re.compile(r"qty\s*:?\s*(\d{1,3})\s*nos\b", re.IGNORECASE)


def _box_dims_re(prefix):
    return re.compile(
        prefix + r"\s*:?\s*-?\s*l\.?\s*(\d{3,4})\s*(?:mm)?\s*[xX\xd7]\s*w\.?\s*"
        r"(\d{3,4})\s*(?:mm)?\s*[xX\xd7]\s*h\.?\s*(\d{3,4})",
        re.IGNORECASE)


_OVERALL_RE = _box_dims_re(r"overall\s*size")
_INTERNAL_RE = _box_dims_re(r"internal\s*size")
_DIA_QUALIFIED_RE = re.compile(
    r"(internal|external)\s+dia(?:\.|meter)?\s*(\d{2,5}(?:\.\d+)?)\s*mm",
    re.IGNORECASE)
_DIA_BARE_RE = re.compile(
    r"(?:dia(?:\.|meter)?)\s*(\d{2,5}(?:\.\d+)?)\s*mm", re.IGNORECASE)
_DIA_METERS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*m\s+dia\.?", re.IGNORECASE)
_PANEL_MM_RE = re.compile(
    r"(internal|external)\s+(\d+(?:\.\d+)?)\s*mm\s*thick", re.IGNORECASE)
_SPHERE_MM_RE = re.compile(r"\(\s*thick\s*(\d+(?:\.\d+)?)\s*mm\s*\)",
                           re.IGNORECASE)
_INSULATION_RE = re.compile(
    r"(\d+)\s*mm\s*thick\s+((?:glass\s*wool|pu(?:\s*foam)?))", re.IGNORECASE)
_PIPE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*mm\s*dia\.?\s*x\s*(\d+(?:\.\d+)?)\s*mm\s*thick\s*"
    r"(gi|ms|ss|stainless)?\s*pipe", re.IGNORECASE)
_PIPE_DIA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mm\s*dia\.?\s*(?:g\.?i\.?|gi)?\s*"
                          r"pipe", re.IGNORECASE)
_PLATE_RE = re.compile(
    r"(\d+)\s*x\s*(\d+)(?:\s*x\s*(\d+))?\s*mm"
    r"(?:\s+(?:thk?\.?|thick|painted|ms|galvanized|ss|316|base|anchor)){0,6}?"
    r"\s+(base\s+plate|plate)",
    re.IGNORECASE)
_PLATE_PAREN_RE = re.compile(
    r"(base\s+plate|plate)\s*(?:\([^()]*\)\s*)?"
    r"\(\s*(\d+)\s*x\s*(\d+)(?:\s*x\s*(\d+))?\s*mm?\s*\)",
    re.IGNORECASE)
_PLATE_DIA_RE = re.compile(r"plate\s*\(\s*(\d+)\s*mm\s*dia", re.IGNORECASE)
_COUNT_RE = re.compile(r"-\s*(\d+)\s*(?:nos?\.?)?", re.IGNORECASE)
_BOLT_RE = re.compile(r"\b(M\s?\d+)\b[^.\n]{0,50}?(bolt)", re.IGNORECASE)
_BOLT_REV_RE = re.compile(r"bolt\s*\(\s*(M\s?\d+)", re.IGNORECASE)
_CHANNEL_RE = re.compile(r"(\d+)\s*x\s*(\d+)\s*x\s*(\d+)\s*mm[^\n]{0,40}?"
                         r"c-channel", re.IGNORECASE)
_RAL_RE = re.compile(r"RAL\s*\.?\s*(\d{3,4}\s*[A-Z0-9]*)", re.IGNORECASE)
_COLOR_RE = re.compile(r"\b(beige|white|grey|gray|green|blue|red|yellow|black|"
                       r"ivory|cream)\b", re.IGNORECASE)
_FINISH_RE = re.compile(r"\b(smooth|rough)\s+finish\b", re.IGNORECASE)
_SUPPORT_RE = re.compile(r"\b(steel|stainless|galvanized|gi(?:\s+pipe)?|shs|rhs|"
                         r"angle|channel|beam|supports?|stiffeners?|plywood|"
                         r"timber|frames?|brackets?)\b", re.IGNORECASE)
_WINDOW = 200  # chars searched around a keyword hit

#: Door material words: aluminium or steel named next to the door mention
#: names the door; anything else (or nothing) means a GRP door from our
#: own shop - never assume a bought-in metal door.
_DOOR_ALU_RE = re.compile(r"\b(aluminium|aluminum)\b", re.IGNORECASE)
_DOOR_STEEL_RE = re.compile(r"\b(stainless(?:\s+steel)?|steel|ss)\b",
                            re.IGNORECASE)
_DOOR_WINDOW = 60  # chars around the door mention searched for a material


def _door_label(text, hit):
    """Schedule label for a door hit from nearby material words."""
    window = text[max(0, hit - _DOOR_WINDOW):hit + _DOOR_WINDOW]
    if _DOOR_ALU_RE.search(window):
        return "Aluminium door (glass top, lock)"
    if _DOOR_STEEL_RE.search(window):
        return "Steel door"
    return "GRP door"


def _hits(text, rule):
    """Start offsets where every word of one variant appears near each other."""
    for variant in rule["variants"]:
        occurrences = []
        for key in variant:
            found = [m.start() for m in
                     re.finditer(r"\b%s\b" % re.escape(key), text, re.IGNORECASE)]
            if not found:
                break
            occurrences.append(found)
        else:
            for combo in itertools.product(*occurrences):
                if max(combo) - min(combo) <= _WINDOW:
                    return [min(combo)]
    return []


def parse_job_qty(text):
    """Job quantity from a title-block line like 'QTY : 2 NOS'."""
    match = _JOB_QTY_RE.search(text or "")
    if not match:
        return None
    try:
        qty = int(match.group(1))
    except ValueError:
        return None
    return qty if qty >= 1 else None


def _box_dims_match(regex, text):
    match = regex.search(text or "")
    if not match:
        return None
    try:
        dims = {key: int(match.group(i)) for i, key in
                ((1, "length"), (2, "width"), (3, "height"))}
    except ValueError:
        return None
    if any(v <= 0 for v in dims.values()):
        return None
    return dims


def parse_overall_dims(text):
    """Overall LxWxH millimetres from an 'Overall Size' title-block line."""
    return _box_dims_match(_OVERALL_RE, text)


def parse_internal_dims(text):
    """Internal LxWxH millimetres from an 'Internal Size' title-block line."""
    return _box_dims_match(_INTERNAL_RE, text)


def parse_finishes(text):
    """Colors and finishes named in the text (RAL codes first)."""
    found = []
    for match in _RAL_RE.finditer(text or ""):
        code = "RAL " + " ".join(match.group(1).split()).upper()
        if code not in found:
            found.append(code)
    for match in _COLOR_RE.finditer(text or ""):
        color = match.group(1).lower()
        if color not in found:
            found.append(color)
    for match in _FINISH_RE.finditer(text or ""):
        finish = match.group(0).lower()
        if finish not in found:
            found.append(finish)
    return found[:8]


def parse_support_mentions(text):
    """Structural/support keywords named in the text (display only)."""
    found = []
    for match in _SUPPORT_RE.finditer(text or ""):
        word = " ".join(match.group(1).split()).lower()
        if word not in found:
            found.append(word)
    # Drop overlaps ("gi" inside "gi pipe") for a clean display list.
    return [w for w in found
            if not any(w != o and w in o for o in found)][:8]


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_diameters(text):
    """Diameters stated in the text (domes, spheres, round tanks)."""
    text = text or ""
    found, qualified = [], []
    for match in _DIA_QUALIFIED_RE.finditer(text):
        mm = _num(match.group(2))
        if mm:
            found.append("%s dia %g mm" % (match.group(1).lower(), mm))
            qualified.append((match.start(), match.end()))
    for match in _DIA_METERS_RE.finditer(text):
        meters = _num(match.group(1))
        if meters:
            found.append("dia %g mm" % (meters * 1000))
    for match in _DIA_BARE_RE.finditer(text):
        if any(start - 12 <= match.start() <= end for start, end in qualified):
            continue
        mm = _num(match.group(1))
        if mm:
            found.append("dia %g mm" % mm)
    return list(dict.fromkeys(found))[:6]


def _join_counts(counts):
    """'8+4 nos' style aggregation with unstated counts kept visible."""
    known = [c for c in counts if c != "?"]
    extra = len(counts) - len(known)
    if not known:
        return "count not stated"
    text = "+".join(known) + " nos"
    if extra:
        text += " (+%d unstated)" % extra
    return text


def parse_panel_mm(text):
    """GRP laminate thicknesses stated per skin (domes, sandwich walls)."""
    found = []
    for match in _PANEL_MM_RE.finditer(text or ""):
        mm = _num(match.group(2))
        if mm:
            found.append("%s %g mm" % (match.group(1).lower(), mm))
    for match in _SPHERE_MM_RE.finditer(text or ""):
        mm = _num(match.group(1))
        if mm:
            found.append("sphere %g mm" % mm)
    return list(dict.fromkeys(found))[:6]


def parse_insulation(text):
    """Insulation thicknesses stated in the text (display only)."""
    found = []
    for match in _INSULATION_RE.finditer(text or ""):
        kind = match.group(2).lower()
        kind = "PU foam" if kind.startswith("pu") else "glass wool"
        found.append("%s mm %s" % (match.group(1), kind))
    return list(dict.fromkeys(found))[:4]


def _steel_counts(flat, end):
    """Component count ('- 4 nos') just after a steel match, if stated."""
    match = _COUNT_RE.search(flat[end:end + 60])
    return match.group(1) if match else None


def parse_steel_parts(text):
    """Steel support parts with counts (display only - weigh to cost)."""
    flat = re.sub(r"\s+", " ", text or "")
    pipes, seen_pipe = {}, set()
    for match in _PIPE_RE.finditer(flat):
        key = (match.group(1), match.group(2),
               (match.group(3) or "GI").upper())
        count = _steel_counts(flat, match.end())
        pipes.setdefault(key, []).append(count or "?")
    for match in _PIPE_DIA_RE.finditer(flat):
        key = (match.group(1), None, "GI")
        if key not in seen_pipe and key not in pipes:
            count = _steel_counts(flat, match.end())
            pipes[key] = [count or "?"]
        seen_pipe.add(key)
    parts = []
    for (dia, thick, grade), counts in pipes.items():
        spec = "%s pipe %s dia" % (grade, dia)
        if thick:
            spec += " x %s thk" % thick
        parts.append("%s (%s)" % (spec, _join_counts(counts)))
    plates = {}
    for match in _PLATE_RE.finditer(flat):
        dims = "x".join(g for g in match.groups()[:3] if g)
        key = (" ".join(match.group(4).lower().split()), dims)
        plates.setdefault(key, []).append(
            _steel_counts(flat, match.end()) or "?")
    for match in _PLATE_PAREN_RE.finditer(flat):
        dims = "x".join(g for g in match.groups()[1:] if g)
        key = (" ".join(match.group(1).lower().split()), dims)
        plates.setdefault(key, []).append(
            _steel_counts(flat, match.end()) or "?")
    for (kind, dims), counts in plates.items():
        parts.append("%s %s (%s)" % (kind, dims, _join_counts(counts)))
    match = _PLATE_DIA_RE.search(flat)
    if match:
        parts.append("plate dia %s" % match.group(1))
    match = _CHANNEL_RE.search(flat)
    if match:
        parts.append("C-channel %sx%sx%s ring"
                     % (match.group(1), match.group(2), match.group(3)))
    bolts = []
    for match in _BOLT_RE.finditer(flat):
        size = re.sub(r"\s+", "", match.group(1).upper())
        count = _steel_counts(flat, match.end())
        spacing = re.search(r"@\s*(\d+)\s*mm\s*c/c",
                            flat[match.end():match.end() + 30],
                            re.IGNORECASE)
        label = "%s bolt" % size
        if spacing:
            label += "s @%s c/c" % spacing.group(1)
        elif count:
            label += "s %s nos" % count
        if label not in bolts:
            bolts.append(label)
    for match in _BOLT_REV_RE.finditer(flat):
        size = re.sub(r"\s+", "", match.group(1).upper())
        label = "%s eye bolt" % size
        if label not in bolts:
            bolts.append(label)
    parts.extend(bolts)
    return parts[:14]


def parse_schedule(text):
    """Detect bought-in items in drawing/description text.

    Returns {"items": [{label, qty, unit, rate, basis, kind, source}],
    "openings": [...], "openings_m2": float, "fitted": bool,
    "job_qty": int|None, "overall": {length, width, height}|None,
    "internal": ...|None, "finishes": [...], "supports": [...],
    "diameters": [...], "dome": {...}|None, "panels": [...],
    "insulation": [...], "steel": [...]}. Each rule fires once; quantities
    and opening sizes come from nearby text or fall back to 1 pc /
    standard sizes. Doors and windows price per m2 of opening; the wiring
    allowance prices per electrical point. Allowances follow the items.
    """
    text = text or ""
    items, openings = [], []
    seen, kinds = set(), set()
    for rule in RULES:
        hits = _hits(text, rule)
        if not hits:
            continue
        label = rule["label"]
        if rule["kind"] == "door":
            label = _door_label(text, hits[0])
        if label in seen:
            continue
        seen.add(label)
        kinds.add(rule["kind"])
        near = text[hits[0]:hits[0] + _WINDOW]
        qty = 1
        match = _QTY_RE.search(near)
        if match:
            try:
                qty = max(1, int(match.group(1)))
            except ValueError:
                qty = 1
        width = height = 0.0
        if rule["kind"] in ("door", "window") and rule["std"]:
            width, height, source = rule["std"][0], rule["std"][1], "standard"
            dims = _DIM_RE.search(near)
            if dims:
                try:
                    width = int(dims.group(1)) / 1000.0
                    height = int(dims.group(2)) / 1000.0
                    source = "drawing"
                except ValueError:
                    pass
            openings.append({"label": label, "width_m": width,
                             "height_m": height, "qty": qty, "source": source})
        if rule.get("per_m2"):
            area = round(width * height, 4)
            rate = round(rule["rate"] * area, 3)
            basis = ("%.2f BD/m2 x %.2f m2 (%s)"
                     % (rule["rate"], area, source))
        else:
            rate, basis = rule["rate"], "Price list"
        items.append({"label": label, "qty": qty, "unit": rule["unit"],
                      "rate": rate, "basis": basis, "kind": rule["kind"],
                      "source": "drawing"})
    points = sum(i["qty"] for i in items if i["kind"] in ("elec", "ac"))
    for lot in ALLOWANCES:
        if kinds.intersection(lot["needs"]):
            qty = max(1, points) if lot.get("per_point") else 1
            items.append({"label": lot["label"], "qty": qty, "unit": lot["unit"],
                          "rate": lot["rate"], "basis": "Allowance",
                          "kind": "other", "source": "allowance"})
    openings_m2 = round(sum(o["width_m"] * o["height_m"] * o["qty"]
                            for o in openings), 4)
    return {"items": items, "openings": openings, "openings_m2": openings_m2,
            "fitted": bool({"door", "window"} <= kinds),
            "has_elec": bool({"elec", "ac"} & kinds),
            "elec_points": points,
            "job_qty": parse_job_qty(text), "overall": parse_overall_dims(text),
            "internal": parse_internal_dims(text),
            "finishes": parse_finishes(text),
            "supports": parse_support_mentions(text),
            "diameters": parse_diameters(text),
            "dome": parse_dome_guess(text),
            "panels": parse_panel_mm(text),
            "insulation": parse_insulation(text),
            "steel": parse_steel_parts(text)}


#: Bare dimension numbers (no unit nearby) in shop drawings.
_BARE_DIM_RE = re.compile(r"(?<!\d)(\d{3,4})(?!\d)")


def parse_dome_guess(text):
    """Best-guess dome dimensions from shop-drawing text.

    Returns {"inner_dia", "outer_dia", "rise", "ring", "base_dia",
    "skin_outer", "skin_inner"} in mm (None when not found). The internal
    diameter and skin thicknesses come from qualified lines
    ("INTERNAL DIA. 4000 MM"); the outer/base diameters, rise and ring
    height come from bare numbers in text order, so the review page shows
    them as unconfirmed guesses to check against the drawing.
    """
    text = text or ""
    inner = None
    for match in _DIA_QUALIFIED_RE.finditer(text):
        if match.group(1).lower() == "internal":
            inner = _num(match.group(2))
            if inner:
                break
    if not inner:
        return None
    seen_spans = [m.span() for m in _DIA_QUALIFIED_RE.finditer(text)]
    seen_spans += [m.span() for m in _DIA_METERS_RE.finditer(text)]
    bare = []
    for match in _BARE_DIM_RE.finditer(text):
        if any(start <= match.start() and match.end() <= end
               for start, end in seen_spans):
            continue
        before = text[max(0, match.start() - 5):match.start()].upper()
        after = text[match.end():match.end() + 10].upper()
        if "RAL" in before:
            continue  # color code, not a dimension
        if re.match(r"\s*MM\s*(THICK|THK\.?|LONG|C/C)", after):
            continue  # plate/bolt/insulation size, not the dome
        bare.append(int(match.group(1)))
    outer = rise = ring = base = None
    for number in bare:
        if outer is None and inner < number <= inner + 500:
            outer = number
        elif rise is None and 500 <= number < inner:
            rise = number
        elif ring is None and 100 <= number < 500:
            ring = number
    in_band = [n for n in bare if inner < n <= inner + 500]
    if in_band:
        base = max(in_band)
    skin_outer = skin_inner = None
    for match in _PANEL_MM_RE.finditer(text):
        mm = _num(match.group(2))
        if not mm:
            continue
        if match.group(1).lower() == "external" and skin_outer is None:
            skin_outer = mm
        elif match.group(1).lower() == "internal" and skin_inner is None:
            skin_inner = mm
    if outer is None and rise is None:
        return None
    return {"inner_dia": inner, "outer_dia": outer, "rise": rise,
            "ring": ring, "base_dia": base, "skin_outer": skin_outer,
            "skin_inner": skin_inner}
