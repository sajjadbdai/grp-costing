"""GFPF drawing-to-estimate web app.

Upload/Describe -> Review -> Calculate -> Compare/Save.
Legacy POST /estimate behaviour is preserved; all geometry and money go
through the deterministic engine; Muse only interprets and narrates.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import costing, layup as layups, materials, muse_client, pdf_report, schedule, shapes, store, units, xlsx_report

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
UPLOAD_DIR = ROOT / "uploads"
DEMO_DIR = BASE / "demo"

app = FastAPI(title="Drawing to Estimate - GFPF Fiberglass Costing")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))


def _render(name, context):
    """Request-first TemplateResponse call for modern Starlette."""
    context = dict(context)
    request = context.pop("request")
    call = templates.TemplateResponse
    return call(request, name, context)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SAFE_NAME_RE = re.compile(r"^[0-9a-f]{12,32}(?:_p1)?\.(jpg|jpeg|png|pdf)$")


class UploadError(ValueError):
    """Rejected or unreadable upload."""


def _sniff(data):
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg", "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png", "image/png"
    if data[:4] == b"%PDF":
        return ".pdf", "application/pdf"
    return None, None


def _pdf_available():
    try:
        import pymupdf  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import fitz  # noqa: F401
        return True
    except ImportError:
        return False


def _pdf_first_page_png(data):
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            raise UploadError("PDF drawings need the optional 'pymupdf' package on the server.")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise UploadError("Could not read that PDF (%s)." % exc)
    if doc.page_count < 1:
        raise UploadError("That PDF has no pages.")
    try:
        pixmap = doc.load_page(0).get_pixmap(dpi=150)
        return pixmap.tobytes("png"), doc.page_count
    except Exception as exc:
        raise UploadError("Could not render that PDF (%s)." % exc)


def _pdf_all_text(data):
    """Extractable text of every PDF page (empty string when none)."""
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            return ""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return ""
    try:
        return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


def _store_bytes(data, ext):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + ext
    (UPLOAD_DIR / name).write_bytes(data)
    return name


def _prepare_drawing(filename, data):
    """Validate an upload; returns dict with display + model payloads."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError("File is larger than 10 MB; please upload a smaller file.")
    ext, mime = _sniff(data)
    if ext is None:
        raise UploadError("Only JPG, PNG or PDF drawings are accepted (%s)." % (filename or "file"))
    if ext == ".pdf":
        original = _store_bytes(data, ".pdf")
        png_bytes, pages = _pdf_first_page_png(data)
        render = uuid.uuid4().hex + "_p1.png"
        (UPLOAD_DIR / render).write_bytes(png_bytes)
        note = "PDF page 1 of %d rendered for review." % pages
        return {"display": render, "original": original, "model_bytes": png_bytes,
                "model_mime": "image/png", "note": note}
    stored = _store_bytes(data, ext)
    return {"display": stored, "original": stored, "model_bytes": data,
            "model_mime": mime, "note": ""}

#: Most likely laminate schedule per shape; the user can change it on review.
DEFAULT_LAYUP = {
    "panel": "classic",
    "cylinder": "tank_medium",
    "reducer": "classic",
    "box": "enclosure",
    "custom": "boat_hull",
    "cabin": "cabin_outer",
    "dome": "dome_outer",
    "sphere": "dome_outer",
}

#: Cabin commercial defaults, prefilled on a fresh fitted-cabin review and
#: editable like every other value (labour rate/hours, overhead, pigment for
#: the beige gelcoat, margin, tax, transport, new mould and bonding paste).
CABIN_DEFAULTS = {
    "labour_rate": 1.6,
    "overhead_pct": 15.0,
    "pigment_pct": 8.0,
    "markup_pct": 20.0,
    "tax_pct": 10.0,
    "delivery_bd": 45.0,
    "mould_cost": 600.0,
    "hardware_cost": 12.0,
    "skin_mm": 4.0,
}

CABIN_NOTE = (
    "Cabin mode: sandwich take-off (outer + inner skins, cores, trims), "
    "%(labour).1f hr/pc across %(ops)d assembly operations, and cabin "
    "commercial defaults (overhead %(oh).0f%%, margin %(margin).0f%%, VAT "
    "%(vat).0f%%, transport BD %(trans).0f, new mould BD %(mould).0f, bonding "
    "paste BD %(bond).0f) - change any value before calculating.")

#: Dome commercial defaults, prefilled on a fresh dome/sphere review from
#: a dome drawing and editable like every other value.
DOME_DEFAULTS = {
    "labour_rate": 1.6,
    "overhead_pct": 15.0,
    "pigment_pct": 8.0,
    "markup_pct": 20.0,
    "tax_pct": 10.0,
    "delivery_bd": 45.0,
    "mould_cost": 600.0,
    "paste_kg": 8.0,
}

DOME_NOTE = (
    "Dome mode: sandwich take-off (outer + inner caps, ring beam, site "
    "joint strips, PU core, paint both faces), %(labour).1f hr/pc across "
    "%(ops)d assembly operations, and dome commercial defaults (overhead "
    "%(oh).0f%%, margin %(margin).0f%%, VAT %(vat).0f%%, transport BD "
    "%(trans).0f, new mould BD %(mould).0f, bonding paste %(paste).0f kg) - "
    "check the diameters and joint count against the drawing, then change "
    "any value before calculating.")

#: Descriptions that name a fitted product; without a drawing attached the
#: schedule reader never runs, so the review says so instead of staying quiet.
FITTED_WORDS_RE = re.compile(r"cabin|enclosure|kiosk|door|window",
                             re.IGNORECASE)


def _current_rates():
    """Factory default rates, honouring saved material price updates."""
    try:
        return materials.get_rates()
    except materials.MaterialsError:
        return dict(costing.DEFAULT_RATES)


def _blank_extraction(shape_id, qty=1):
    spec = shapes.get_shape(shape_id)
    return {
        "shape": shape_id,
        "shape_evidence": "",
        "quantity": qty,
        "dims": [],
        "options": {},
        "missing": [f["label"] for f in spec["fields"] if f["required"]],
        "ambiguities": [],
        "questions": [],
        "notes": [],
    }


def _review_rows(shape_id, extraction, raw=None):
    """Build editable review rows; raw overrides (value, unit) per field."""
    spec = shapes.get_shape(shape_id)
    by_field = {d["field"]: d for d in extraction.get("dims", [])}
    raw = raw or {}
    rows = []
    for field in spec["fields"]:
        key = field["key"]
        kind = field.get("kind", "length")
        entry = by_field.get(key, {})
        value = entry.get("value")
        unit = entry.get("unit") or ("m2" if kind == "area" else "mm")
        source = entry.get("source") or "user"
        quote = entry.get("quote") or ""
        if key in raw:
            value = raw[key][0]
            unit = raw[key][1] or unit
            source = "user"
        if kind == "area":
            unit = "m2"
        elif kind == "count":
            unit = "nos"
        text = "" if value is None else str(value)
        missing = field["required"] and (text.strip() == "")
        mm = None
        if kind not in ("area", "count") and text.strip():
            try:
                mm = units.parse_measurement(text, unit)["mm"]
            except units.UnitError:
                mm = None
        rows.append({"key": key, "label": field["label"], "required": field["required"],
                     "kind": kind, "value": text, "unit": unit, "source": source,
                     "quote": quote, "missing": missing, "mm": mm})
    options = []
    for option in spec["options"]:
        key = option["key"]
        value = extraction.get("options", {}).get(key, option["default"])
        if key in raw:
            value = raw[key][0] == "yes"
        options.append({"key": key, "label": option["label"], "value": bool(value)})
    return rows, options


def _review_labour_estimate(shape_id, rows, options, layup, gelcoat_sel,
                            openings_m2=0.0, n_openings=0, has_elec=False,
                            elec_points=0, openings_detail=None,
                            cabin_trims=None):
    """Labour estimate from review rows: (hours, ops|None).

    Returns None when dims are incomplete. Cabins, domes and spheres
    estimate per assembly operation from the net laminate area; other
    shapes use the single area-and-ply estimate.
    """
    try:
        spec = shapes.get_shape(shape_id)
    except shapes.ShapeError:
        return None
    by_key = {f["key"]: f for f in spec["fields"]}
    dims = {}
    for row in rows:
        field = by_key.get(row["key"], {})
        required = field.get("required", False) and row["key"] != "thickness"
        if row["kind"] == "area":
            try:
                dims[row["key"]] = float(row["value"])
            except (TypeError, ValueError):
                if required:
                    return None
        elif row["kind"] == "count":
            try:
                dims[row["key"]] = float(row["value"]) if row["value"].strip() else 0.0
            except (TypeError, ValueError, AttributeError):
                if required:
                    return None
                dims[row["key"]] = 0.0
        elif row["mm"] is None:
            if required:
                return None
            else:
                dims[row["key"]] = 0.0
        else:
            dims[row["key"]] = row["mm"]
    opts = {o["key"]: o.get("default", False) for o in spec["options"]}
    for row_opt in options:
        opts[row_opt["key"]] = row_opt["value"]
    try:
        n_open = max(0, int(n_openings))
    except (TypeError, ValueError):
        n_open = 0
    if shape_id == "cabin":
        opts["openings_count"] = n_open
        opts["openings"] = openings_detail or []
        for key, default in (("plinth_mm", 200.0), ("overhang_mm", 100.0),
                             ("cornice_mm", 350.0)):
            try:
                opts[key] = float((cabin_trims or {}).get(key, default)
                                  or default)
            except (TypeError, ValueError):
                opts[key] = default
        opts["sandwich"] = (cabin_trims or {}).get("sandwich", True)
        if isinstance(opts["sandwich"], str):
            opts["sandwich"] = opts["sandwich"] not in ("no", "false", "0", "")
    try:
        result = shapes.compute_area(shape_id, dims, opts)
    except (KeyError, shapes.ShapeError):
        return None
    gelcoat_bool = {"yes": True, "no": False}.get(gelcoat_sel)
    if shape_id in ("cabin", "dome", "sphere") and layup != "classic":
        skins = len([p for p in result["parts"] if p.get("wall")]) or 1
        try:
            gross = result["area_m2"] - float(openings_m2) * skins
        except (TypeError, ValueError):
            gross = result["area_m2"]
        try:
            points = max(0, int(elec_points))
        except (TypeError, ValueError):
            points = 0
        if has_elec and not points:
            points = 1
        ops = layups.estimate_cabin_labour(max(0.0, gross), n_open, points)
        total = round(sum(hours for _, hours in ops), 1)
        return total, len(ops)
    try:
        return layups.estimate_labour_hours(result["area_m2"], layup,
                                            gelcoat_bool), None
    except layups.LayupError:
        return None


