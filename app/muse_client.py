"""Server-side Meta Model API client (Muse).

All API calls stay on the server. The key comes only from the MODEL_API_KEY
environment variable and is never logged, never sent to the browser, and
never stored in estimates. Geometry and money stay in deterministic code;
Muse only interprets text/drawings and narrates results.

Request shapes follow Meta's documented Responses / Chat Completions
formats (base https://api.meta.ai/v1). Payloads stay minimal and every
call degrades gracefully: a 400 retries once without structured-output
hints, and any failure raises MuseError with the user's work preserved
so the app can fall back to manual estimation.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-wonder-1.0"

SOURCES = ("drawing", "description", "user", "default")
DIM_FIELDS = ("length", "width", "thickness", "flange", "diameter", "height", "d_large",
              "d_small", "area", "diameter_inner")
AREA_UNITS = ("m2", "m²", "sqm", "sq m", "sq.m", "sq.m.")
SHAPE_IDS = ("panel", "cylinder", "reducer", "box", "cabin", "dome",
               "sphere", "custom", "unknown")

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "shape": {"type": "string",
                  "enum": ["panel", "cylinder", "reducer", "box", "cabin",
                          "dome", "sphere", "custom", "unknown"]},
        "shape_evidence": {"type": "string"},
        "quantity": {"type": ["integer", "null"]},
        "dims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {"type": ["number", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "source": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["field", "source"],
            },
        },
        "options": {"type": "object"},
        "missing": {"type": "array", "items": {"type": "string"}},
        "ambiguities": {"type": "array", "items": {"type": "string"}},
        "questions": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["shape", "dims", "missing", "ambiguities", "questions"],
}

EXTRACTION_SYSTEM = """You are the estimation assistant of a small fiberglass (GRP) factory. \
Read the customer description and optional drawing, then propose product values for costing.

Shapes and their dimension fields:
- panel: length, width, thickness, flange (flange = all-round planar border width, 0 if none)
- cylinder: diameter (outer), height (axial length), thickness; options closed_bottom/closed_top true/false
- reducer: d_large, d_small, height (axial), thickness (concentric cone, open ends)
- box: length, width, height, thickness (rectangular tank, chamber or enclosure);
- cabin: overall length, width, height, outer skin target (security cabins and
  fitted kiosks with door, windows and wiring - prefer over box when fitted);
- dome: diameter (outer base), height (rise), thickness (spherical caps and
  hemispheres - rise is half the diameter for a true hemisphere);
- sphere: diameter (outer), thickness (full ornamental balls);
  option open_top true/false (lid included when false)
- custom: area (measured surface in m2, for boat hulls and free-form parts) plus
  thickness; use only when the customer states a measured area - never compute it

Strict rules:
1. Only report values supported by the description or drawing. Never invent dimensions.
2. Never estimate real dimensions from image proportions or guess scale. If a value is not \
readable, list it under "missing" instead.
3. Preserve original units (mm, cm or m) exactly as written; never silently convert.
4. For every dim give "source": "drawing" (visible annotation), "description" (quoted text), \
"user" (user typed it separately) or "default" (explicit factory default, value 0 flange only).
5. Put short evidence in "quote": the annotation text or quoted description fragment.
6. Flag conflicts in "ambiguities": mixed units for one dimension, unclear thickness, unclear \
flange meaning, unreadable annotations, swapped diameters.
7. Ask at most 4 short clarification questions covering every "missing" item.
8. Reply with JSON only, matching the requested schema. No prose outside the JSON.
9. Extract EVERY stated dimension - an empty dims list is only valid when the
customer gave no usable numbers at all.

