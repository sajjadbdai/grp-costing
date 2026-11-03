# Drawing to Estimate — GFPF Fiberglass Costing

**Meta Global AI Developer Hackathon 2026 · Indie track · Theme: Build for Your World**

Live app: https://costing.arsharafin.com/ · Health/proof: https://costing.arsharafin.com/healthz

## The problem (firsthand)

I am the chief accountant at a fiberglass (GRP) factory in Bahrain. Every quote starts the
same way: a customer sends a drawing or a WhatsApp description — "2 metre panel, 5 mm thick,
with flange" — and someone re-derives the geometry, the material quantity, the resin, the
labour and the price by hand. It takes 30–60 minutes per item, it is done differently by
different people, and an arithmetic slip quietly becomes a wrong price. The expensive part
is not typing; it is **re-checking someone else's numbers**.

## What the app does

Upload a drawing (PNG/JPEG/PDF) or describe the part in words. The app:

1. **Interprets** the input with **Muse** (Meta Model API): shape type (panel / cylinder /
   reducer), dimensions, quantity, plus what is ambiguous or contradictory.
2. **Reviews with a human** — every extracted dimension is shown with its source, and the
   user confirms or corrects before any money is computed.
3. **Calculates deterministically** — geometry, material quantities and cost happen in plain
   Python (`shapes.py`, `units.py`, `costing.py`). The language model never does arithmetic.
4. **Compares and saves** — estimates can be compared side by side and stored for reuse.

Muse also **narrates** the result and answers follow-up questions, but the numbers come from
the engine. Without an API key the app still runs end to end in manual mode.

## Why Meta models, and how

- **Muse (Meta's model)** is the interpretation layer: it reads drawings and free-text
  descriptions and turns them into a structured shape + dimension proposal. The model is
  reached through an OpenAI-compatible endpoint, so base URL, model id and format are all
  configurable (`/healthz` shows exactly which one is live).
- **Muse Code** built this application: the FastAPI service, the deterministic costing
  engine, the templates and the test suite were written with it in the agent workflow.
- The model is called **server-side only** (key from environment, never logged, never sent
  to the browser), with a structured extraction schema and a single retry on soft failures.

## Technical depth

- FastAPI + Jinja templates, no frontend build step.
- Deterministic costing engine separated from the LLM — the audit trail is code, not a prompt.
- Drawing intake: JPEG/PNG/PDF with magic-byte sniffing, 10 MB cap, strict filename rules,
  PDF pages rasterised with PyMuPDF for the vision call.
- Contradiction handling: the model is allowed to say "unknown" or "conflict"; the UI asks.
- **Test suite included** (`tests/`) covering units, shapes, costing, store and the Muse client.
- Dockerised; runs behind nginx with a public health endpoint.

## Impact

A quote that took 30–60 minutes becomes a 5-minute review. More importantly, the factory
gets the same answer from every estimator, with the derivation visible — which is what a
quote actually needs to be defensible.

## Judging map

| Criterion | How this project answers it |
|---|---|
| Impact | Real factory, real quotations, real money; removes a 30–60 min manual step |
| Use of Meta AI tooling | Muse interprets every drawing/description; Muse Code built the app |
| Technical depth | LLM/engine separation, schema-guided extraction, PDF pipeline, test suite, Docker |
| Demo quality | Live public URL, one upload → review → priced estimate in under a minute |

## Demo video (3 minutes)

1. **0:00** — "This is how a quote starts in a fiberglass factory." Show the drawing.
2. **0:25** — Upload it → Muse extracts shape, dimensions, flags the ambiguity.
3. **1:00** — Correct one dimension in the review screen; show that the source of each value is visible.
4. **1:30** — Calculate → material, resin, labour and price, with the formula breakdown.
5. **2:10** — Compare two variants (5 mm vs 6 mm) side by side.
6. **2:40** — "Muse interprets, Python calculates, the estimator approves." Show the health
   endpoint proving the Meta model is live.

## Run it

```bash
pip install -r requirements.txt
MODEL_API_KEY=... MODEL_ID=meta-models/muse-spark-open MODEL_API_FORMAT=chat \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Contributors: **Mohammed Sajjad** (chief accountant, GFPF — problem owner, domain rules,
testing).