def _review_context(request, shape_id, extraction, description="", drawing=None,
                    demo_ref=None, ai_error=None, ai_notice=None, form_errors=None,
                    raw=None, recipe=None, rates=None, qty=None, layup=None,
                    gelcoat="auto", mould_option="have", mould_cost=0.0,
                    plywood_m2=0.0, steel_kg=0.0, resin_type="gp",
                    mould_life_qty=None, hardware_cost=0.0, paint=False,
                    extra_area_m2=0.0, delivery_bd=0.0, testing_bd=0.0,
                    markup_pct=0.0, tax_pct=0.0, bought_ins="auto",
                    openings_m2="auto", openings_detail="auto",
                    cabin_defaults=False, dome_defaults=False, scan=None,
                    bought_blanks=2, open_blanks=1, paste_kg=0.0,
                    plinth_mm=200.0, overhang_mm=100.0, cornice_mm=350.0,
                    sandwich=True, drawing_no="", project="",
                    door_blanks=1):
    rows, options = _review_rows(shape_id, extraction, raw)
    layup = layup or DEFAULT_LAYUP.get(shape_id, "classic")
    if layup not in layups.SCHEDULE_IDS:
        layup = "classic"
    gelcoat_sel = "auto"
    if gelcoat is True or gelcoat == "yes":
        gelcoat_sel = "yes"
    elif gelcoat is False or gelcoat == "no":
        gelcoat_sel = "no"
    gelcoat_bool = {"yes": True, "no": False}.get(gelcoat_sel)
    try:
        layup_mm = layups.schedule_thickness(layup, gelcoat_bool)
    except layups.LayupError:
        layup_mm = None
    if bought_ins == "auto" or openings_m2 == "auto" or openings_detail == "auto":
        found_items, found_openings, info = _detect_schedule(description, drawing)
        if bought_ins == "auto":
            bought_ins = found_items
        if openings_m2 == "auto":
            openings_m2 = found_openings
        if openings_detail == "auto":
            openings_detail = info["openings"]
    else:
        info = {"has_elec": False}
    if bought_ins:
        detected = sum(1 for b in bought_ins
                       if (b.get("source") or "drawing") == "drawing")
        bought_note = ("Detected %d item%s from the drawing/description - "
                       "review qty and price below."
                       % (detected or len(bought_ins),
                          "s" if (detected or len(bought_ins)) != 1 else ""))
    else:
        bought_note = ("No bought-in items detected - add rows below as needed, "
                       "or leave empty.")
    def _wired(label):
        text = str(label or "").lower()
        return ("arrester" not in text
                and any(word in text for word in
                        ("light", "socket", "switch", " db", "distribution",
                         "split", "a/c", "air cond")))
    has_elec = info.get("has_elec", False) or any(
        _wired(b.get("label")) for b in bought_ins or [])
    elec_points = info.get("elec_points", 0) or 0
    if not elec_points and has_elec:
        elec_points = sum(1 for b in bought_ins or []
                          if _wired(b.get("label")))
    cabin_trims = {"plinth_mm": plinth_mm, "overhang_mm": overhang_mm,
                   "cornice_mm": cornice_mm, "sandwich": sandwich}
    recipe_out = recipe or dict(costing.DEFAULT_RECIPE)
    labour_note = None
    if recipe is None:
        estimate = _review_labour_estimate(
            shape_id, rows, options, layup, gelcoat_sel,
            openings_m2=openings_m2 or 0.0,
            n_openings=len(openings_detail or []), has_elec=has_elec,
            elec_points=elec_points, openings_detail=openings_detail,
            cabin_trims=cabin_trims)
        if estimate is None:
            labour_note = ("Labour hours need your input - dims are incomplete "
                           "for an estimate.")
        else:
            hours, ops = estimate
            recipe_out["labour_hours"] = hours
            if ops:
                labour_note = ("Labour pre-filled at %.1f hr/pc across %d assembly "
                               "operations - change it if your shop differs."
                               % (hours, ops))
            else:
                labour_note = ("Labour pre-filled at %.1f hr/pc from area and ply "
                               "count - change it if your shop differs." % hours)
    fresh_cabin = bool(cabin_defaults) and recipe is None and rates is None
    fresh_dome = bool(dome_defaults) and recipe is None and rates is None
    if fresh_cabin:
        recipe_out["overhead_pct"] = CABIN_DEFAULTS["overhead_pct"]
        recipe_out["pigment_pct"] = CABIN_DEFAULTS["pigment_pct"]
    if fresh_dome:
        recipe_out["overhead_pct"] = DOME_DEFAULTS["overhead_pct"]
        recipe_out["pigment_pct"] = DOME_DEFAULTS["pigment_pct"]
    rates_out = dict(rates) if rates else _current_rates()
    if fresh_cabin:
        rates_out["labour"] = CABIN_DEFAULTS["labour_rate"]
    if fresh_dome:
        rates_out["labour"] = DOME_DEFAULTS["labour_rate"]
    if fresh_cabin:
        cabin_note = CABIN_NOTE % {
            "labour": recipe_out["labour_hours"],
            "ops": len(layups.estimate_cabin_labour(1.0, 0, 1 if has_elec else 0)),
            "oh": CABIN_DEFAULTS["overhead_pct"],
            "margin": CABIN_DEFAULTS["markup_pct"],
            "vat": CABIN_DEFAULTS["tax_pct"],
            "trans": CABIN_DEFAULTS["delivery_bd"],
            "mould": CABIN_DEFAULTS["mould_cost"],
            "bond": CABIN_DEFAULTS["hardware_cost"]}
    elif fresh_dome:
        cabin_note = DOME_NOTE % {
            "labour": recipe_out["labour_hours"],
            "ops": len(layups.estimate_cabin_labour(1.0, 0, 1 if has_elec else 0)),
            "oh": DOME_DEFAULTS["overhead_pct"],
            "margin": DOME_DEFAULTS["markup_pct"],
            "vat": DOME_DEFAULTS["tax_pct"],
            "trans": DOME_DEFAULTS["delivery_bd"],
            "mould": DOME_DEFAULTS["mould_cost"],
            "paste": DOME_DEFAULTS["paste_kg"]}
    else:
        cabin_note = None
    notes = list(extraction.get("notes", []))
    if (not drawing and not bought_ins and not openings_detail
            and FITTED_WORDS_RE.search(description or "")):
        notes.append("No drawing was attached, so door/window/AC auto-detection "
                     "never ran - attach the PDF on the first page and review "
                     "again if these are missing.")
    for item in bought_ins or []:
        item.setdefault("kind", "other")
        item.setdefault("basis", "")
        item.setdefault("by_client", False)
    door_rows = [b for b in bought_ins or []
                 if (b.get("kind") or "other") in ("door", "window")]
    elec_rows = [b for b in bought_ins or []
                 if (b.get("kind") or "other") not in ("door", "window")]
    return {
        "request": request,
        "shape_id": shape_id,
        "shape_label": shapes.get_shape(shape_id)["label"],
        "shape_ids": shapes.SHAPE_IDS,
        "shape_labels": {sid: shapes.SHAPES[sid]["label"] for sid in shapes.SHAPE_IDS},
        "rows": rows,
        "options": options,
        "layup": layup,
        "layup_ids": layups.SCHEDULE_IDS,
        "layup_labels": {sid: layups.schedule_label(sid) for sid in layups.SCHEDULE_IDS},
        "layup_mm": layup_mm,
        "gelcoat": gelcoat_sel,
        "mould_option": mould_option if mould_option in ("have", "need") else "have",
        "mould_cost": mould_cost,
        "mould_life_qty": mould_life_qty if mould_life_qty is not None else "",
        "plywood_m2": plywood_m2,
        "steel_kg": steel_kg,
        "hardware_cost": hardware_cost,
        "resin_type": resin_type if resin_type in costing.RESIN_TYPES else "gp",
        "resin_types": costing.RESIN_TYPES,
        "paint": bool(paint),
        "extra_area_m2": extra_area_m2,
        "delivery_bd": delivery_bd,
        "testing_bd": testing_bd,
        "markup_pct": markup_pct,
        "tax_pct": tax_pct,
        "bought_ins": bought_ins,
        "bought_note": bought_note,
        "bought_blanks": bought_blanks,
        "door_items": door_rows,
        "elec_items": elec_rows,
        "door_blanks": door_blanks,
        "openings_m2": openings_m2,
        "openings_detail": openings_detail or [],
        "open_blanks": open_blanks,
        "cabin_note": cabin_note,
        "paste_kg": paste_kg,
        "plinth_mm": plinth_mm,
        "overhang_mm": overhang_mm,
        "cornice_mm": cornice_mm,
        "sandwich": sandwich,
        "drawing_no": drawing_no,
        "project": project,
        "elec_points": elec_points,
        "scan": scan,
        "scan_json": json.dumps(scan) if scan else "",
        "qty": qty if qty is not None else (extraction.get("quantity") or 1),
        "missing": extraction.get("missing", []),
        "ambiguities": extraction.get("ambiguities", []),
        "questions": extraction.get("questions", []),
        "notes": notes,
        "shape_evidence": extraction.get("shape_evidence", ""),
        "description": description,
        "drawing": drawing,
        "demo_ref": demo_ref,
        "demo_expected": _demo_expected(demo_ref),
        "recipe": recipe_out,
        "recipe_labels": costing.RECIPE_LABELS,
        "labour_note": labour_note,
        "rates": rates_out,
        "rate_labels": costing.RATE_LABELS,
        "ai_error": ai_error,
        "ai_notice": ai_notice,
        "form_errors": form_errors or [],
    }


_AREA_SUFFIX_RE = re.compile(r"\s*(m2|m²|sqm|sq\.?\s*m\.?)\s*$", re.IGNORECASE)


def _parse_area(text):
    """Plain square-metre number, tolerating a trailing m2 unit."""
    return float(_AREA_SUFFIX_RE.sub("", text).strip())


def _detect_schedule(description, extra_text=""):
    """Bought-in items + openings + job info from description plus PDF text."""
    found = schedule.parse_schedule((description or "") + "\n" + (extra_text or ""))
    info = {"openings": found["openings"], "fitted": found["fitted"],
            "has_elec": found["has_elec"], "elec_points": found["elec_points"],
            "job_qty": found["job_qty"],
            "overall": found["overall"], "internal": found["internal"],
            "finishes": found["finishes"], "supports": found["supports"],
            "diameters": found["diameters"], "dome": found["dome"],
            "panels": found["panels"],
            "insulation": found["insulation"], "steel": found["steel"]}
    return found["items"], found["openings_m2"], info


#: Tokens kept uppercase when title-casing a detected product name.
_PRODUCT_ACRONYMS = frozenset({
    "GRP", "FRP", "GRC", "PVC", "UPVC", "GI", "MS", "SS", "IP",
    "AC", "DB", "HDPE", "PP", "PE",
})


def _title_product(text):
    """Title-case a drawing product name, keeping material acronyms upper."""
    out = []
    for word in (text or "").split():
        core = word.strip(".,:;()[]")
        if not core:
            continue
        if core.upper() in _PRODUCT_ACRONYMS:
            out.append(core.upper())
        else:
            out.append(core.capitalize())
    return " ".join(out)


def _clean_product(text):
    """Trim a raw title-block line to a product name ("" when unusable)."""
    text = re.split(r"(?i)\bqty\b", text or "")[0]
    text = re.sub(r"(?i)^\s*(custom[\s-]*built|new)\s+", "", text)
    text = re.sub(r"(?i)\s+details?\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -:,.#")
    if not text or len(text) > 60 or not re.search(r"[A-Za-z]", text):
        return ""
    return _title_product(text)


def _guess_product(drawing_text, filename=""):
    """Product name from drawing title lines, else the upload filename.

    Title-block order: a DETAILS OF line, the head of a QTY title line,
    then the first short GRP/... line; the filename stem is the last
    resort so the Product box is never blank without reason.
    """
    lines = [ln.strip() for ln in (drawing_text or "").splitlines()
             if ln.strip()]
    for line in lines:
        found = re.match(r"(?i)details\s+of\s+(.+)", line)
        if found:
            name = _clean_product(found.group(1))
            if name:
                return name
    for line in lines:
        if " - " in line and re.search(r"(?i)\bqty\b", line):
            name = _clean_product(line.split(" - ")[0])
            if name:
                return name
    for line in lines:
        if len(line) <= 42 and re.match(
                r"(?i)(grp|fibreglass|fiberglass|fibre\s*glass)\s+[a-z][a-z ]*$",
                line):
            return _title_product(line)
    stem = (filename or "").rsplit(".", 1)[0]
    stem = re.sub(r"\s+", " ", stem.replace("_", " ").replace("-", " ")).strip()
    if stem and not re.fullmatch(r"[0-9a-f]{12,}", stem):
        return _title_product(stem)
    return ""


def _build_scan(source, sched_info, sched_items, sched_openings, text=""):
    """Drawing-scan summary for the review page (what was read, from where)."""
    detected = sum(1 for b in sched_items
                   if (b.get("source") or "drawing") == "drawing")
    thin = (not detected and not sched_info.get("overall")
            and not sched_info.get("job_qty")
            and not sched_info.get("diameters"))
    round_product = bool(sched_info.get("diameters"))
    return {"source": source, "overall": sched_info.get("overall"),
            "internal": sched_info.get("internal"),
            "finishes": sched_info.get("finishes") or [],
            "supports": sched_info.get("supports") or [],
            "diameters": sched_info.get("diameters") or [],
            "dome": sched_info.get("dome") or None,
            "panels": sched_info.get("panels") or [],
            "insulation": sched_info.get("insulation") or [],
            "steel": sched_info.get("steel") or [],
            "round": round_product,
            "n_items": detected, "openings_m2": sched_openings,
            "job_qty": sched_info.get("job_qty"), "thin": thin,
            "text": (text or "")[:3000]}


