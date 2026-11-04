# Hackathon build: Drawing to Estimate - AI for Fiberglass Manufacturers

## What changed

- New shape library: panel (original formula preserved), cylinder with
  optional ends, and open concentric reducer.
- Deterministic costing engine with recipe/rate validation, per-piece and
  batch totals, assumptions, exclusions and warnings on every result.
- Server-side Muse client (Meta Model API, default `muse-wonder-1.0`):
  drawing/description extraction with sources, clarification questions and
  plain-language explanations. Key from `MODEL_API_KEY`, never in the browser.
- Review workflow: drawing stays visible beside extracted values; every value
  shows its source (drawing / description / user / default); missing and
  conflicting inputs block calculation until confirmed.
- Units: mm/cm/m accepted, originals preserved, conversions shown, embedded
  vs selected unit mismatches flagged.
- JPG/PNG upload plus PDF first-page rendering.
- Save / revise / compare with immutable revision snapshots (inputs, rates,
  recipe, assumptions frozen per revision) and print stylesheets.
- Three fictional demo cases plus a one-click before/after comparison.
- Fixes: `/static` mount (stylesheet now loads), invalid-input guards.
- Docs: this file plus an updated README and 60 unit checks.

## Demo script (about 5 minutes)

1. Open `/demo`. Note AI status at the top (needs `MODEL_API_KEY`).
2. Run **Cover panel**: extraction fills length 1200, width 800, thickness 5,
   flange 50, qty 5. Review shows each source beside the drawing. Confirm and
   calculate: batch BD 68.731, BD 13.746 per piece. Save it.
3. Run **Water tank**: review flags missing thickness, approximate 1.2 m /
   1.5 m readings and the open-top question. Fill thickness 6 mm, confirm ends,
   calculate, save as a second estimate.
4. Run **Duct reducer**: review flags mixed mm/cm units, missing thickness and
   the unsupported end-flange request. Confirm values and calculate.
5. Press **Load comparison**: a fictional panel is costed at qty 5 vs qty 10
   with a resin rise; the compare page shows changed inputs highlighted and
   batch/per-piece deltas.
6. Open a saved estimate, change quantity or a rate, save as revision 2, show
   revision 1 unchanged, then print.

## Validation results (2026-10-31, this machine)

- Unit suite: 60/60 pass (`python -m unittest discover -s tests`).
- Live server smoke (keyless): 15/15 pass - home, CSS, legacy endpoint,
  manual extract, demo extract, calculate, invalid-input blocking, save,
  revise, revision immutability, compare, demo compare, health, PNG and PDF
  upload. Server stopped and smoke data removed afterwards.
- Hand-verified numbers (engine output matches independent hand calculation):
  - Legacy panel 675x675x4 flange 100 qty 1: total BD 8.454125625.
  - Demo A panel 1200x800x5 flange 50 qty 5: batch BD 68.730833, per pc 13.746167.
  - Demo B same panel qty 10, resin 1.045: batch BD 144.522469, per pc 14.452247.
  - Cylinder D1000 H2000 bottom-only: area 7.0685835 m2.
  - Reducer 600/400x500: lateral area 0.80095 m2.
- Live Muse extraction (`muse-wonder-1.0`, Responses API), checked against
  fixture expected values:
  - panel_complete: shape, qty 5 and all four dims exact; zero missing.
  - cylinder_ambiguous: shape, qty 2, 1.2 m / 1.5 m with units preserved;
    missing thickness and end covers; 3 ambiguities; 4 questions.
  - reducer_conflict: shape; 850 mm / 60 cm / 45 cm with original units;
    missing thickness, flange width, quantity; mixed-unit + flange + thickness
    ambiguities; 3 questions.
  - explain_estimate: repeats the given totals/exclusions without invention.
- Minor note: on the panel case the model cited "description" for values that
  also appear on the drawing; values were exact either way.

## Known limitations

- Live AI checked on 3 fictional cases only; no accuracy or time-saving
  percentage is claimed.
- PDF review uses page 1; multi-page drawing sets are not merged.
- `flange` means the panel border only; cylinder rims and reducer end rings
  are flagged as unsupported, not costed.
- Single-server JSON store, no login, no multi-user locking - fine for local
  demo, not for production.
- Rates are DEMO values; Docker build not re-tested here (no Docker engine).
- Estimates never claim structural suitability or certification.

## Pre-existing vs hackathon work

Already there: FastAPI+Jinja panel form, MVP costing formulas and demo rates,
CSS look, Dockerfile/compose and README assumptions.

Added for the hackathon: shape library (+cylinder, +reducer), costing engine
module, units module, Muse client + prompts, review/compare/save/revise flow,
upload + PDF handling, JSON revision store, demo cases + generated drawings,
print CSS, static-mount and validation fixes, 60 unit checks, live smoke
script (throwaway, not shipped), README rewrite and this file.

## Update (Nov 1-3, still in the event window)

- Dome/sphere take-off from diameters, GRP cabin mode, material-aware
  door detection (GRP unless aluminium/steel stated), automatic product
  naming, in-page AI price check with previous/new columns.
- Review UI rebuilt side-by-side with live totals and one-click Excel.
- Suite now 223 checks; fresh-install verified (clean venv, all green).