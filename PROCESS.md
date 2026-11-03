# GRP Manufacturing Process Notes

Research basis for the laminate schedules, mould options and supports in this
app. Resin uptake, product recipes and prices follow the factory material
catalogue (cross-checked against the FAO boat-building manual and trade
estimating guides); factory trials should confirm them.

## Process flow

1. **Plug** - a full-size model of the part (timber, foam, filler), faired and
   polished. Needed once per new shape.
2. **Mould** - release the plug (5-7 coats parting wax plus PVA film), spray
   tooling gelcoat ~0.6 mm, then lay 8-10 plies of CSM 450 for a rigid
   ~10 mm mould shell. Back large moulds with a steel/plywood frame.
3. **Part lay-up** - wax + PVA the mould, spray product gelcoat 0.5 mm
   (~0.7 kg/m2), then wet out the schedule ply by ply: CSM skin against the
   gelcoat, woven roving always sandwiched between CSM, max 4-5 plies of
   CSM 450 per session so exotherm stays safe.
4. **Cure, demould, trim** - room-temperature cure, release, trim edges, cut
   openings, bond baffles/lids/flanges.
5. **Fit-out** - fit plywood backing pads, steel frames, brackets and
   fasteners; polish and dispatch.

## Standard materials and consumption (per m2, before wastage)

| Material | Resin uptake | Cured ply |
|---|---|---|
| CSM 300 | 0.66 kg (2.2:1) | ~0.8 mm |
| CSM 450 | 0.99 kg (2.2:1) | ~1.1 mm |
| CSM 600 | 1.38 kg (2.3:1) | ~1.4 mm |
| Woven roving 600 | 0.78 kg (1.3:1) | ~0.8 mm |
| Woven roving 800 | 1.04 kg (1.3:1) | ~1.0 mm |
| Gelcoat film | 0.55-0.65 kg (per product) | ~0.5 mm |
| MEKP catalyst | 1.5% of resin + gelcoat mass | - |
| Pigment paste | % of gelcoat mass (recipe) | - |
| Surface tissue | 1 m2 per m2 behind outside gelcoat | - |
| ISO skin coat | 15% of resin behind gelcoat (GP jobs) | - |
| Consumables | 5% of GRP materials | - |
| Bonding paste | kg per piece entered on review | - |

Resin grades: GP/ortho for general work, isophthalic for water tanks, vinyl
ester for chemical duty. Machine hours and hardware/fittings are costed per
piece alongside labour.

## Standard products and schedules in the app

| Product | Shape | Schedule | Lays as |
|---|---|---|---|
| Flat panel / plate | panel | Classic % or Structural panel | CSM450 + CSM300 + WR600 + CSM450 (~4.3 mm) |
| Water tank standard | box / cylinder | Tank medium | CSM450 + CSM300 + 3xWR600 + CSM450 (~5.9 mm) |
| Water tank heavy / sewerage | box / cylinder | Tank heavy | CSM450 + CSM300 + 3xWR600 + 2xCSM600 + 3xWR600 + CSM450 (~11.1 mm) |
| Enclosure, cabinet, kiosk | box | Enclosure | CSM450 + 2xCSM300 + WR600 + CSM450 (~5.1 mm) |
| Boat hull, guard | custom area | Boat hull | CSM300 + CSM450 + WR800 + CSM450 + WR800 + CSM450 (~6.6 mm) |
| Light cover, dust bin | panel | Light cover | CSM450 + CSM300 + CSM450 (~3.5 mm) |

Boat hulls use a measured surface area (from mould, plug or drawings) because
no simple geometry fits a hull. The app warns when the entered target
thickness is more than 15% off the selected schedule.

## Mould: have vs need

- **Have mould** - no mould cost; the estimate covers the part only.
- **Need new mould** - enter the full mould cost (plug, wax/PVA, tooling
  gelcoat, mould laminate, stiffening frame and labour) plus its expected
  life in pieces. Each piece carries cost / life pieces (blank life means
  this batch), and overhead applies on top like any manufacturing cost.