def _parse_bought_ins(form, errors):
    """Bought-in schedule rows; blank and delete-ticked rows are skipped.

    Reads the doors/windows table (doorwin_ prefix) and the electrical &
    other table (boughtin_ prefix); each row keeps its kind, price basis
    and by-client flag for the estimate and the Excel export.
    """
    items = []
    for prefix, default_kind in (("doorwin", "door"), ("boughtin", "other")):
        try:
            count = int(form.get(prefix + "_count") or 0)
        except (TypeError, ValueError):
            count = 0
        for i in range(min(count, 50)):
            if (form.get("%s_%d_del" % (prefix, i)) or "") == "1":
                continue
            label = (form.get("%s_%d_label" % (prefix, i)) or "").strip()
            qty_text = (form.get("%s_%d_qty" % (prefix, i)) or "").strip()
            unit = (form.get("%s_%d_unit" % (prefix, i)) or "").strip() or "no"
            rate_text = (form.get("%s_%d_rate" % (prefix, i)) or "").strip()
            if not label and not qty_text and not rate_text:
                continue
            if not label:
                errors.append("Bought-in row %d needs a label." % (i + 1))
                continue
            try:
                qty = float(qty_text) if qty_text else 1.0
            except ValueError:
                errors.append("Bought-in %r: qty is not a number." % label)
                continue
            try:
                rate = float(rate_text) if rate_text else 0.0
            except ValueError:
                errors.append("Bought-in %r: rate is not a number." % label)
                continue
            if qty < 0 or rate < 0:
                errors.append("Bought-in %r: qty/rate must not be negative."
                              % label)
                continue
            kind = (form.get("%s_%d_kind" % (prefix, i)) or "").strip()
            if kind not in ("door", "window", "ac", "elec", "other"):
                kind = default_kind
            items.append({"label": label, "qty": qty, "unit": unit,
                          "rate": rate, "kind": kind,
                          "basis": (form.get("%s_%d_basis" % (prefix, i))
                                    or "").strip(),
                          "by_client": ((form.get("%s_%d_client" % (prefix, i))
                                         or "") == "1")})
    return items


def _parse_openings(form, errors):
    """Opening rows (label + W/H metres + qty); blank/deleted rows skipped."""
    try:
        count = int(form.get("opening_count") or 0)
    except (TypeError, ValueError):
        count = 0
    rows = []
    for i in range(min(count, 50)):
        if (form.get("opening_%d_del" % i) or "") == "1":
            continue
        label = (form.get("opening_%d_label" % i) or "").strip()
        w_text = (form.get("opening_%d_w" % i) or "").strip()
        h_text = (form.get("opening_%d_h" % i) or "").strip()
        q_text = (form.get("opening_%d_qty" % i) or "").strip()
        if not label and not w_text and not h_text and not q_text:
            continue
        try:
            width = float(w_text) if w_text else 0.0
            height = float(h_text) if h_text else 0.0
            qty = float(q_text) if q_text else 0.0
        except ValueError:
            errors.append("Opening %r: width, height and qty must be numbers."
                          % (label or "#%d" % (i + 1)))
            continue
        if min(width, height, qty) < 0:
            errors.append("Opening %r: size/qty must not be negative."
                          % (label or "#%d" % (i + 1)))
            continue
        if width > 0 and height > 0 and qty > 0:
            rows.append({"label": label or "Opening %d" % (i + 1),
                         "width_m": width, "height_m": height, "qty": qty})
        elif label or w_text or h_text or q_text:
            errors.append("Opening %r: give width, height and qty, or clear "
                          "the row." % (label or "#%d" % (i + 1)))
    return rows


def _posted_blanks(form, count_key, prefix, fields, default):
    """Blank-row count to keep when re-rendering a dynamic row table."""
    try:
        count = int(form.get(count_key) or 0)
    except (TypeError, ValueError):
        return default
    content = 0
    for i in range(min(max(count, 0), 50)):
        if any((form.get("%s_%d_%s" % (prefix, i, field)) or "").strip()
               for field in fields):
            content += 1
    return min(10, max(default, count - content))


def _parse_extra_number(form, name, label, errors):
    """Optional non-negative form number; blank means zero."""
    text = (form.get(name) or "").strip()
    if text == "":
        return 0.0
    try:
        number = float(text)
    except ValueError:
        errors.append("%s is not a number." % label)
        return 0.0
    if number < 0:
        errors.append("%s must not be negative." % label)
        return 0.0
    return number


def _parse_confirm(form, shape_id):
    """Parse the review confirm form; returns (inputs, warnings, errors, raw)."""
    spec = shapes.get_shape(shape_id)
    warnings, errors, raw = [], [], {}
    dims_original, dims_mm = [], {}
    for field in spec["fields"]:
        key = field["key"]
        if field.get("kind") == "area":
            text = (form.get("dim_" + key) or "").strip()
            raw[key] = (text, "m2")
            if text == "":
                errors.append("%s is required." % field["label"])
                continue
            try:
                area_val = _parse_area(text)
            except ValueError:
                errors.append("%s: give a number in m2 (got %r)." % (field["label"], text))
                continue
            if area_val <= 0:
                errors.append("%s must be greater than zero." % field["label"])
                continue
            dims_mm[key] = area_val
            dims_original.append({"field": key, "value": area_val, "unit": "m2"})
            continue
        if field.get("kind") == "count":
            text = (form.get("dim_" + key) or "").strip()
            raw[key] = (text, "nos")
            if text == "":
                if field["required"]:
                    errors.append("%s is required." % field["label"])
                    continue
                dims_mm[key] = float(field.get("default", 0))
                dims_original.append({"field": key, "value": dims_mm[key],
                                      "unit": "nos"})
                continue
            try:
                count_val = float(text)
            except ValueError:
                errors.append("%s: give a whole number (got %r)."
                              % (field["label"], text))
                continue
            if count_val < 0:
                errors.append("%s must not be negative." % field["label"])
                continue
            dims_mm[key] = count_val
            dims_original.append({"field": key, "value": count_val, "unit": "nos"})
            continue
        text = (form.get("dim_" + key) or "").strip()
        unit_sel = form.get("unit_" + key) or "mm"
        raw[key] = (text, unit_sel)
        if text == "":
            if field["required"]:
                errors.append("%s is required." % field["label"])
            else:
                default = float(field.get("default", 0.0))
                dims_mm[key] = default
                dims_original.append({"field": key, "value": default, "unit": "mm"})
                warnings.append("%s not given; factory default %s mm used."
                                % (field["label"], default))
            continue
        try:
            parsed = units.parse_measurement(text, unit_sel)
        except units.UnitError as exc:
            errors.append("%s: %s" % (field["label"], exc))
            continue
        try:
            selected = units.normalize_unit(unit_sel)
        except units.UnitError:
            selected = "mm"
        if parsed["unit"] != selected:
            warnings.append(
                "%s: value %r carries %s but %s was selected; %s used."
                % (field["label"], text, parsed["unit"], selected, parsed["unit"])
            )
        dims_mm[key] = parsed["mm"]
        dims_original.append({"field": key, "value": parsed["value"], "unit": parsed["unit"]})
    options = {}
    for option in spec["options"]:
        options[option["key"]] = (form.get("opt_" + option["key"]) or "") == "yes"
        raw[option["key"]] = ("yes" if options[option["key"]] else "no", "")
    if shape_id == "cabin":
        for key, default in (("plinth_mm", 200.0), ("overhang_mm", 100.0),
                             ("cornice_mm", 350.0)):
            text = (form.get("optnum_" + key) or "").strip()
            if text == "":
                options[key] = default
            else:
                try:
                    options[key] = float(text)
                except ValueError:
                    errors.append("Cabin %s is not a number." % key)
                    options[key] = default
                if options[key] < 0:
                    errors.append("Cabin %s must not be negative." % key)
                    options[key] = default
        options["sandwich"] = (form.get("opt_sandwich") or "yes") == "yes"
    try:
        qty = int(form.get("qty") or 1)
    except (TypeError, ValueError):
        errors.append("Quantity must be a whole number.")
        qty = 1
    layup = (form.get("layup") or DEFAULT_LAYUP.get(shape_id, "classic")).strip()
    if layup not in layups.SCHEDULE_IDS:
        errors.append("Unknown laminate schedule %r." % layup)
        layup = DEFAULT_LAYUP.get(shape_id, "classic")
    gelcoat_raw = (form.get("gelcoat") or "auto").strip().lower()
    if gelcoat_raw == "auto":
        gelcoat = None
    elif gelcoat_raw in ("yes", "true", "1", "on"):
        gelcoat = True
    elif gelcoat_raw in ("no", "false", "0", "off"):
        gelcoat = False
    else:
        errors.append("Gelcoat must be auto, yes or no.")
        gelcoat = None
    mould_option = (form.get("mould_option") or "have").strip().lower()
    if mould_option not in ("have", "need"):
        errors.append("Mould option must be 'have' or 'need'.")
        mould_option = "have"
    mould_cost = _parse_extra_number(form, "mould_cost", "Mould cost", errors)
    paste_kg = _parse_extra_number(form, "paste_kg", "Bonding paste", errors)
    plywood_m2 = _parse_extra_number(form, "plywood_m2", "Plywood supports", errors)
    steel_kg = _parse_extra_number(form, "steel_kg", "Steel supports", errors)
    hardware_cost = _parse_extra_number(form, "hardware_cost", "Hardware", errors)
    extra_area_m2 = _parse_extra_number(form, "extra_area_m2", "Extra laminate area",
                                        errors)
    delivery_bd = _parse_extra_number(form, "delivery_bd", "Delivery", errors)
    testing_bd = _parse_extra_number(form, "testing_bd", "Testing", errors)
    markup_pct = _parse_extra_number(form, "markup_pct", "Markup", errors)
    tax_pct = _parse_extra_number(form, "tax_pct", "Tax", errors)
    if form.get("opening_count") is None:
        openings = []
        openings_m2 = _parse_extra_number(form, "openings_m2", "Openings",
                                          errors)
    else:
        openings = _parse_openings(form, errors)
        openings_m2 = round(sum(o["width_m"] * o["height_m"] * o["qty"]
                                for o in openings), 4)
    bought_ins = _parse_bought_ins(form, errors)
    paint_raw = (form.get("paint") or "no").strip().lower()
    if paint_raw in ("yes", "true", "1", "on"):
        paint = True
    elif paint_raw in ("no", "false", "0", "off"):
        paint = False
    else:
        errors.append("Paint must be yes or no.")
        paint = False
    resin_type = (form.get("resin_type") or "gp").strip().lower()
    if resin_type not in costing.RESIN_TYPES:
        errors.append("Unknown resin type %r." % resin_type)
        resin_type = "gp"
    life_text = (form.get("mould_life_qty") or "").strip()
    if life_text == "":
        mould_life_qty = None
    else:
        try:
            mould_life_qty = int(life_text)
        except ValueError:
            errors.append("Mould life quantity must be a whole number.")
            mould_life_qty = None
        if mould_life_qty is not None and mould_life_qty < 1:
            errors.append("Mould life quantity must be at least 1.")
            mould_life_qty = None
    recipe, rates = {}, {}
    for key in costing.DEFAULT_RECIPE:
        text = (form.get("recipe_" + key) or "").strip()
        try:
            recipe[key] = float(text) if text else costing.DEFAULT_RECIPE[key]
        except ValueError:
            errors.append("Recipe field %s is not a number." % key)
    rate_defaults = _current_rates()
    for key in costing.DEFAULT_RATES:
        text = (form.get("rate_" + key) or "").strip()
        try:
            rates[key] = float(text) if text else rate_defaults[key]
        except ValueError:
            errors.append("Rate field %s is not a number." % key)
    inputs = {"shape_id": shape_id, "dims_original": dims_original, "dims_mm": dims_mm,
              "options": options, "qty": qty, "layup": layup, "gelcoat": gelcoat,
              "mould_option": mould_option, "mould_cost": mould_cost,
              "mould_life_qty": mould_life_qty, "plywood_m2": plywood_m2,
              "steel_kg": steel_kg, "hardware_cost": hardware_cost,
              "resin_type": resin_type, "paint": paint, "extra_area_m2": extra_area_m2,
              "delivery_bd": delivery_bd, "testing_bd": testing_bd,
              "markup_pct": markup_pct, "tax_pct": tax_pct,
              "paste_kg": paste_kg,
              "bought_ins": bought_ins, "openings_m2": openings_m2,
              "openings": openings, "recipe": recipe, "rates": rates,
              "description": form.get("description") or "", "drawing": form.get("drawing") or "",
              "drawing_no": (form.get("drawing_no") or "").strip(),
              "project": (form.get("project") or "").strip()}
    return inputs, warnings, errors, raw