Example: description "GRP cover panel 1200 x 800 mm, 5 mm thick, 50 mm flange,
qty 5" with a matching drawing must produce shape "panel", quantity 5, and four
dims entries: length 1200 mm, width 800 mm, thickness 5 mm, flange 50 mm, each
with its source and quote, plus empty missing/ambiguities/questions lists."""

EXPLAIN_SYSTEM = """You explain a fiberglass factory cost estimate in plain, short language for \
factory staff. Use ONLY the numbers given. Do not invent rates or quantities, do not claim \
structural suitability, pressure ratings or certification. End with the exclusions line given."""

TRANSCRIBE_SYSTEM = """You read engineering drawings for a fiberglass factory estimator. Copy \
out ALL text visible in the drawing EXACTLY as printed: the title block (project, \
drawing number, overall size, internal size, quantity, colors, finishes, materials), \
every legend and symbol-table row (symbol, description, reference, quantity), the \
label on every view, every dimension annotation, and all notes. Write one item per \
line. Copy numbers, units and quantities exactly as shown; never invent text you \
cannot read - write "[unreadable]" for illegible words. Plain text only: no JSON, \
no markdown, no commentary."""


class MuseError(Exception):
    """User-safe model failure (never carries the API key)."""

    def __init__(self, message, http_status=None):
        super().__init__(message)
        self.message = message
        self.http_status = http_status


class MuseConfig:
    def __init__(self):
        self.base_url = os.environ.get("MODEL_API_BASE", DEFAULT_BASE_URL).rstrip("/")
        self.api_key = os.environ.get("MODEL_API_KEY", "")
        self.model = os.environ.get("MODEL_ID", DEFAULT_MODEL)
        self.api_format = os.environ.get("MODEL_API_FORMAT", "responses").strip().lower()
        try:
            self.timeout_s = float(os.environ.get("MODEL_TIMEOUT_S", "90"))
        except ValueError:
            self.timeout_s = 90.0
        try:
            self.max_image_mb = float(os.environ.get("MODEL_MAX_IMAGE_MB", "8"))
        except ValueError:
            self.max_image_mb = 8.0
        self.reasoning_effort = os.environ.get("MODEL_REASONING_EFFORT", "low")

    @property
    def configured(self):
        return bool(self.api_key)

    def summary(self):
        """Key-free status for health checks and the UI."""
        return {
            "configured": self.configured,
            "base_url": self.base_url,
            "model": self.model,
            "api_format": self.api_format,
            "reasoning_effort": self.reasoning_effort,
        }


def _data_url(image_bytes, image_mime):
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return "data:%s;base64,%s" % (image_mime, encoded)


def build_responses_payload(model, system_text, user_text, image=None, schema=None,
                            temperature=None, reasoning_effort=None, max_tokens=16000):
    """Native Responses shape: typed input blocks + text.format schema."""
    content = [{"type": "input_text", "text": user_text}]
    if image is not None:
        content.append({"type": "input_image", "image_url": image, "detail": "high"})
    payload = {
        "model": model,
        "instructions": system_text,
        "input": [{"role": "user", "content": content}],
        "max_output_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    if schema is not None:
        payload["text"] = {
            "format": {"type": "json_schema", "name": "extraction", "strict": False, "schema": schema}
        }
    return payload


def build_chat_payload(model, system_text, user_text, image=None, schema=None,
                       temperature=None, max_tokens=16000):
    """Chat Completions fallback shape (kept minimal and robust)."""
    user_content = [{"type": "text", "text": user_text}]
    if image is not None:
        user_content.append({"type": "image_url", "image_url": {"url": image}})
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "extraction", "strict": False, "schema": schema},
        }
    return payload


def _post(url, payload, api_key, timeout_s):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            detail = ""
        raise MuseError(
            "Model API error (HTTP %s): %s" % (exc.code, detail or exc.reason),
            http_status=exc.code,
        )
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        raise MuseError("Model API unreachable: %s" % exc)
    try:
        return json.loads(raw)
    except ValueError:
        raise MuseError("Model API returned an unexpected response.")


def _post_with_retry(url, payload, api_key, timeout_s):
    """One retry on transient failures; no retry on client errors."""
    try:
        return _post(url, payload, api_key, timeout_s)
    except MuseError as exc:
        transient = exc.http_status is None or (exc.http_status is not None and exc.http_status >= 500)
        if not transient:
            raise
        time.sleep(2)
        return _post(url, payload, api_key, timeout_s)


def _collect_text(node, found):
    if isinstance(node, dict):
        for key in ("output_text", "text"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                found.append(value)
        content = node.get("content")
        if isinstance(content, str) and content.strip():
            found.append(content)
        for key in ("output", "content", "message", "choices", "data", "parts"):
            if key in node:
                _collect_text(node[key], found)
    elif isinstance(node, list):
        for item in node:
            _collect_text(item, found)


def extract_output_text(data):
    """Best-effort text pull from Responses- or Chat-shaped replies."""
    found = []
    _collect_text(data, found)
    return "\n".join(found)[:20000]


_FENCE_RE = re.compile(r"^```[A-Za-z]*\s*\n(.*?)\n```\s*$", re.DOTALL)


def extract_json(text):
    """Parse JSON from a model reply, tolerating fences and prose."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise MuseError("The model returned an empty reply.")
    match = _FENCE_RE.match(cleaned)
    if match:
        cleaned = match.group(1).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except ValueError:
            pass
    raise MuseError("The model reply was not usable data. Nothing was calculated.")