## Plywood and steel supports

Big or loaded items get 18 mm marine-plywood backing/frames (charged per m2
per piece) and mild-steel frames or brackets (charged per kg per piece).
Enter zero when the laminate is self-supporting.

## Labour estimating

Labour hours default from workshop-typical output (single worker): 0.5 hr +
0.10 hr/m2 mould prep, gelcoat at 20 m2/hr, wet-out at 12 ply-m2/hr, and
0.5 hr + 0.15 hr/m2 demould/trim/finish. A 1280x3000 tank (~13.4 m2,
6 plies) estimates ~11.7 hr. The review page pre-fills this and shows a
note; overwrite it with the shop's known time. Machine hours stay manual.

## Bought-in items and openings

Doors, windows, lights, switches, sockets, DB and AC are read from the
drawing text and description, priced from the default book, and shown on
the review page for confirmation. Door/window openings deduct from the
shell area for materials. Change any qty, price or opening before
calculating; the Excel export keeps them as editable yellow cells.
A door with no stated material is listed as a GRP door; aluminium or
steel/SS appears only when named next to the door mention.

## Fitted cabins (automatic cabin mode)

When the drawing shows a door plus windows, the review starts as a GRP
cabin: sandwich take-off (outer 3xCSM450 skin, inner 2xCSM450 skin on PU
foam, heavy roof on foam, heavy floor on plywood, plus cornice, plinth and
one rain hood per opening), per-skin opening deductions, cabin assembly
labour in operations (mould prep, lamination, cores/assembly, trim,
finishing, door/window fixing, electrical, QC), estimator allowance lots
(cables, AC installation, sealant/fixings), job quantity and overall dims
from the title block, and cabin commercial defaults (overhead 15%,
margin 20%, VAT 10%, transport BD 45/pc, new mould BD 600, bonding paste
BD 12, pigment 8%). Every value stays editable on review; switching the
shape back to a plain box restores single-skin costing.

Delivery, packing/installation and testing are charged per piece and
carry overhead like any direct cost, so the result page, PDF and Excel
agree on multi-unit jobs.

## Drawing scan (PDF text and image transcription)

The review opens with a Drawing scan section: where the readings came
from (PDF text, AI vision transcription, or description only), overall
and internal size, job quantity, fittings/electrical count, openings,
colors/finishes and support mentions. PDFs are read from their text
layer; photos and screenshots - which have no text layer - are
transcribed by the vision model first, then interpreted by the same
deterministic rules, so both upload types detect the same items. The
scanned text is shown for verification; thin scans advise uploading the
original PDF. Bought-in default rates are internet-approximate Bahrain
supply prices (Nov 2026) - confirm with supplier quotes.

Round products (domes, spheres, tanks) state diameters instead of LxWxH,
so the scan reports internal/external diameters, GRP skin thicknesses,
insulation and steel support parts with counts; dims stay manual because
one drawing can carry several products (dome #1, dome #2, sphere).

The review prefills the Product name from the drawing title block (a
DETAILS OF line, else the head of a QTY title line, else the filename);
it stays editable and flows into the result, PDF, Excel and saved copy.

Domes use the spherical-cap surface 2*pi*R*h from base diameter and rise
(hemisphere = rise of half the diameter); spheres use 4*pi*R^2. Giving
the inner skin diameter adds the inner sandwich skin on PU foam board.
Dome skins default to paint finish (no gelcoat) per the shop drawings.

## Answering assumptions, including exclusions

Stiffeners, nozzles and rim flanges are costed through the extra laminate
area (m2 per piece), using the same schedule as the shell. Paint/topcoat
(0.15 kg/m2), delivery, testing, margin % and tax % are optional per
estimate: anything entered moves from the excluded list into the totals
(cost total, then selling price, then grand total with tax).