def _dims_display(shape_id, dims_original):
    labels = {f["key"]: f["label"] for f in shapes.get_shape(shape_id)["fields"]}
    display = []
    for entry in dims_original:
        if entry.get("unit") == "m2":
            try:
                metric = "%.2f m2" % float(entry["value"])
            except (TypeError, ValueError):
                metric = "-"
            mm = None
        elif entry.get("unit") == "nos":
            try:
                metric = "%d nos" % int(float(entry["value"]))
            except (TypeError, ValueError):
                metric = "-"
            mm = None
        else:
            try:
                mm = units.to_mm(entry["value"], entry["unit"])
                metric = "%.1f mm" % mm
            except (units.UnitError, TypeError, ValueError):
                mm, metric = None, "-"
        display.append({"field": entry["field"], "label": labels.get(entry["field"], entry["field"]),
                        "value": entry["value"], "unit": entry["unit"], "mm": mm,
                        "metric": metric})
    return display


def _spec_rows(calc):
    """Item specification rows for the estimation sheet."""
    layup = calc.get("layup_label", "Classic")
    if calc.get("schedule_mm"):
        layup += " (~%.1f mm)" % calc["schedule_mm"]
    if calc.get("mould_bd"):
        mould = "New (BD %.3f over %d pc)" % (calc["mould_bd"],
                                              calc.get("mould_life_qty", 0))
    else:
        mould = "Existing (no cost)"
    supports = []
    if calc.get("supports_bd"):
        supports.append("BD %.3f/pc" % calc["supports_bd"])
    if calc.get("hardware_bd"):
        supports.append("hardware BD %.3f/pc" % calc["hardware_bd"])
    rows = [
        ("Product", "%s  x  %d pc" % (calc["shape_label"], calc["qty"])),
        ("Laminate schedule", layup),
        ("Resin / gelcoat / paint",
         "%s / %s / %s" % (calc.get("resin_label", "-"),
                           "yes" if calc.get("gelcoat") else "no",
                           "yes" if calc.get("paint") else "no")),
        ("Mould", mould),
        ("Supports", "; ".join(supports) if supports else "None"),
    ]
    for key, value in (calc.get("options") or {}).items():
        rows.append(("Option: " + key.replace("_", " "),
                     "Yes" if value else "No"))
    recipe = calc.get("recipe", {})
    rows += [
        ("Wastage / MEKP / pigment",
         "%.1f%% / %.2f%% / %.2f%%" % (recipe.get("wastage_pct", 0.0),
                                       recipe.get("mekp_pct", 0.0),
                                       recipe.get("pigment_pct", 0.0))),
        ("Labour / machine / overhead",
         "%.1f hr / %.1f hr / %.1f%%" % (recipe.get("labour_hours", 0.0),
                                         recipe.get("machine_hours", 0.0),
                                         recipe.get("overhead_pct", 0.0))),
    ]
    if calc.get("iso_kg"):
        rows.append(("ISO skin coat",
                     "%.1f%% of resin (%.2f kg)"
                     % (recipe.get("iso_share_pct", 0.0), calc["iso_kg"])))
    if calc.get("tissue_m2"):
        rows.append(("Surface tissue", "%.2f m2" % calc["tissue_m2"]))
    if calc.get("paste_kg"):
        rows.append(("Bonding paste", "%.2f kg" % calc["paste_kg"]))
    if calc.get("consumables_bd"):
        rows.append(("Consumables",
                     "%.1f%% of GRP materials (BD %.3f)"
                     % (recipe.get("consumables_pct", 0.0),
                        calc["consumables_bd"])))
    return [{"label": label, "value": value} for label, value in rows]


def _calc_from_inputs(inputs):
    """costing.calculate from a confirm-form inputs dict (old snapshots safe).

    Inputs saved before the take-off update lack paste_kg and the new
    recipe keys; those recalculate under the old rules (single resin,
    MEKP on resin only, flat BD 0.400 consumables) so history is kept.
    """
    legacy = "paste_kg" not in inputs
    recipe = dict(inputs["recipe"])
    rates = dict(inputs["rates"])
    if legacy:
        recipe.setdefault("iso_share_pct", 0.0)
        recipe.setdefault("consumables_pct", 0.0)
        rates = {k: v for k, v in rates.items()
                 if k in costing.DEFAULT_RATES}
    return costing.calculate(
        inputs["shape_id"], inputs["dims_mm"], inputs["qty"],
        recipe, rates, inputs.get("options"),
        layup=inputs.get("layup") or "classic",
        gelcoat=inputs.get("gelcoat"),
        mould_option=inputs.get("mould_option") or "have",
        mould_cost=inputs.get("mould_cost") or 0.0,
        plywood_m2=inputs.get("plywood_m2") or 0.0,
        steel_kg=inputs.get("steel_kg") or 0.0,
        resin_type=inputs.get("resin_type") or "gp",
        mould_life_qty=inputs.get("mould_life_qty"),
        hardware_cost=inputs.get("hardware_cost") or 0.0,
        paint=inputs.get("paint") or False,
        extra_area_m2=inputs.get("extra_area_m2") or 0.0,
        delivery_bd=inputs.get("delivery_bd") or 0.0,
        testing_bd=inputs.get("testing_bd") or 0.0,
        markup_pct=inputs.get("markup_pct") or 0.0,
        tax_pct=inputs.get("tax_pct") or 0.0,
        bought_ins=inputs.get("bought_ins") or [],
        openings_m2=inputs.get("openings_m2") or 0.0,
        openings=inputs.get("openings") or [],
        paste_kg=inputs.get("paste_kg") or 0.0,
        mekp_on_coat=not legacy,
        consumables_flat=0.4 if legacy else 0.0,
    )

def _demo_cases():
    cases = []
    if not DEMO_DIR.exists():
        return cases
    for path in sorted(DEMO_DIR.glob("*.json")):
        try:
            cases.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return cases


def _demo_case(case_id):
    path = DEMO_DIR / (case_id + ".json")
    if not DEMO_DIR.exists() or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _demo_expected(demo_ref):
    if not demo_ref:
        return None
    case = _demo_case(demo_ref)
    return case.get("expected") if case else None


@app.get("/healthz")
def healthz():
    config = muse_client.MuseConfig()
    return JSONResponse({"status": "ok", "muse": config.summary(), "pdf": _pdf_available()})


@app.get("/", response_class=HTMLResponse)
def home(request: Request, demo: str = ""):
    prefill = {"description": "", "shape_hint": "auto"}
    if demo:
        case = _demo_case(demo)
        if case:
            prefill = {"description": case.get("description", ""),
                       "shape_hint": case.get("shape_hint", "auto"),
                       "case_title": case.get("title", demo)}
    return _render(
        "index.html",
        {"request": request, "result": None, "rates": _current_rates(),
         "muse": muse_client.MuseConfig().summary(), "pdf_ok": _pdf_available(),
         "prefill": prefill, "legacy_error": None, "exclusions": costing.EXCLUSIONS},
    )


@app.post("/estimate", response_class=HTMLResponse)
def legacy_estimate(
    request: Request,
    description: str = Form(""),
    length_mm: float = Form(...),
    width_mm: float = Form(...),
    thickness_mm: float = Form(...),
    flange_mm: float = Form(0),
    qty: int = Form(1),
    resin_pct: float = Form(70),
    fiber_pct: float = Form(30),
    wastage_pct: float = Form(10),
    labour_hours: float = Form(1),
    overhead_pct: float = Form(10),
):
    """Original quick-cost endpoint: same fields, same numbers, via the engine."""
    base = {"request": request, "result": None, "rates": _current_rates(),
            "muse": muse_client.MuseConfig().summary(), "pdf_ok": _pdf_available(),
            "prefill": {"description": description, "shape_hint": "panel"},
            "legacy_error": None, "exclusions": costing.EXCLUSIONS}
    try:
        calc = costing.calculate(
            "panel",
            {"length": length_mm, "width": width_mm, "thickness": thickness_mm,
             "flange": flange_mm},
            qty=qty,
            recipe={"resin_pct": resin_pct, "fiber_pct": fiber_pct,
                    "wastage_pct": wastage_pct, "labour_hours": labour_hours,
                    "overhead_pct": overhead_pct},
            rates=_current_rates(),
        )
    except (shapes.ShapeError, costing.CostingError) as exc:
        base["legacy_error"] = str(exc)
        return _render("index.html", base)
    base["result"] = {
        "description": description or "GRP Product",
        "area": calc["area_m2"],
        "laminate": calc["laminate_kg"],
        "resin": calc["resin_kg"],
        "fiber": calc["fiber_kg"],
        "mekp": calc["mekp_kg"],
        "consumables": calc["consumables_bd"],
        "labour_hours": labour_hours,
        "labour": calc["labour_bd"],
        "subtotal": calc["batch_bd"],
        "overhead": calc["overhead_bd"],
        "total": calc["total_bd"],
        "per_piece": calc["per_piece_bd"],
    }
    base["rates"] = calc["rates"]
    return _render("index.html", base)


@app.post("/extract", response_class=HTMLResponse)
async def extract(
    request: Request,
    description: str = Form(""),
    shape_hint: str = Form("auto"),
    drawing: UploadFile = File(None),
):
    """Describe/upload -> Muse proposes values -> review page (or manual mode)."""
    drawing_ref = ""
    drawing_note = ""
    model_bytes = model_mime = None
    upload_text = ""
    upload_name = ""
    if drawing is not None and drawing.filename:
        upload_name = drawing.filename or ""
        try:
            data = await drawing.read(MAX_UPLOAD_BYTES + 1)
            prepared = _prepare_drawing(drawing.filename, data)
        except UploadError as exc:
            return _render(
                "index.html",
                {"request": request, "result": None, "rates": _current_rates(),
                 "muse": muse_client.MuseConfig().summary(), "pdf_ok": _pdf_available(),
                 "prefill": {"description": description, "shape_hint": shape_hint},
                 "legacy_error": "Upload problem: %s" % exc,
                 "exclusions": costing.EXCLUSIONS},
            )
        drawing_ref = prepared["display"]
        drawing_note = prepared["note"]
        model_bytes, model_mime = prepared["model_bytes"], prepared["model_mime"]
        if str(drawing.filename).lower().endswith(".pdf"):
            upload_text = _pdf_all_text(data)
    config = muse_client.MuseConfig()
    scan_text, scan_error = "", None
    if drawing_ref and len(upload_text.strip()) >= 50:
        scan_source = "PDF text"
    elif drawing_ref and config.configured:
        try:
            scan_text = muse_client.transcribe_drawing(model_bytes, model_mime,
                                                      description, config)
            scan_source = "AI vision transcription"
        except muse_client.MuseError as exc:
            scan_error = exc.message
            scan_source = "drawing (scan failed)"
    elif drawing_ref:
        scan_source = "image (AI scan off - no MODEL_API_KEY)"
    else:
        scan_source = "description only"
    sched_items, sched_openings, sched_info = _detect_schedule(
        description, upload_text + "\n" + scan_text)
    scan = _build_scan(scan_source, sched_info, sched_items, sched_openings,
                       scan_text)
    scan_notes = _scan_notes(scan, drawing_ref, scan_error)
    auto_product = "" if description.strip() else _guess_product(
        upload_text + "\n" + scan_text, upload_name)
    if auto_product:
        scan["product"] = auto_product
    product = description.strip() or auto_product
    if not description.strip() and not drawing_ref:
        extraction = _blank_extraction("panel")
        ctx = _review_context(request, "panel", extraction, description, drawing_ref,
                              ai_notice="Describe the product or upload a drawing first; "
                                        "fields below are blank for manual entry.")
        return _render("review.html", ctx)
    if not config.configured:
        shape_id = shape_hint if shape_hint in shapes.SHAPE_IDS else "panel"
        extraction = _blank_extraction(shape_id)
        if drawing_note:
            extraction["notes"].append(drawing_note)
        extraction["notes"].extend(scan_notes)
        shape_id = _maybe_cabin(shape_id, shape_hint, sched_info, extraction)
        shape_id = _maybe_dome(shape_id, shape_hint, sched_info, extraction)
        ctx = _review_context(
            request, shape_id, extraction, product, drawing_ref,
            ai_notice="AI extraction is off (no MODEL_API_KEY on the server). "
                      "Drawing readings below are still automatic - check them.",
            raw=_overall_raw(shape_id, sched_info),
            qty=sched_info["job_qty"] or None,
            bought_ins=sched_items, openings_m2=sched_openings,
            openings_detail=sched_info["openings"], scan=scan,
            **_cabin_commercial_kwargs(shape_id, sched_info),
                            **_dome_commercial_kwargs(shape_id, sched_info))
        return _render("review.html", ctx)
    try:
        extraction = muse_client.extract_inputs(
            description, model_bytes, model_mime, shape_hint, config)
    except muse_client.MuseError as exc:
        shape_id = shape_hint if shape_hint in shapes.SHAPE_IDS else "panel"
        fallback = _blank_extraction(shape_id)
        if drawing_note:
            fallback["notes"].append(drawing_note)
        shape_id = _maybe_cabin(shape_id, shape_hint, sched_info, fallback)
        shape_id = _maybe_dome(shape_id, shape_hint, sched_info, fallback)
        fallback["notes"].extend(scan_notes)
        ctx = _review_context(request, shape_id, fallback, product, drawing_ref,
                              ai_error="AI extraction failed (%s). Your description and drawing "
                                       "are kept - enter values manually." % exc.message,
                              raw=_overall_raw(shape_id, sched_info),
                              qty=sched_info["job_qty"] or None,
                              bought_ins=sched_items, openings_m2=sched_openings,
                              openings_detail=sched_info["openings"], scan=scan,
                              **_cabin_commercial_kwargs(shape_id, sched_info),
                            **_dome_commercial_kwargs(shape_id, sched_info))
        return _render("review.html", ctx)
    shape_id = extraction["shape"]
    if shape_id == "unknown":
        shape_id = shape_hint if shape_hint in shapes.SHAPE_IDS else "panel"
        extraction["notes"].append("Shape unclear; review started as '%s' - change it if needed."
                                  % shapes.SHAPES[shape_id]["label"])
    shape_id = _maybe_cabin(shape_id, shape_hint, sched_info, extraction)
    shape_id = _maybe_dome(shape_id, shape_hint, sched_info, extraction)
    if drawing_note:
        extraction["notes"].append(drawing_note)
    extraction["notes"].extend(scan_notes)
    ctx = _review_context(request, shape_id, extraction, product, drawing_ref,
                          raw=_overall_raw(shape_id, sched_info),
                          qty=sched_info["job_qty"] or extraction.get("quantity"),
                          bought_ins=sched_items, openings_m2=sched_openings,
                          openings_detail=sched_info["openings"], scan=scan,
                          **_cabin_commercial_kwargs(shape_id, sched_info),
                            **_dome_commercial_kwargs(shape_id, sched_info))
    return _render("review.html", ctx)