def _call(config, system_text, user_text, image=None, schema=None, max_tokens=16000,
          temperature=None, reasoning_effort=None):
    if not config.configured:
        raise MuseError("AI is not configured: set the MODEL_API_KEY environment variable.")
    is_chat = config.api_format in ("chat", "chat_completions", "chat-completions")
    if is_chat:
        url = config.base_url + "/chat/completions"
        payload = build_chat_payload(config.model, system_text, user_text, image, schema,
                                     max_tokens=max_tokens, temperature=temperature)
    else:
        url = config.base_url + "/responses"
        payload = build_responses_payload(config.model, system_text, user_text, image, schema,
                                          max_tokens=max_tokens, temperature=temperature,
                                          reasoning_effort=reasoning_effort)
    try:
        data = _post_with_retry(url, payload, config.api_key, config.timeout_s)
    except MuseError as exc:
        if exc.http_status == 400 and (schema is not None or temperature is not None
                                       or reasoning_effort is not None):
            if is_chat:
                minimal = build_chat_payload(config.model, system_text, user_text, image,
                                             None, max_tokens=max_tokens)
            else:
                minimal = build_responses_payload(config.model, system_text, user_text, image,
                                                  None, max_tokens=max_tokens)
            data = _post_with_retry(url, minimal, config.api_key, config.timeout_s)
        else:
            raise
    if isinstance(data, dict):
        status = data.get("status")
        if status is not None and status != "completed" and not extract_output_text(data):
            reason = (data.get("incomplete_details") or {}).get("reason", status)
            raise MuseError("The model stopped early (%s); nothing was calculated." % reason)
        choices = data.get("choices") or []
        if choices and choices[0].get("finish_reason") not in (None, "stop"):
            if not extract_output_text(data):
                raise MuseError("The model stopped early (%s); nothing was calculated."
                                % choices[0].get("finish_reason"))
    return data


def _string_list(value, limit=10, chars=500):
    items = value if isinstance(value, list) else []
    return [str(item)[:chars] for item in items[:limit] if str(item).strip()]


def normalize_extraction(raw, shape_hint="auto"):
    """Coerce a raw model reply into the review model. Never raises."""
    notes = []
    shape = str((raw or {}).get("shape", "unknown")).strip().lower()
    if shape not in ("panel", "cylinder", "reducer", "box", "cabin", "dome",
                      "sphere", "custom"):
        if shape_hint in ("panel", "cylinder", "reducer", "box", "cabin",
                           "dome", "sphere", "custom"):
            notes.append("Shape unclear; using your selected shape '%s'." % shape_hint)
            shape = shape_hint
        else:
            shape = "unknown"
    dims = []
    for entry in (raw or {}).get("dims", []) or []:
        if not isinstance(entry, dict):
            continue
        field = str(entry.get("field", "")).strip()
        if field not in DIM_FIELDS:
            notes.append("Ignored unknown field %r." % field)
            continue
        try:
            value = float(entry.get("value")) if entry.get("value") is not None else None
        except (TypeError, ValueError):
            value = None
        if value is not None and value <= 0:
            notes.append("Rejected non-positive value for %s." % field)
            value = None
        unit = str(entry.get("unit", "") or "").strip().lower()
        if field == "area":
            if unit in AREA_UNITS:
                unit = "m2"
            else:
                if entry.get("unit") not in (None, ""):
                    notes.append("Unknown unit %r for %s; assumed m2."
                                 % (entry.get("unit"), field))
                unit = "m2" if value is not None else None
        elif unit not in ("mm", "cm", "m"):
            if entry.get("unit") not in (None, ""):
                notes.append("Unknown unit %r for %s; assumed mm." % (entry.get("unit"), field))
            unit = "mm" if value is not None else None
        source = str(entry.get("source", "") or "").strip().lower()
        if source not in SOURCES:
            source = "description"
        dims.append(
            {
                "field": field,
                "value": value,
                "unit": unit,
                "source": source,
                "quote": str(entry.get("quote", "") or "")[:300],
            }
        )
    options = {}
    for key, value in (((raw or {}).get("options")) or {}).items():
        text = str(value).strip().lower()
        if text in ("true", "yes", "closed", "1", "on"):
            options[key] = True
        elif text in ("false", "no", "open", "0", "off"):
            options[key] = False
    quantity = (raw or {}).get("quantity")
    try:
        quantity = int(quantity) if quantity is not None else None
    except (TypeError, ValueError):
        quantity = None
    if quantity is not None and quantity < 1:
        quantity = None
    return {
        "shape": shape,
        "shape_evidence": str((raw or {}).get("shape_evidence", "") or "")[:500],
        "quantity": quantity,
        "dims": dims,
        "options": options,
        "missing": _string_list((raw or {}).get("missing")),
        "ambiguities": _string_list((raw or {}).get("ambiguities")),
        "questions": _string_list((raw or {}).get("questions"), limit=4),
        "notes": _string_list((raw or {}).get("notes")) + notes,
    }


