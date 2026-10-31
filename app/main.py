"""GFPF drawing-to-estimate web app.

Upload/Describe -> Review -> Calculate -> Compare/Save.
Legacy POST /estimate behaviour is preserved; all geometry and money go
through the deterministic engine; Muse only interprets and narrates.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import costing, muse_client, shapes, store, units

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
        entry = by_field.get(key, {})
        value = entry.get("value")
        unit = entry.get("unit") or "mm"
        source = entry.get("source") or "user"
        quote = entry.get("quote") or ""
        if key in raw:
            value = raw[key][0]
            unit = raw[key][1] or unit
            source = "user"
        text = "" if value is None else str(value)
        missing = field["required"] and (text.strip() == "")
        mm = None
        if text.strip():
            try:
                mm = units.parse_measurement(text, unit)["mm"]
            except units.UnitError:
                mm = None
        rows.append({"key": key, "label": field["label"], "required": field["required"],
                     "value": text, "unit": unit, "source": source, "quote": quote,
                     "missing": missing, "mm": mm})
    options = []
    for option in spec["options"]:
        key = option["key"]
        value = extraction.get("options", {}).get(key, option["default"])
        if key in raw:
            value = raw[key][0] == "yes"
        options.append({"key": key, "label": option["label"], "value": bool(value)})
    return rows, options


def _review_context(request, shape_id, extraction, description="", drawing=None,
                    demo_ref=None, ai_error=None, ai_notice=None, form_errors=None,
                    raw=None, recipe=None, rates=None, qty=None):
    rows, options = _review_rows(shape_id, extraction, raw)
    return {
        "request": request,
        "shape_id": shape_id,
        "shape_label": shapes.get_shape(shape_id)["label"],
        "shape_ids": shapes.SHAPE_IDS,
        "shape_labels": {sid: shapes.SHAPES[sid]["label"] for sid in shapes.SHAPE_IDS},
        "rows": rows,
        "options": options,
        "qty": qty if qty is not None else (extraction.get("quantity") or 1),
        "missing": extraction.get("missing", []),
        "ambiguities": extraction.get("ambiguities", []),
        "questions": extraction.get("questions", []),
        "notes": extraction.get("notes", []),
        "shape_evidence": extraction.get("shape_evidence", ""),
        "description": description,
        "drawing": drawing,
        "demo_ref": demo_ref,
        "demo_expected": _demo_expected(demo_ref),
        "recipe": recipe or dict(costing.DEFAULT_RECIPE),
        "rates": rates or dict(costing.DEFAULT_RATES),
        "ai_error": ai_error,
        "ai_notice": ai_notice,
        "form_errors": form_errors or [],
    }


def _parse_confirm(form, shape_id):
    """Parse the review confirm form; returns (inputs, warnings, errors, raw)."""
    spec = shapes.get_shape(shape_id)
    warnings, errors, raw = [], [], {}
    dims_original, dims_mm = [], {}
    for field in spec["fields"]:
        key = field["key"]
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
    try:
        qty = int(form.get("qty") or 1)
    except (TypeError, ValueError):
        errors.append("Quantity must be a whole number.")
        qty = 1
    recipe, rates = {}, {}
    for key in costing.DEFAULT_RECIPE:
        text = (form.get("recipe_" + key) or "").strip()
        try:
            recipe[key] = float(text) if text else costing.DEFAULT_RECIPE[key]
        except ValueError:
            errors.append("Recipe field %s is not a number." % key)
    for key in costing.DEFAULT_RATES:
        text = (form.get("rate_" + key) or "").strip()
        try:
            rates[key] = float(text) if text else costing.DEFAULT_RATES[key]
        except ValueError:
            errors.append("Rate field %s is not a number." % key)
    inputs = {"shape_id": shape_id, "dims_original": dims_original, "dims_mm": dims_mm,
              "options": options, "qty": qty, "recipe": recipe, "rates": rates,
              "description": form.get("description") or "", "drawing": form.get("drawing") or ""}
    return inputs, warnings, errors, raw


def _dims_display(shape_id, dims_original):
    labels = {f["key"]: f["label"] for f in shapes.get_shape(shape_id)["fields"]}
    display = []
    for entry in dims_original:
        try:
            mm = units.to_mm(entry["value"], entry["unit"])
        except (units.UnitError, TypeError, ValueError):
            mm = None
        display.append({"field": entry["field"], "label": labels.get(entry["field"], entry["field"]),
                        "value": entry["value"], "unit": entry["unit"], "mm": mm})
    return display

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
        {"request": request, "result": None, "rates": costing.DEFAULT_RATES,
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
    base = {"request": request, "result": None, "rates": costing.DEFAULT_RATES,
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
    if drawing is not None and drawing.filename:
        try:
            data = await drawing.read(MAX_UPLOAD_BYTES + 1)
            prepared = _prepare_drawing(drawing.filename, data)
        except UploadError as exc:
            return _render(
                "index.html",
                {"request": request, "result": None, "rates": costing.DEFAULT_RATES,
                 "muse": muse_client.MuseConfig().summary(), "pdf_ok": _pdf_available(),
                 "prefill": {"description": description, "shape_hint": shape_hint},
                 "legacy_error": "Upload problem: %s" % exc,
                 "exclusions": costing.EXCLUSIONS},
            )
        drawing_ref = prepared["display"]
        drawing_note = prepared["note"]
        model_bytes, model_mime = prepared["model_bytes"], prepared["model_mime"]
    config = muse_client.MuseConfig()
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
        ctx = _review_context(
            request, shape_id, extraction, description, drawing_ref,
            ai_notice="AI extraction is off (no MODEL_API_KEY on the server). "
                      "Enter the values manually below - nothing is lost.")
        return _render("review.html", ctx)
    try:
        extraction = muse_client.extract_inputs(
            description, model_bytes, model_mime, shape_hint, config)
    except muse_client.MuseError as exc:
        shape_id = shape_hint if shape_hint in shapes.SHAPE_IDS else "panel"
        fallback = _blank_extraction(shape_id)
        if drawing_note:
            fallback["notes"].append(drawing_note)
        ctx = _review_context(request, shape_id, fallback, description, drawing_ref,
                              ai_error="AI extraction failed (%s). Your description and drawing "
                                       "are kept - enter values manually." % exc.message)
        return _render("review.html", ctx)
    shape_id = extraction["shape"]
    if shape_id == "unknown":
        shape_id = shape_hint if shape_hint in shapes.SHAPE_IDS else "panel"
        extraction["notes"].append("Shape unclear; review started as '%s' - change it if needed."
                                  % shapes.SHAPES[shape_id]["label"])
    if drawing_note:
        extraction["notes"].append(drawing_note)
    ctx = _review_context(request, shape_id, extraction, description, drawing_ref)
    return _render("review.html", ctx)


@app.post("/review-shape", response_class=HTMLResponse)
async def review_shape(request: Request):
    """Re-render review rows for another shape, keeping overlapping values."""
    form = await request.form()
    shape_id = form.get("shape_id") or "panel"
    if shape_id not in shapes.SHAPE_IDS:
        shape_id = "panel"
    described = {
        "shape": shape_id, "shape_evidence": "", "quantity": form.get("qty") or 1,
        "dims": [], "options": {},
        "missing": [f["label"] for f in shapes.get_shape(shape_id)["fields"] if f["required"]],
        "ambiguities": [], "questions": [],
        "notes": ["Shape changed - re-check every value before calculating."],
    }
    raw = {}
    for key in list(shapes.required_fields(shape_id)) + ["flange"]:
        text = (form.get("dim_" + key) or "").strip()
        if text:
            raw[key] = (text, form.get("unit_" + key) or "mm")
    recipe = {k: form.get("recipe_" + k) or costing.DEFAULT_RECIPE[k]
              for k in costing.DEFAULT_RECIPE}
    rates = {k: form.get("rate_" + k) or costing.DEFAULT_RATES[k]
             for k in costing.DEFAULT_RATES}
    try:
        qty = int(form.get("qty") or 1)
    except (TypeError, ValueError):
        qty = 1
    ctx = _review_context(request, shape_id, described, form.get("description") or "",
                          form.get("drawing") or "", demo_ref=form.get("demo_ref") or None,
                          raw=raw, recipe=recipe, rates=rates, qty=qty)
    return _render("review.html", ctx)

@app.post("/calculate", response_class=HTMLResponse)
async def calculate(request: Request):
    """Confirmed review values -> deterministic estimate -> result page."""
    form = await request.form()
    shape_id = form.get("shape_id") or "panel"
    if shape_id not in shapes.SHAPE_IDS:
        shape_id = "panel"
    inputs, warnings, errors, raw = _parse_confirm(form, shape_id)
    if errors:
        described = _blank_extraction(shape_id, inputs["qty"])
        ctx = _review_context(request, shape_id, described, inputs["description"],
                              inputs["drawing"], demo_ref=form.get("demo_ref") or None,
                              form_errors=errors, raw=raw, recipe=inputs["recipe"],
                              rates=inputs["rates"], qty=inputs["qty"])
        return _render("review.html", ctx)
    try:
        calc = costing.calculate(shape_id, inputs["dims_mm"], inputs["qty"],
                                 inputs["recipe"], inputs["rates"], inputs["options"])
    except (shapes.ShapeError, costing.CostingError) as exc:
        described = _blank_extraction(shape_id, inputs["qty"])
        ctx = _review_context(request, shape_id, described, inputs["description"],
                              inputs["drawing"], demo_ref=form.get("demo_ref") or None,
                              form_errors=[str(exc)], raw=raw, recipe=inputs["recipe"],
                              rates=inputs["rates"], qty=inputs["qty"])
        return _render("review.html", ctx)
    warnings = warnings + calc["warnings"]
    ctx = {
        "request": request,
        "inputs": inputs,
        "inputs_json": json.dumps(inputs),
        "dims_display": _dims_display(shape_id, inputs["dims_original"]),
        "result": calc,
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
    ctx = _review_context(request, shape_id, described, inputs.get("description", ""),
                          inputs.get("drawing", ""), demo_ref=form.get("demo_ref") or None,
                          raw=raw, recipe=inputs.get("recipe"), rates=inputs.get("rates"),
                          qty=inputs.get("qty", 1))
    return _render("review.html", ctx)


@app.post("/explain", response_class=HTMLResponse)
async def explain(request: Request):
    inputs_json = (await request.form()).get("inputs_json") or "{}"
    try:
        inputs = json.loads(inputs_json)
        calc = costing.calculate(inputs["shape_id"], inputs["dims_mm"], inputs["qty"],
                                 inputs["recipe"], inputs["rates"], inputs.get("options"))
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
         "result": calc, "warnings": calc["warnings"], "explanation": explanation,
         "ai_error": ai_error, "ai_available": muse_client.MuseConfig().configured},
    )


def _estimate_summary(inputs, calc):
    lines = [
        "Estimate for %s, batch of %d." % (calc["shape_label"], calc["qty"]),
        "Area %.4f m2; laminate %.2f kg per piece." % (calc["area_m2"], calc["laminate_kg"]),
        "Materials per piece: resin %.2f kg, fibre %.2f kg, MEKP %.3f kg."
        % (calc["resin_kg"], calc["fiber_kg"], calc["mekp_kg"]),
        "Cost: materials BD %.3f + labour BD %.3f per piece; batch BD %.3f + overhead BD %.3f."
        % (calc["material_bd"], calc["labour_bd"], calc["batch_bd"], calc["overhead_bd"]),
        "Total BD %.3f; cost per piece BD %.3f."
        % (calc["total_bd"], calc["per_piece_bd"]),
        "Exclusions: " + "; ".join(calc["exclusions"]) + ".",
    ]
    return "\n".join(lines)


@app.post("/save")
async def save_estimate(request: Request, label: str = Form(""), inputs_json: str = Form("{}")):
    try:
        inputs = json.loads(inputs_json)
        calc = costing.calculate(inputs["shape_id"], inputs["dims_mm"], inputs["qty"],
                                 inputs["recipe"], inputs["rates"], inputs.get("options"))
    except (ValueError, KeyError) as exc:
        return HTMLResponse("Could not save (%s)." % exc, status_code=400)
    record = {
        "label": label.strip() or "Untitled estimate",
        "shape_id": inputs["shape_id"],
        "dims_original": inputs["dims_original"],
        "dims_mm": inputs["dims_mm"],
        "options": inputs.get("options", {}),
        "qty": inputs["qty"],
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

@app.get("/estimates/{estimate_id}", response_class=HTMLResponse)
def estimate_detail(request: Request, estimate_id: str, rev: str = ""):
    try:
        meta, revision = store.get(estimate_id, int(rev) if rev else None)
    except (store.StoreError, ValueError) as exc:
        return HTMLResponse("Estimate not found (%s)." % exc, status_code=404)
    snapshot = revision["snapshot"]
    calc = snapshot["result"]
    try:
        others = store.list_all()
    except store.StoreError:
        others = []
    return _render(
        "detail.html",
        {"request": request, "meta": meta, "rev": revision["rev"],
         "saved_at": revision["saved_at"], "snapshot": snapshot, "result": calc,
         "dims_display": _dims_display(snapshot["shape_id"], snapshot["dims_original"]),
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
        calc = costing.calculate(shape_id, inputs["dims_mm"], inputs["qty"],
                                 inputs["recipe"], inputs["rates"], inputs["options"])
    except (shapes.ShapeError, costing.CostingError) as exc:
        return HTMLResponse("Cannot revise (%s)." % exc, status_code=400)
    snapshot = {
        "label": meta["label"],
        "shape_id": shape_id,
        "dims_original": inputs["dims_original"],
        "dims_mm": inputs["dims_mm"],
        "options": inputs.get("options", {}),
        "qty": inputs["qty"],
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
    for group in ("rates", "recipe"):
        for key in sorted(snap_a.get(group, {})):
            left, right = snap_a[group][key], snap_b.get(group, {}).get(key)
            rows.append({"label": "%s.%s" % (group, key), "left": str(left),
                         "right": str(right), "changed": left != right})
    return rows


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
    try:
        calc_a = costing.calculate("panel", dims, qty=5)
        calc_b = costing.calculate("panel", dims, qty=10, rates={"resin": 1.045})
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