def _scan_notes(scan, drawing_ref, scan_error):
    """User-facing notes about how well the drawing was read."""
    notes = []
    if scan_error:
        notes.append("Drawing scan failed (%s) - detection used the "
                     "description only." % scan_error)
    if scan["thin"] and drawing_ref:
        if scan["source"] == "AI vision transcription":
            notes.append("I could read almost nothing from this image - upload "
                         "the original PDF for full auto-detection, or fill the "
                         "values below.")
        elif scan["source"].startswith("image (AI scan off"):
            notes.append("Image uploads need the AI scan, which is off "
                         "(no MODEL_API_KEY) - nothing was auto-read. A PDF "
                         "drawing would still be read.")
    return notes


def _kept_scan(form):
    """Scan summary round-tripped through the review form, if any."""
    try:
        scan = json.loads(form.get("scan_json") or "null")
    except ValueError:
        return None
    return scan if isinstance(scan, dict) else None


def _fresh_cabin(shape_id, sched_info):
    """True when this review starts as a detected fitted cabin."""
    return shape_id == "cabin" and bool(sched_info.get("fitted"))


def _fresh_dome(shape_id, sched_info):
    """True when this review starts as a detected dome/sphere drawing."""
    return shape_id in ("dome", "sphere") and bool(sched_info.get("dome"))


def _maybe_cabin(shape_id, shape_hint, sched_info, extraction):
    """Upgrade auto/box reviews to the cabin shape when the drawing shows
    a fitted cabin (door + windows); anything explicit is respected."""
    if sched_info.get("fitted") and shape_hint in ("auto", "box"):
        if shape_id != "cabin":
            extraction["notes"].append(
                "Detected a fitted cabin (door + windows) - shape set to "
                "'%s'. Switch back to '%s' if this is really a plain tank."
                % (shapes.SHAPES["cabin"]["label"],
                   shapes.SHAPES[shape_id]["label"]))
        return "cabin"
    return shape_id


def _cabin_commercial_kwargs(shape_id, sched_info):
    """Review kwargs for a fresh fitted cabin (standard values otherwise)."""
    if not _fresh_cabin(shape_id, sched_info):
        return {"cabin_defaults": False}
    return {"cabin_defaults": True,
            "mould_option": "need",
            "mould_cost": CABIN_DEFAULTS["mould_cost"],
            "hardware_cost": CABIN_DEFAULTS["hardware_cost"],
            "delivery_bd": CABIN_DEFAULTS["delivery_bd"],
            "markup_pct": CABIN_DEFAULTS["markup_pct"],
            "tax_pct": CABIN_DEFAULTS["tax_pct"]}


def _dome_commercial_kwargs(shape_id, sched_info):
    """Review kwargs for a fresh dome drawing (standard values otherwise)."""
    if not _fresh_dome(shape_id, sched_info):
        return {"dome_defaults": False}
    return {"dome_defaults": True,
            "mould_option": "need",
            "mould_cost": DOME_DEFAULTS["mould_cost"],
            "paste_kg": DOME_DEFAULTS["paste_kg"],
            "paint": True,
            "delivery_bd": DOME_DEFAULTS["delivery_bd"],
            "markup_pct": DOME_DEFAULTS["markup_pct"],
            "tax_pct": DOME_DEFAULTS["tax_pct"]}


def _overall_raw(shape_id, sched_info):
    """Prefill review dims from the drawing's Overall Size line / dome guess."""
    if shape_id == "cabin":
        overall = sched_info.get("overall") or {}
        if not overall:
            return None
        raw = {key: (str(overall[key]), "mm")
               for key in ("length", "width", "height") if overall.get(key)}
        raw["thickness"] = (str(CABIN_DEFAULTS["skin_mm"]), "mm")
        return raw or None
    if shape_id in ("dome", "sphere"):
        dome = sched_info.get("dome") or {}
        if not dome:
            return None
        raw = {}
        if dome.get("outer_dia"):
            raw["diameter"] = (str(dome["outer_dia"]), "mm")
        if dome.get("inner_dia"):
            raw["diameter_inner"] = (str(int(dome["inner_dia"])), "mm")
        if dome.get("rise"):
            rise = float(dome["rise"])
            if dome.get("outer_dia") and dome.get("inner_dia"):
                rise += (float(dome["outer_dia"])
                         - float(dome["inner_dia"])) / 2.0
            raw["height"] = (str(int(round(rise))), "mm")
        if dome.get("skin_outer"):
            raw["thickness"] = (str(dome["skin_outer"]), "mm")
        if dome.get("ring"):
            raw["ring_mm"] = (str(dome["ring"]), "mm")
        if dome.get("base_dia"):
            raw["base_dia_mm"] = (str(dome["base_dia"]), "mm")
        return raw or None
    return None


def _maybe_dome(shape_id, shape_hint, sched_info, extraction):
    """Upgrade auto reviews to the dome shape when the drawing shows dome
    diameters; anything explicit is respected."""
    if sched_info.get("dome") and shape_hint == "auto" and shape_id != "dome":
        if shape_id != "cabin" or not sched_info.get("fitted"):
            extraction["notes"].append(
                "Detected dome diameters - shape set to 'Dome / spherical "
                "cap'. Switch to 'Sphere' for the ball, or back if this is "
                "a different product.")
            return "dome"
    return shape_id


@app.post("/review-shape", response_class=HTMLResponse)
async def review_shape(request: Request):
    """Re-render review rows for another shape, keeping overlapping values."""
    form = await request.form()
    return _rerender_review(
        request, form,
        ["Shape changed - re-check every value before calculating."])


@app.post("/review-rows", response_class=HTMLResponse)
async def review_rows(request: Request):
    """Re-render the review with one more blank item or opening row."""
    form = await request.form()
    return _rerender_review(request, form, [], extra=form.get("add") or "")


def _rerender_review(request, form, notes, extra=""):
    """Re-render the review from posted values, keeping every entry."""
    shape_id = form.get("shape_id") or "panel"
    if shape_id not in shapes.SHAPE_IDS:
        shape_id = "panel"
    described = {
        "shape": shape_id, "shape_evidence": "", "quantity": form.get("qty") or 1,
        "dims": [], "options": {},
        "missing": [f["label"] for f in shapes.get_shape(shape_id)["fields"] if f["required"]],
        "ambiguities": [], "questions": [],
        "notes": list(notes),
    }
    raw = {}
    for key in list(shapes.required_fields(shape_id)) + ["flange"]:
        text = (form.get("dim_" + key) or "").strip()
        if text:
            raw[key] = (text, form.get("unit_" + key) or "mm")
    recipe = {k: form.get("recipe_" + k) or costing.DEFAULT_RECIPE[k]
              for k in costing.DEFAULT_RECIPE}
    rate_defaults = _current_rates()
    rates = {k: form.get("rate_" + k) or rate_defaults[k]
             for k in costing.DEFAULT_RATES}
    try:
        qty = int(form.get("qty") or 1)
    except (TypeError, ValueError):
        qty = 1
    shape_errors = []
    kept_bought = _parse_bought_ins(form, shape_errors)
    if form.get("opening_count") is None:
        kept_open = []
        kept_openings = _parse_extra_number(form, "openings_m2", "Openings",
                                            shape_errors)
    else:
        kept_open = _parse_openings(form, shape_errors)
        kept_openings = round(sum(o["width_m"] * o["height_m"] * o["qty"]
                                  for o in kept_open), 4)
    bought_blanks = _posted_blanks(form, "boughtin_count", "boughtin",
                                   ("label", "qty", "rate"), 2)
    open_blanks = _posted_blanks(form, "opening_count", "opening",
                                 ("label", "w", "h", "qty"), 1)
    door_blanks = _posted_blanks(form, "doorwin_count", "doorwin",
                                 ("label", "qty", "rate"), 1)
    if extra == "boughtin":
        bought_blanks = min(10, bought_blanks + 1)
    elif extra == "opening":
        open_blanks = min(10, open_blanks + 1)
    elif extra == "door":
        door_blanks = min(10, door_blanks + 1)
    ctx = _review_context(request, shape_id, described, form.get("description") or "",
                          form.get("drawing") or "", demo_ref=form.get("demo_ref") or None,
                          raw=raw, recipe=recipe, rates=rates, qty=qty,
                          layup=form.get("layup") or None,
                          gelcoat=form.get("gelcoat") or "auto",
                          mould_option=form.get("mould_option") or "have",
                          mould_cost=form.get("mould_cost") or 0.0,
                          mould_life_qty=form.get("mould_life_qty") or None,
                          plywood_m2=form.get("plywood_m2") or 0.0,
                          steel_kg=form.get("steel_kg") or 0.0,
                          hardware_cost=form.get("hardware_cost") or 0.0,
                          resin_type=form.get("resin_type") or "gp",
                          paint=(form.get("paint") or "no") == "yes",
                          extra_area_m2=form.get("extra_area_m2") or 0.0,
                          delivery_bd=form.get("delivery_bd") or 0.0,
                          testing_bd=form.get("testing_bd") or 0.0,
                          markup_pct=form.get("markup_pct") or 0.0,
                          tax_pct=form.get("tax_pct") or 0.0,
                          paste_kg=form.get("paste_kg") or 0.0,
                          plinth_mm=form.get("optnum_plinth_mm") or 200.0,
                          overhang_mm=form.get("optnum_overhang_mm") or 100.0,
                          cornice_mm=form.get("optnum_cornice_mm") or 350.0,
                          sandwich=(form.get("opt_sandwich") or "yes") == "yes",
                          drawing_no=form.get("drawing_no") or "",
                          project=form.get("project") or "",
                          bought_ins=kept_bought, openings_m2=kept_openings,
                          openings_detail=kept_open, scan=_kept_scan(form),
                          bought_blanks=bought_blanks, open_blanks=open_blanks,
                          door_blanks=door_blanks)
    return _render("review.html", ctx)