def extract_inputs(description, image_bytes=None, image_mime=None, shape_hint="auto", config=None):
    """Interpret a description/drawing into normalized review values."""
    config = config or MuseConfig()
    image = None
    if image_bytes:
        limit = config.max_image_mb * 1024 * 1024
        if len(image_bytes) > limit:
            raise MuseError(
                "The drawing is larger than %.0f MB; please upload a smaller image."
                % config.max_image_mb
            )
        image = _data_url(image_bytes, image_mime or "image/jpeg")
    user_text = "Customer description:\n%s\n" % (description.strip() or "(no description)")
    user_text += "Shape hint: %s\n" % shape_hint
    user_text += "Drawing attached: %s\n" % ("yes" if image else "no")
    user_text += "Return the extraction JSON now."
    data = _call(config, EXTRACTION_SYSTEM, user_text, image, EXTRACTION_SCHEMA,
                 temperature=0.0, reasoning_effort=config.reasoning_effort)
    return normalize_extraction(extract_json(extract_output_text(data)), shape_hint)


def transcribe_drawing(image_bytes, image_mime=None, description="", config=None):
    """OCR-style transcription of all visible drawing text.

    Used when an upload has no extractable text layer (photos and
    screenshots). The deterministic schedule reader - not the model -
    interprets the transcription, so detection stays testable.
    """
    config = config or MuseConfig()
    if not image_bytes:
        raise MuseError("No drawing image to transcribe.")
    limit = config.max_image_mb * 1024 * 1024
    if len(image_bytes) > limit:
        raise MuseError(
            "The drawing is larger than %.0f MB; please upload a smaller image."
            % config.max_image_mb
        )
    user_text = "Transcribe this drawing now.\n"
    if (description or "").strip():
        user_text += "Customer description for context:\n%s\n" % description.strip()
    data = _call(config, TRANSCRIBE_SYSTEM, user_text,
                 _data_url(image_bytes, image_mime or "image/jpeg"), None,
                 temperature=0.0, reasoning_effort=config.reasoning_effort)
    text = extract_output_text(data).strip()
    if not text:
        raise MuseError("The model returned an empty transcription.")
    return text[:8000]


def explain_estimate(summary_text, config=None):
    """Narrate confirmed numbers in plain factory language."""
    config = config or MuseConfig()
    data = _call(config, EXPLAIN_SYSTEM, summary_text, None, None, max_tokens=4000)
    text = extract_output_text(data).strip()
    if not text:
        raise MuseError("The model returned an empty explanation.")
    return text[:3000]


PRICES_SCHEMA = {
    "type": "object",
    "properties": {
        "prices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "price": {"type": ["number", "null"]},
                    "note": {"type": "string"},
                },
                "required": ["key", "price"],
            },
        },
    },
    "required": ["prices"],
}

PRICES_SYSTEM = """You are a procurement price database for a fiberglass (GRP) factory in \
Bahrain. For EACH rate-book line, give a NUMERIC best-estimate typical 2025-2026 Gulf market \
price in Bahraini dinars (BD) per the stated unit, based on supplier listings and factory \
prices you know. Common materials (resin, fiberglass, catalyst, labour, steel, plywood) MUST \
have numeric prices - use null ONLY for an item you genuinely have no price knowledge of. \
Each note states the basis in under 12 words (e.g. "Gulf 2025 industrial"). Reply with JSON \
only, matching the requested schema. No prose outside the JSON."""


def suggest_prices(items, config=None):
    """Today's market prices for rate-book items from the model.

    items: sequence of (key, label) with the unit in the label. Returns
    {key: {"price": float|None, "note": str}} for known keys only; keys
    the model skips or mangles are simply absent. Raises MuseError when
    the key is missing or the reply has no usable JSON.
    """
    config = config or MuseConfig()
    keys = [key for key, _ in items]
    lines = ["%s | %s" % (key, label) for key, label in items]
    user_text = ("Rate book (key | material with unit):\n" + "\n".join(lines)
                 + "\nReturn the prices JSON now.")
    data = _call(config, PRICES_SYSTEM, user_text, None, PRICES_SCHEMA,
                 max_tokens=4000, temperature=0.0,
                 reasoning_effort=config.reasoning_effort)
    raw = extract_json(extract_output_text(data))
    entries = raw.get("prices") if isinstance(raw, dict) else None
    found = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if key not in keys or key in found:
            continue
        price = entry.get("price")
        if price is not None:
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            if price < 0:
                continue
        found[key] = {"price": price, "note": str(entry.get("note") or "")[:200]}
    return found