@app.post("/api/totals")
async def api_totals(request: Request):
    """Live totals for the review page footer (JSON, same engine)."""
    form = await request.form()
    shape_id = form.get("shape_id") or "panel"
    if shape_id not in shapes.SHAPE_IDS:
        return JSONResponse({"ok": False, "error": "Unknown shape."})
    inputs, _warnings, errors, _raw = _parse_confirm(form, shape_id)
    if errors:
        return JSONResponse({"ok": False, "error": errors[0],
                             "errors": errors})
    try:
        calc = _calc_from_inputs(inputs)
    except (shapes.ShapeError, costing.CostingError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    qty = calc["qty"]
    bought = calc.get("bought_ins_bd", 0.0) + calc.get("supports_bd", 0.0)
    return JSONResponse({
        "ok": True,
        "per_piece": round(calc["per_piece_bd"], 3),
        "project": round(calc["total_bd"], 3),
        "selling": round(calc.get("selling_bd", 0.0), 3),
        "selling_inc": round(calc.get("grand_total_bd", 0.0), 3),
        "qty": qty,
        "tax_pct": inputs.get("tax_pct", 0.0),
        "grp": round(calc.get("grp_basket_bd", 0.0)
                     + calc.get("consumables_bd", 0.0), 3),
        "bought": round(bought, 3),
        "labour": round(calc.get("labour_bd", 0.0), 3),
        "labour_hours": inputs["recipe"].get("labour_hours", 0.0),
        "mould_trans": round(calc.get("mould_pc_bd", 0.0)
                             + inputs.get("delivery_bd", 0.0)
                             + inputs.get("testing_bd", 0.0), 3),
        "direct": round(calc.get("subtotal_pc_bd", 0.0)
                        + calc.get("mould_pc_bd", 0.0)
                        + inputs.get("delivery_bd", 0.0)
                        + inputs.get("testing_bd", 0.0), 3),
        "area": round(calc.get("area_m2", 0.0), 2),
        "laminate": round(calc.get("laminate_kg", 0.0), 1),
    })


@app.post("/api/price-check")
async def api_price_check():
    """AI online price lookup for the rate book (JSON, nothing saved)."""
    config = muse_client.MuseConfig()
    if not config.configured:
        return JSONResponse({"ok": False, "error":
                             "Online price check needs MODEL_API_KEY on the server."})
    try:
        current = materials.get_state()["rates"]
    except materials.MaterialsError:
        current = dict(costing.DEFAULT_RATES)
    try:
        found = muse_client.suggest_prices(list(costing.RATE_LABELS.items()),
                                           config)
    except muse_client.MuseError as exc:
        return JSONResponse({"ok": False, "error": exc.message})
    prices = {}
    for key in costing.DEFAULT_RATES:
        entry = found.get(key) or {}
        prices[key] = {"current": current.get(key),
                       "price": entry.get("price"),
                       "note": entry.get("note", "")}
    return JSONResponse({"ok": True, "prices": prices})


@app.post("/calculate-xlsx")
async def calculate_xlsx(request: Request):
    """Review values straight to a live-formula Excel file (one click)."""
    from io import BytesIO

    form = await request.form()
    shape_id = form.get("shape_id") or "panel"
    if shape_id not in shapes.SHAPE_IDS:
        shape_id = "panel"
    inputs, _warnings, errors, _raw = _parse_confirm(form, shape_id)
    if errors:
        return HTMLResponse("Cannot build this file: " + " ".join(errors),
                            status_code=400)
    try:
        calc = _calc_from_inputs(inputs)
    except (shapes.ShapeError, costing.CostingError) as exc:
        return HTMLResponse("Could not build this file (%s)." % exc,
                            status_code=400)
    title = (inputs.get("description") or calc["shape_label"])[:60]
    wb = xlsx_report.build_workbook(title, inputs["qty"], calc, inputs,
                                    calc["rates"])
    buffer = BytesIO()
    wb.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 'attachment; filename="estimate_costing.xlsx"'})


@app.post("/calculate", response_class=HTMLResponse)
async def calculate(request: Request):
    """Confirmed review values -> deterministic estimate -> result page."""
    form = await request.form()
    shape_id = form.get("shape_id") or "panel"
    if shape_id not in shapes.SHAPE_IDS:
        shape_id = "panel"
    inputs, warnings, errors, raw = _parse_confirm(form, shape_id)
    bought_blanks = _posted_blanks(form, "boughtin_count", "boughtin",
                                   ("label", "qty", "rate"), 2)
    open_blanks = _posted_blanks(form, "opening_count", "opening",
                                 ("label", "w", "h", "qty"), 1)
    door_blanks = _posted_blanks(form, "doorwin_count", "doorwin",
                                 ("label", "qty", "rate"), 1)
    if not inputs["openings"] and inputs["openings_m2"] > 0:
        kept_open_err = [{"label": "Openings (total entered)",
                          "width_m": inputs["openings_m2"], "height_m": 1,
                          "qty": 1}]
    else:
        kept_open_err = inputs["openings"]
    if errors:
        described = _blank_extraction(shape_id, inputs["qty"])
        ctx = _review_context(request, shape_id, described, inputs["description"],
                              inputs["drawing"], demo_ref=form.get("demo_ref") or None,
                              form_errors=errors, raw=raw, recipe=inputs["recipe"],
                              rates=inputs["rates"], qty=inputs["qty"],
                              layup=inputs["layup"],
                              gelcoat=("auto" if inputs["gelcoat"] is None
                                       else inputs["gelcoat"]),
                              mould_option=inputs["mould_option"],
                              mould_cost=inputs["mould_cost"],
                              mould_life_qty=inputs["mould_life_qty"],
                              plywood_m2=inputs["plywood_m2"], steel_kg=inputs["steel_kg"],
                              hardware_cost=inputs["hardware_cost"],
                              resin_type=inputs["resin_type"],
                              paint=inputs["paint"],
                              extra_area_m2=inputs["extra_area_m2"],
                              delivery_bd=inputs["delivery_bd"],
                              testing_bd=inputs["testing_bd"],
                              markup_pct=inputs["markup_pct"],
                              tax_pct=inputs["tax_pct"],
                              paste_kg=inputs["paste_kg"],
                              plinth_mm=inputs["options"].get("plinth_mm", 200.0),
                              overhang_mm=inputs["options"].get("overhang_mm", 100.0),
                              cornice_mm=inputs["options"].get("cornice_mm", 350.0),
                              sandwich=inputs["options"].get("sandwich", True),
                              drawing_no=inputs.get("drawing_no") or "",
                              project=inputs.get("project") or "",
                              bought_ins=inputs["bought_ins"],
                              openings_m2=inputs["openings_m2"],
                              openings_detail=kept_open_err,
                              scan=_kept_scan(form),
                              bought_blanks=bought_blanks,
                              open_blanks=open_blanks,
                              door_blanks=door_blanks)
        return _render("review.html", ctx)
    try:
        calc = _calc_from_inputs(inputs)
    except (shapes.ShapeError, costing.CostingError) as exc:
        described = _blank_extraction(shape_id, inputs["qty"])
        ctx = _review_context(request, shape_id, described, inputs["description"],
                              inputs["drawing"], demo_ref=form.get("demo_ref") or None,
                              form_errors=[str(exc)], raw=raw, recipe=inputs["recipe"],
                              rates=inputs["rates"], qty=inputs["qty"],
                              layup=inputs["layup"],
                              gelcoat=("auto" if inputs["gelcoat"] is None
                                       else inputs["gelcoat"]),
                              mould_option=inputs["mould_option"],
                              mould_cost=inputs["mould_cost"],
                              mould_life_qty=inputs["mould_life_qty"],
                              plywood_m2=inputs["plywood_m2"], steel_kg=inputs["steel_kg"],
                              hardware_cost=inputs["hardware_cost"],
                              resin_type=inputs["resin_type"],
                              paint=inputs["paint"],
                              extra_area_m2=inputs["extra_area_m2"],
                              delivery_bd=inputs["delivery_bd"],
                              testing_bd=inputs["testing_bd"],
                              markup_pct=inputs["markup_pct"],
                              tax_pct=inputs["tax_pct"],
                              paste_kg=inputs["paste_kg"],
                              plinth_mm=inputs["options"].get("plinth_mm", 200.0),
                              overhang_mm=inputs["options"].get("overhang_mm", 100.0),
                              cornice_mm=inputs["options"].get("cornice_mm", 350.0),
                              sandwich=inputs["options"].get("sandwich", True),
                              drawing_no=inputs.get("drawing_no") or "",
                              project=inputs.get("project") or "",
                              bought_ins=inputs["bought_ins"],
                              openings_m2=inputs["openings_m2"],
                              openings_detail=kept_open_err,
                              scan=_kept_scan(form),
                              bought_blanks=bought_blanks,
                              open_blanks=open_blanks,
                              door_blanks=door_blanks)
        return _render("review.html", ctx)
    warnings = warnings + calc["warnings"]
    if (not inputs["drawing"] and not inputs["bought_ins"]
            and shape_id in ("box", "cabin")):
        warnings.append("No drawing was attached to this estimate, so door/window/AC "
                        "auto-detection never ran - attach the PDF on the first page "
                        "and recalculate if these are missing.")
    inputs["scan"] = _kept_scan(form)
    ctx = {
        "request": request,
        "inputs": inputs,
        "inputs_json": json.dumps(inputs),
        "dims_display": _dims_display(shape_id, inputs["dims_original"]),
        "result": calc,
        "spec_rows": _spec_rows(calc),
        "sheet_no": "DRAFT",
        "sheet_date": time.strftime("%Y-%m-%d %H:%M"),
        "sheet_status": "Draft - not saved yet",
        "warnings": warnings,
        "explanation": None,
        "ai_error": None,
        "ai_available": muse_client.MuseConfig().configured,
    }
    return _render("result.html", ctx)


@app.post("/review-edit", response_class=HTMLResponse)
async def review_edit(request: Request):
    """Reopen calculated inputs on the review page for correction."""
    form = await request.form()
    try:
        inputs = json.loads(form.get("inputs_json") or "{}")
        shape_id = inputs["shape_id"]
        shapes.get_shape(shape_id)
    except (ValueError, KeyError):
        return HTMLResponse("Cannot reopen those inputs.", status_code=400)
    described = _blank_extraction(shape_id, inputs.get("qty", 1))
    described["missing"] = []
    raw = {}
    for entry in inputs.get("dims_original", []):
        raw[entry["field"]] = (str(entry["value"]), entry.get("unit", "mm"))
    for key, value in (inputs.get("options") or {}).items():
        raw[key] = ("yes" if value else "no", "")
    gelcoat = inputs.get("gelcoat")
    ctx = _review_context(request, shape_id, described, inputs.get("description", ""),
                          inputs.get("drawing", ""), demo_ref=form.get("demo_ref") or None,
                          raw=raw, recipe=inputs.get("recipe"), rates=inputs.get("rates"),
                          qty=inputs.get("qty", 1),
                          layup=inputs.get("layup") or None,
                          gelcoat="auto" if gelcoat is None else gelcoat,
                          mould_option=inputs.get("mould_option") or "have",
                          mould_cost=inputs.get("mould_cost") or 0.0,
                          mould_life_qty=inputs.get("mould_life_qty"),
                          plywood_m2=inputs.get("plywood_m2") or 0.0,
                          steel_kg=inputs.get("steel_kg") or 0.0,
                          hardware_cost=inputs.get("hardware_cost") or 0.0,
                          resin_type=inputs.get("resin_type") or "gp",
                          paint=inputs.get("paint") or False,
                          extra_area_m2=inputs.get("extra_area_m2") or 0.0,
                          delivery_bd=inputs.get("delivery_bd") or 0.0,
                          testing_bd=inputs.get("testing_bd") or 0.0,
                          markup_pct=inputs.get("markup_pct") or 0.0,
                          tax_pct=inputs.get("tax_pct") or 0.0,
                          paste_kg=inputs.get("paste_kg") or 0.0,
                          plinth_mm=(inputs.get("options") or {}).get("plinth_mm", 200.0),
                          overhang_mm=(inputs.get("options") or {}).get("overhang_mm", 100.0),
                          cornice_mm=(inputs.get("options") or {}).get("cornice_mm", 350.0),
                          sandwich=(inputs.get("options") or {}).get("sandwich", True),
                          drawing_no=inputs.get("drawing_no") or "",
                          project=inputs.get("project") or "",
                          bought_ins=inputs.get("bought_ins") or [],
                          openings_m2=inputs.get("openings_m2") or 0.0,
                          openings_detail=inputs.get("openings") or [],
                          scan=inputs.get("scan"))
    return _render("review.html", ctx)


@app.post("/explain", response_class=HTMLResponse)
async def explain(request: Request):
    inputs_json = (await request.form()).get("inputs_json") or "{}"
    try:
        inputs = json.loads(inputs_json)
        calc = _calc_from_inputs(inputs)
    except (ValueError, KeyError) as exc:
        return HTMLResponse("Could not recompute this estimate (%s)." % exc, status_code=400)
    summary = _estimate_summary(inputs, calc)
    explanation, ai_error = None, None
    try:
        explanation = muse_client.explain_estimate(summary)
    except muse_client.MuseError as exc:
        ai_error = exc.message
    return _render(
        "result.html",
        {"request": request, "inputs": inputs, "inputs_json": inputs_json,
         "dims_display": _dims_display(inputs["shape_id"], inputs["dims_original"]),
         "result": calc, "spec_rows": _spec_rows(calc), "sheet_no": "DRAFT",
         "sheet_date": time.strftime("%Y-%m-%d %H:%M"),
         "sheet_status": "Draft - not saved yet",
         "warnings": calc["warnings"], "explanation": explanation,
         "ai_error": ai_error, "ai_available": muse_client.MuseConfig().configured},
    )


def _estimate_summary(inputs, calc):
    lines = [
        "Estimate for %s, batch of %d." % (calc["shape_label"], calc["qty"]),
        "Area %.4f m2; laminate %.2f kg per piece." % (calc["area_m2"], calc["laminate_kg"]),
        "Materials per piece: resin %.2f kg, fibre %.2f kg, MEKP %.3f kg."
        % (calc["resin_kg"], calc["fiber_kg"], calc["mekp_kg"]),
        "Bought-ins: %d items BD %.3f; openings %s m2."
        % (len(calc.get("bought_ins") or []), calc.get("bought_ins_bd", 0.0),
           calc.get("openings_m2", 0.0)),
        "Layup: %s; %s resin; gelcoat %s; mould %s."
        % (calc.get("layup_label", "classic"),
           calc.get("resin_label", "GP / ortho polyester"),
           "yes" if calc.get("gelcoat") else "no",
           ("new (BD %.3f over %d pc)" % (calc.get("mould_bd", 0.0),
                                          calc.get("mould_life_qty", 0)))
           if calc.get("mould_bd") else "existing"),
        "Cost: materials BD %.3f + labour BD %.3f per piece; batch BD %.3f + overhead BD %.3f."
        % (calc["material_bd"], calc["labour_bd"], calc["batch_bd"], calc["overhead_bd"]),
        "Total BD %.3f; cost per piece BD %.3f."
        % (calc["total_bd"], calc["per_piece_bd"]),
        ("Selling BD %.3f; grand total BD %.3f (tax included)."
         % (calc.get("selling_bd", 0.0), calc.get("grand_total_bd", 0.0)))
        if calc.get("markup_pct") or calc.get("tax_pct") else
        "Cost estimate only: no markup or tax included.",
        "Exclusions: " + "; ".join(calc["exclusions"]) + ".",
    ]
    return "\n".join(lines)


@app.post("/save")
async def save_estimate(request: Request, label: str = Form(""), inputs_json: str = Form("{}")):
    try:
        inputs = json.loads(inputs_json)
        calc = _calc_from_inputs(inputs)
    except (ValueError, KeyError) as exc:
        return HTMLResponse("Could not save (%s)." % exc, status_code=400)
    record = {
        "label": label.strip() or "Untitled estimate",
        "shape_id": inputs["shape_id"],
        "dims_original": inputs["dims_original"],
        "dims_mm": inputs["dims_mm"],
        "options": inputs.get("options", {}),
        "qty": inputs["qty"],
        "layup": inputs.get("layup") or "classic",
        "gelcoat": inputs.get("gelcoat"),
        "mould_option": inputs.get("mould_option") or "have",
        "mould_cost": inputs.get("mould_cost") or 0.0,
        "mould_life_qty": inputs.get("mould_life_qty"),
        "plywood_m2": inputs.get("plywood_m2") or 0.0,
        "steel_kg": inputs.get("steel_kg") or 0.0,
        "hardware_cost": inputs.get("hardware_cost") or 0.0,
        "resin_type": inputs.get("resin_type") or "gp",
        "paint": inputs.get("paint") or False,
        "extra_area_m2": inputs.get("extra_area_m2") or 0.0,
        "delivery_bd": inputs.get("delivery_bd") or 0.0,
        "testing_bd": inputs.get("testing_bd") or 0.0,
        "markup_pct": inputs.get("markup_pct") or 0.0,
        "tax_pct": inputs.get("tax_pct") or 0.0,
        "paste_kg": inputs.get("paste_kg") or 0.0,
        "drawing_no": inputs.get("drawing_no") or "",
        "project": inputs.get("project") or "",
        "bought_ins": inputs.get("bought_ins") or [],
        "openings_m2": inputs.get("openings_m2") or 0.0,
        "openings": inputs.get("openings") or [],
        "recipe": inputs["recipe"],
        "rates": inputs["rates"],
        "description": inputs.get("description", ""),
        "drawing": inputs.get("drawing", ""),
        "result": calc,
    }
    try:
        saved = store.save_new(record)
    except store.StoreError as exc:
        return HTMLResponse("Could not save (%s)." % exc, status_code=500)
    return RedirectResponse("/estimates/%s" % saved["id"], status_code=303)


@app.get("/estimates", response_class=HTMLResponse)
def list_estimates(request: Request):
    try:
        estimates = store.list_all()
    except store.StoreError as exc:
        return HTMLResponse("Saved estimates unavailable (%s)." % exc, status_code=500)
    return _render("estimates.html", {"request": request, "estimates": estimates})

def _with_calc_defaults(calc):
    """Backfill display keys missing from older saved results."""
    for key, default in (("layup_label", "Classic (resin/fibre %)"), ("gelcoat", False),
                         ("mould_bd", 0.0), ("supports_bd", 0.0),
                         ("resin_label", "GP / ortho polyester"), ("paint", False),
                         ("delivery_bd", 0.0), ("testing_bd", 0.0),
                         ("markup_pct", 0.0), ("markup_bd", 0.0),
                         ("selling_bd", 0.0), ("tax_pct", 0.0), ("tax_bd", 0.0),
                         ("grand_total_bd", 0.0)):
        calc.setdefault(key, default)
    calc.setdefault("mould_life_qty", calc.get("qty", 1))
    # Older snapshots stored delivery/testing as batch figures already.
    calc.setdefault("delivery_batch_bd", calc.get("delivery_bd", 0.0))
    calc.setdefault("testing_batch_bd", calc.get("testing_bd", 0.0))
    return calc


def _pdf_response(data, filename):
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition":
                             'attachment; filename="%s"' % filename})


@app.post("/pdf")
async def draft_pdf(request: Request):
    """Download the current (unsaved) estimate as a PDF sheet."""
    inputs_json = (await request.form()).get("inputs_json") or "{}"
    try:
        inputs = json.loads(inputs_json)
        calc = _calc_from_inputs(inputs)
    except (ValueError, KeyError) as exc:
        return HTMLResponse("Could not build this PDF (%s)." % exc, status_code=400)
    data = pdf_report.build_pdf(
        "DRAFT", time.strftime("%Y-%m-%d %H:%M"), "Draft - not saved", calc,
        _dims_display(inputs["shape_id"], inputs["dims_original"]),
        _spec_rows(calc), inputs.get("description", ""))
    return _pdf_response(data, "estimate_draft.pdf")


@app.get("/estimates/{estimate_id}/pdf")
def estimate_pdf(estimate_id: str, rev: str = ""):
    """Download a saved estimate revision as a PDF sheet."""
    try:
        meta, revision = store.get(estimate_id, int(rev) if rev else None)
    except (store.StoreError, ValueError) as exc:
        return HTMLResponse("Estimate not found (%s)." % exc, status_code=404)
    snapshot = revision["snapshot"]
    calc = _with_calc_defaults(snapshot["result"])
    data = pdf_report.build_pdf(
        meta["id"], revision["saved_at"],
        "Revision %d of %d" % (revision["rev"], meta["rev_count"]), calc,
        _dims_display(snapshot["shape_id"], snapshot["dims_original"]),
        _spec_rows(calc), snapshot.get("description", ""))
    return _pdf_response(data, "estimate_%s_r%d.pdf" % (meta["id"], revision["rev"]))


@app.post("/xlsx")
async def draft_xlsx(request: Request):
    """Download the current (unsaved) estimate as a live-formula Excel file."""
    from io import BytesIO

    inputs_json = (await request.form()).get("inputs_json") or "{}"
    try:
        inputs = json.loads(inputs_json)
        calc = _calc_from_inputs(inputs)
    except (ValueError, KeyError) as exc:
        return HTMLResponse("Could not build this file (%s)." % exc, status_code=400)
    title = (inputs.get("description") or calc["shape_label"])[:60]
    wb = xlsx_report.build_workbook(title, inputs["qty"], calc, inputs, calc["rates"])
    buffer = BytesIO()
    wb.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="estimate_draft.xlsx"'})


@app.get("/estimates/{estimate_id}/xlsx")
def estimate_xlsx(estimate_id: str, rev: str = ""):
    """Download a saved estimate revision as a live-formula Excel file."""
    from io import BytesIO

    try:
        meta, revision = store.get(estimate_id, int(rev) if rev else None)
    except (store.StoreError, ValueError) as exc:
        return HTMLResponse("Estimate not found (%s)." % exc, status_code=404)
    snapshot = revision["snapshot"]
    calc = _with_calc_defaults(snapshot["result"])
    title = (snapshot.get("description") or snapshot.get("label") or
             calc["shape_label"])[:60]
    wb = xlsx_report.build_workbook(title, snapshot["qty"], calc, snapshot,
                                    calc["rates"])
    buffer = BytesIO()
    wb.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="estimate_%s_r%d.xlsx"'
                                        % (meta["id"], revision["rev"])})


@app.get("/estimates/{estimate_id}", response_class=HTMLResponse)
def estimate_detail(request: Request, estimate_id: str, rev: str = ""):
    try:
        meta, revision = store.get(estimate_id, int(rev) if rev else None)
    except (store.StoreError, ValueError) as exc:
        return HTMLResponse("Estimate not found (%s)." % exc, status_code=404)
    snapshot = revision["snapshot"]
    calc = _with_calc_defaults(snapshot["result"])
    try:
        others = store.list_all()
    except store.StoreError:
        others = []
    return _render(
        "detail.html",
        {"request": request, "meta": meta, "rev": revision["rev"],
         "saved_at": revision["saved_at"], "snapshot": snapshot, "result": calc,
         "dims_display": _dims_display(snapshot["shape_id"], snapshot["dims_original"]),
         "spec_rows": _spec_rows(calc),
         "sheet_no": meta["id"], "sheet_date": revision["saved_at"],
         "sheet_status": "Revision %d of %d" % (revision["rev"], meta["rev_count"]),
         "layup_ids": layups.SCHEDULE_IDS,
         "layup_labels": {sid: layups.schedule_label(sid) for sid in layups.SCHEDULE_IDS},
         "recipe_labels": costing.RECIPE_LABELS,
         "rate_labels": costing.RATE_LABELS,
         "others": others},
    )


@app.post("/estimates/{estimate_id}/revise")
async def revise_estimate(request: Request, estimate_id: str):
    form = await request.form()
    try:
        meta, _ = store.get(estimate_id)
    except store.StoreError as exc:
        return HTMLResponse("Estimate not found (%s)." % exc, status_code=404)
    shape_id = meta["shape_id"]
    inputs, _, errors, _ = _parse_confirm(form, shape_id)
    if errors:
        return HTMLResponse("Cannot revise: " + " ".join(errors), status_code=400)
    try:
        calc = _calc_from_inputs(inputs)
    except (shapes.ShapeError, costing.CostingError) as exc:
        return HTMLResponse("Cannot revise (%s)." % exc, status_code=400)
    snapshot = {
        "label": meta["label"],
        "shape_id": shape_id,
        "dims_original": inputs["dims_original"],
        "dims_mm": inputs["dims_mm"],
        "options": inputs.get("options", {}),
        "qty": inputs["qty"],
        "layup": inputs.get("layup") or "classic",
        "gelcoat": inputs.get("gelcoat"),
        "mould_option": inputs.get("mould_option") or "have",
        "mould_cost": inputs.get("mould_cost") or 0.0,
        "mould_life_qty": inputs.get("mould_life_qty"),
        "plywood_m2": inputs.get("plywood_m2") or 0.0,
        "steel_kg": inputs.get("steel_kg") or 0.0,
        "hardware_cost": inputs.get("hardware_cost") or 0.0,
        "resin_type": inputs.get("resin_type") or "gp",
        "paint": inputs.get("paint") or False,
        "extra_area_m2": inputs.get("extra_area_m2") or 0.0,
        "delivery_bd": inputs.get("delivery_bd") or 0.0,
        "testing_bd": inputs.get("testing_bd") or 0.0,
        "markup_pct": inputs.get("markup_pct") or 0.0,
        "tax_pct": inputs.get("tax_pct") or 0.0,
        "paste_kg": inputs.get("paste_kg") or 0.0,
        "drawing_no": inputs.get("drawing_no") or "",
        "project": inputs.get("project") or "",
        "bought_ins": inputs.get("bought_ins") or [],
        "openings_m2": inputs.get("openings_m2") or 0.0,
        "openings": inputs.get("openings") or [],
        "recipe": inputs["recipe"],
        "rates": inputs["rates"],
        "description": inputs.get("description", ""),
        "drawing": inputs.get("drawing", ""),
        "result": calc,
    }
    try:
        rev = store.add_revision(estimate_id, snapshot)
    except store.StoreError as exc:
        return HTMLResponse("Could not save revision (%s)." % exc, status_code=500)
    return RedirectResponse("/estimates/%s?rev=%d" % (estimate_id, rev), status_code=303)


def _parse_side(value):
    if ":" in value:
        estimate_id, _, rev = value.partition(":")
        return estimate_id, int(rev)
    return value, None


@app.get("/compare", response_class=HTMLResponse)
def compare(request: Request, a: str = "", b: str = ""):
    if not a or not b:
        return HTMLResponse("Pick two revisions to compare.", status_code=400)
    try:
        a_id, a_rev = _parse_side(a)
        b_id, b_rev = _parse_side(b)
        meta_a, rev_a = store.get(a_id, a_rev)
        meta_b, rev_b = store.get(b_id, b_rev)
    except (store.StoreError, ValueError) as exc:
        return HTMLResponse("Cannot compare (%s)." % exc, status_code=404)
    snap_a, snap_b = rev_a["snapshot"], rev_b["snapshot"]
    diffs = _diff_inputs(snap_a, snap_b)
    total_a, total_b = snap_a["result"]["total_bd"], snap_b["result"]["total_bd"]
    pc_a, pc_b = snap_a["result"]["per_piece_bd"], snap_b["result"]["per_piece_bd"]
    totals = {
        "batch_a": total_a, "batch_b": total_b, "batch_delta": total_b - total_a,
        "batch_pct": (total_b - total_a) / total_a * 100.0 if total_a else 0.0,
        "pc_a": pc_a, "pc_b": pc_b, "pc_delta": pc_b - pc_a,
        "pc_pct": (pc_b - pc_a) / pc_a * 100.0 if pc_a else 0.0,
    }
    return _render(
        "compare.html",
        {"request": request, "meta_a": meta_a, "rev_a": rev_a["rev"],
         "snap_a": snap_a, "meta_b": meta_b, "rev_b": rev_b["rev"], "snap_b": snap_b,
         "diffs": diffs, "totals": totals},
    )


def _diff_inputs(snap_a, snap_b):
    rows = []
    dims_a = {d["field"]: d for d in snap_a["dims_original"]}
    dims_b = {d["field"]: d for d in snap_b["dims_original"]}
    for field in sorted(set(dims_a) | set(dims_b)):
        left = dims_a.get(field)
        right = dims_b.get(field)
        ltext = "%s %s" % (left["value"], left["unit"]) if left else "-"
        rtext = "%s %s" % (right["value"], right["unit"]) if right else "-"
        rows.append({"label": field, "left": ltext, "right": rtext, "changed": ltext != rtext})
    rows.append({"label": "qty", "left": str(snap_a.get("qty")), "right": str(snap_b.get("qty")),
                 "changed": snap_a.get("qty") != snap_b.get("qty")})
    for key, default in (("layup", "classic"), ("gelcoat", None), ("mould_option", "have"),
                         ("mould_cost", 0.0), ("mould_life_qty", None),
                         ("plywood_m2", 0.0), ("steel_kg", 0.0),
                         ("hardware_cost", 0.0), ("resin_type", "gp"),
                         ("paint", False), ("extra_area_m2", 0.0),
                         ("delivery_bd", 0.0), ("testing_bd", 0.0),
                         ("markup_pct", 0.0), ("tax_pct", 0.0),
                         ("openings_m2", 0.0)):
        left, right = snap_a.get(key, default), snap_b.get(key, default)
        rows.append({"label": key, "left": str(left), "right": str(right),
                     "changed": left != right})

    def _bought_summary(snap):
        items = snap.get("bought_ins") or []
        total = sum(float(i.get("qty", 0)) * float(i.get("rate", 0)) for i in items)
        return "%d items / BD %.3f" % (len(items), total)

    left, right = _bought_summary(snap_a), _bought_summary(snap_b)
    rows.append({"label": "bought_ins", "left": left, "right": right,
                 "changed": left != right})
    for group in ("rates", "recipe"):
        for key in sorted(snap_a.get(group, {})):
            left, right = snap_a[group][key], snap_b.get(group, {}).get(key)
            rows.append({"label": "%s.%s" % (group, key), "left": str(left),
                         "right": str(right), "changed": left != right})
    return rows


@app.get("/rates", response_class=HTMLResponse)
def edit_rates(request: Request):
    """Show the central material prices form."""
    try:
        state = materials.get_state()
        errors = []
    except materials.MaterialsError as exc:
        state = {"rates": dict(costing.DEFAULT_RATES), "updated_at": None,
                 "customized": False}
        errors = [str(exc)]
    return _render(
        "rates.html",
        {"request": request, "rates": state["rates"], "labels": costing.RATE_LABELS,
         "updated_at": state["updated_at"], "customized": state["customized"],
         "message": None, "errors": errors,
         "ai_on": muse_client.MuseConfig().configured},
    )


@app.post("/rates", response_class=HTMLResponse)
async def save_rates(request: Request):
    """Validate and persist updated material prices."""
    form = await request.form()
    try:
        state = materials.get_state()
    except materials.MaterialsError:
        state = {"rates": dict(costing.DEFAULT_RATES), "updated_at": None,
                 "customized": False}
    values, errors, shown = {}, [], dict(state["rates"])
    for key in costing.DEFAULT_RATES:
        text = (form.get("rate_" + key) or "").strip()
        if text == "":
            continue
        shown[key] = text
        try:
            values[key] = float(text)
        except ValueError:
            errors.append("%s is not a number." % costing.RATE_LABELS[key])
    message = None
    if errors:
        pass
    elif not values:
        message = "No changes - every field was blank, so current prices were kept."
        shown = dict(state["rates"])
    else:
        try:
            state = materials.update_rates(values)
            shown = dict(state["rates"])
            message = ("Material prices updated - new estimates will use them. "
                       "Saved estimates keep their own snapshots and are unchanged.")
        except materials.MaterialsError as exc:
            errors.append(str(exc))
    return _render(
        "rates.html",
        {"request": request, "rates": shown, "labels": costing.RATE_LABELS,
         "updated_at": state["updated_at"], "customized": state["customized"],
         "message": message, "errors": errors,
         "ai_on": muse_client.MuseConfig().configured},
    )


@app.get("/demo", response_class=HTMLResponse)
def demo_page(request: Request):
    cases = _demo_cases()
    for case in cases:
        case["drawing_url"] = "/demo-img/" + case.get("id", "")
    return _render(
        "demo.html",
        {"request": request, "cases": cases,
         "muse": muse_client.MuseConfig().summary()},
    )


@app.get("/demo-img/{case_id}")
def demo_image(case_id: str):
    case = _demo_case(case_id)
    if not case or not case.get("drawing"):
        return HTMLResponse("Demo drawing not found.", status_code=404)
    path = DEMO_DIR / case["drawing"]
    if not path.exists():
        return HTMLResponse("Demo drawing not found.", status_code=404)
    return FileResponse(str(path), media_type="image/png")


@app.post("/demo/extract/{case_id}", response_class=HTMLResponse)
async def demo_extract(request: Request, case_id: str):
    """Run the real extract pipeline on a fictional demo case."""
    case = _demo_case(case_id)
    if not case:
        return HTMLResponse("Demo case not found.", status_code=404)
    description = case.get("description", "")
    shape_hint = case.get("shape_hint", "auto")
    drawing_ref, model_bytes = "", None
    path = DEMO_DIR / (case.get("drawing") or "")
    if path.exists():
        data = path.read_bytes()
        drawing_ref = _store_bytes(data, ".png")
        model_bytes = data
    config = muse_client.MuseConfig()
    if not config.configured:
        shape_id = shape_hint if shape_hint in shapes.SHAPE_IDS else "panel"
        extraction = _blank_extraction(shape_id)
        ctx = _review_context(
            request, shape_id, extraction, description, drawing_ref, demo_ref=case_id,
            ai_notice="Demo running without AI (no MODEL_API_KEY). Fill the values manually, "
                      "then open the expected reference below to compare.")
        return _render("review.html", ctx)
    try:
        extraction = muse_client.extract_inputs(description, model_bytes, "image/png",
                                                shape_hint, config)
    except muse_client.MuseError as exc:
        shape_id = shape_hint if shape_hint in shapes.SHAPE_IDS else "panel"
        fallback = _blank_extraction(shape_id)
        ctx = _review_context(request, shape_id, fallback, description, drawing_ref,
                              demo_ref=case_id,
                              ai_error="Demo AI extraction failed (%s)." % exc.message)
        return _render("review.html", ctx)
    shape_id = extraction["shape"]
    if shape_id == "unknown":
        shape_id = shape_hint if shape_hint in shapes.SHAPE_IDS else "panel"
    ctx = _review_context(request, shape_id, extraction, description, drawing_ref,
                          demo_ref=case_id)
    return _render("review.html", ctx)


@app.post("/demo/compare")
def demo_compare():
    """Seed a fictional before/after revision pair, then show the comparison."""
    dims = {"length": 1200.0, "width": 800.0, "thickness": 5.0, "flange": 50.0}
    original = [
        {"field": "length", "value": 1200.0, "unit": "mm"},
        {"field": "width", "value": 800.0, "unit": "mm"},
        {"field": "thickness", "value": 5.0, "unit": "mm"},
        {"field": "flange", "value": 50.0, "unit": "mm"},
    ]
    current = _current_rates()
    try:
        calc_a = costing.calculate("panel", dims, qty=5, rates=current)
        calc_b = costing.calculate("panel", dims, qty=10,
                                   rates={"resin": round(current["resin"] * 1.1, 3)})
    except (shapes.ShapeError, costing.CostingError) as exc:
        return HTMLResponse("Demo comparison failed (%s)." % exc, status_code=500)
    base = {"label": "DEMO - panel before/after", "shape_id": "panel",
            "dims_original": original, "dims_mm": dims, "options": {},
            "description": "Fictional demo: same panel, revised quantity and resin rate.",
            "drawing": ""}
    snap_a = dict(base, qty=5, recipe=calc_a["recipe"], rates=calc_a["rates"], result=calc_a)
    try:
        saved = store.save_new(snap_a)
        snap_b = dict(base, qty=10, recipe=calc_b["recipe"], rates=calc_b["rates"], result=calc_b)
        rev_b = store.add_revision(saved["id"], snap_b)
    except store.StoreError as exc:
        return HTMLResponse("Demo comparison failed (%s)." % exc, status_code=500)
    return RedirectResponse("/compare?a=%s:1&b=%s:%d" % (saved["id"], saved["id"], rev_b),
                            status_code=303)


@app.get("/uploads/{name}")
def serve_upload(name: str):
    if not SAFE_NAME_RE.match(name):
        return HTMLResponse("Drawing not found.", status_code=404)
    path = UPLOAD_DIR / name
    if not path.exists():
        return HTMLResponse("Drawing not found.", status_code=404)
    media = "application/pdf" if name.endswith(".pdf") else "image/" + path.suffix.lstrip(".")
    if media == "image/jpg":
        media = "image/jpeg"
    return FileResponse(str(path), media_type=media)