"""Detailed Excel costing workbook (openpyxl).

One-click export matching the standard 3-sheet costed format: Costing,
Inputs and Take-off, with live Excel formulas so the user can review and
change quantities and prices in Excel and watch the totals recalculate.

Yellow cells are the estimates to confirm; blue headers are structure.
"""

from __future__ import annotations

from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook

from . import costing, layup as layups

HDR = PatternFill("solid", fgColor="1F4E78")
SUB = PatternFill("solid", fgColor="DDEBF7")
TOT = PatternFill("solid", fgColor="FCE4D6")
EST = PatternFill("solid", fgColor="FFFF00")
WHITE_BOLD = Font(bold=True, color="FFFFFF")
BOLD = Font(bold=True)

MONEY = '#,##0.000;(#,##0.000);-'
QTY2 = '#,##0.00;(#,##0.00);-'
PCT1 = '0.0%;(0.0%);-'
INT = '0'

MAT_START = 10
MATERIALS = [
    ("CSM 300 g/m2", "csm300", "kg"),
    ("CSM 450 g/m2", "csm450", "kg"),
    ("CSM 600 g/m2", "csm600", "kg"),
    ("Woven roving 600 g/m2", "wr600", "kg"),
    ("Woven roving 800 g/m2", "wr800", "kg"),
    ("Fiberglass generic (classic)", "fiber", "kg"),
    ("GP polyester resin", "resin", "kg"),
    ("Isophthalic resin", "resin_iso", "kg"),
    ("Vinyl ester resin", "resin_ve", "kg"),
    ("Gelcoat", "gelcoat", "kg"),
    ("Surface tissue 30 g/m2", "tissue", "m2"),
    ("MEKP catalyst", "mekp", "kg"),
    ("Pigment paste", "pigment", "kg"),
    ("Paint / topcoat", "paint", "kg"),
    ("Bonding paste / filler", "paste", "kg"),
    ("Marine plywood 18 mm", "plywood", "m2"),
    ("Mild steel", "steel", "kg"),
    ("PU foam board 20 mm", "foam", "m2"),
]
N_MATS = len(MATERIALS)
RULE_ROWS = 12
LR = MAT_START + N_MATS + 1  # laminate rules header
CR = LR + 1 + RULE_ROWS + 1  # commercial header


def _hdr(ws, row, values):
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.fill = HDR
        cell.font = WHITE_BOLD


def _sub(ws, row, col, value, number_format="General"):
    cell = ws.cell(row=row, column=col, value=value)
    cell.fill = SUB
    cell.font = BOLD
    cell.number_format = number_format
    return cell


def _tot(ws, row, col, value, number_format="General"):
    cell = ws.cell(row=row, column=col, value=value)
    cell.fill = TOT
    cell.font = BOLD
    cell.number_format = number_format
    return cell


def _est(cell, number_format="General"):
    cell.fill = EST
    cell.number_format = number_format
    return cell


def _widths(ws, widths):
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width


def _schedule_avgs(layup, calc=None):
    """Average CSM/WR kg per ply and resin ratio for a schedule.

    Classic (percentage recipe) is expressed as 3 equivalent CSM plies so
    the take-off stays internally consistent.
    """
    if layup == "classic" and calc is not None:
        recipe = calc["recipe"]
        glass_m2 = (calc["dims_mm"]["thickness"] / 1000.0
                    * recipe["density_kg_m3"] * recipe["fiber_pct"] / 100.0)
        resin_m2 = (calc["dims_mm"]["thickness"] / 1000.0
                    * recipe["density_kg_m3"] * recipe["resin_pct"] / 100.0)
        return {"csm_plies": 3, "wr_plies": 0, "csm_avg": glass_m2 / 3,
                "wr_avg": 0.0,
                "ratio": (resin_m2 / glass_m2) if glass_m2 else 0.0}
    spec = layups.get_schedule(layup)
    csm_plies, csm_kg, wr_plies, wr_kg = 0, 0.0, 0, 0.0
    for layer in spec["layers"]:
        info = layups.REINFORCEMENTS[layer]
        if layer.startswith("csm"):
            csm_plies += 1
            csm_kg += info["gsm"] / 1000.0
        else:
            wr_plies += 1
            wr_kg += info["gsm"] / 1000.0
    resin = layups.schedule_resin_per_m2(layup)
    glass = csm_kg + wr_kg
    return {
        "csm_plies": csm_plies, "wr_plies": wr_plies,
        "csm_avg": (csm_kg / csm_plies) if csm_plies else 0.0,
        "wr_avg": (wr_kg / wr_plies) if wr_plies else 0.0,
        "ratio": (resin / glass) if glass else 0.0,
    }


def build_workbook(title, qty, calc, inputs, rates):
    """Render the Costing/Inputs/Take-off workbook; returns openpyxl Workbook."""
    layup = calc.get("layup") or "classic"
    avgs = _schedule_avgs(layup, calc)
    gelcoat_on = bool(calc.get("gelcoat"))
    coverage = layups.schedule_gelcoat_per_m2(layup) if layup != "classic" else 0.0
    wb = Workbook()
    _build_inputs(wb, title, qty, calc, inputs, rates, avgs, coverage, gelcoat_on)
    take_refs = _build_takeoff(wb, title, calc, inputs, avgs, coverage, gelcoat_on)
    _build_costing(wb, title, qty, calc, inputs, rates, avgs, take_refs)
    return wb


# ---------------------------------------------------------------- Inputs ---

def _build_inputs(wb, title, qty, calc, inputs, rates, avgs, coverage, gelcoat_on):
    ws = wb.active
    ws.title = "Inputs"
    _widths(ws, [44, 14, 12, 14, 12, 70])
    ws["A1"] = "%s - COSTING INPUTS" % title
    ws["A1"].font = BOLD
    ws["A2"] = "Yellow = estimate, please confirm. White = fixed or from the app."

    row = 4
    _hdr(ws, row, ["Exchange / landed cost", "Value", "Unit", "", "",
                  "Source / note"])
    ws.cell(row=5, column=1, value="USD to BHD")
    ws.cell(row=5, column=2, value=0.376).number_format = "0.00000"
    ws.cell(row=5, column=3, value="BHD/USD")
    ws.cell(row=5, column=6, value="Bahrain dinar fixed peg")
    ws.cell(row=6, column=1, value="SAR to BHD")
    ws.cell(row=6, column=2, value="=B5/3.75").number_format = "0.00000"
    ws.cell(row=6, column=3, value="BHD/SAR")
    ws.cell(row=6, column=6, value="Saudi riyal peg 3.75 per USD")
    ws.cell(row=7, column=1, value="Landed cost factor")
    ws.cell(row=7, column=2, value=1.0).number_format = "0.00"
    ws.cell(row=7, column=3, value="x")
    ws.cell(row=7, column=6, value="Rates already in BHD - raise if importing")

    _hdr(ws, MAT_START - 1, ["Raw material", "Price", "Currency",
                             "BHD / unit (landed)", "Per", "Source"])
    rate_row = {}
    for i, (name, key, per) in enumerate(MATERIALS):
        r = MAT_START + i
        ws.cell(row=r, column=1, value=name)
        ws.cell(row=r, column=2, value=rates[key]).number_format = "0.00"
        ws.cell(row=r, column=3, value="BHD")
        ws.cell(row=r, column=4, value="=B%d*1" % r).number_format = MONEY
        ws.cell(row=r, column=5, value=per)
        ws.cell(row=r, column=6, value="Material prices in the app")
        rate_row[name] = r

    lr = LR  # laminate rules header
    _hdr(ws, lr, ["Laminate rules", "Value", "Unit", "", "", "Note"])
    recipe = inputs["recipe"]
    rules = [
        ("CSM weight (avg per ply)", avgs["csm_avg"], "kg/m2 per ply",
         "Schedule average", "0.00"),
        ("WR weight (avg per ply)", avgs["wr_avg"], "kg/m2 per ply",
         "Schedule average", "0.00"),
        ("Resin : glass ratio", avgs["ratio"], "kg resin per kg glass",
         "Schedule average", "0.00"),
        ("Gelcoat coverage", coverage if gelcoat_on else 0.0, "kg/m2",
         "Schedule coverage (0 when off)", "0.00"),
        ("Paint coverage", layups.PAINT_KG_M2, "kg/m2", "Topcoat", "0.00"),
        ("Catalyst (MEKP)", recipe["mekp_pct"] / 100.0, "of resin + gelcoat",
         "App recipe", PCT1),
        ("Pigment", recipe["pigment_pct"] / 100.0, "of gelcoat",
         "App recipe", PCT1),
        ("Material wastage", recipe["wastage_pct"] / 100.0, "",
         "App recipe", PCT1),
        ("Flowcoat coverage", 0.4, "kg/m2", "Inner flowcoat (cabin)", "0.00"),
        ("ISO resin skin-coat share",
         recipe.get("iso_share_pct", 0.0) / 100.0, "of resin",
         "First layer behind gelcoat", PCT1),
        ("Consumables", recipe.get("consumables_pct", 0.0) / 100.0,
         "of GRP materials", "App recipe", PCT1),
        ("Bonding paste / filler per piece", inputs.get("paste_kg", 0.0),
         "kg", "Corner joints, filling", QTY2),
    ]
    rule_row = {}
    for i, (name, value, unit, note, fmt) in enumerate(rules):
        r = lr + 1 + i
        ws.cell(row=r, column=1, value=name)
        ws.cell(row=r, column=2, value=value).number_format = fmt
        ws.cell(row=r, column=3, value=unit)
        ws.cell(row=r, column=6, value=note)
        rule_row[name] = r

    cr = CR  # commercial header
    assert cr == lr + 1 + len(rules) + 1, "Inputs layout drift"
    _hdr(ws, cr, ["Labour & commercial", "Value", "Unit", "", "", "Note"])
    recipe = inputs["recipe"]
    commercial = [
        ("Quantity (units)", qty, "nos", "", "0", False),
        ("Labour rate (blended)", rates["labour"], "BHD/hour",
         "Use payroll cost per hour", MONEY, True),
        ("Machine rate", rates["machine"], "BHD/hour", "App rates", MONEY, False),
        ("Factory overhead", recipe["overhead_pct"] / 100.0, "of direct cost",
         "App recipe", PCT1, True),
        ("Profit margin (on cost)", inputs.get("markup_pct", 0.0) / 100.0, "",
         "Your decision", PCT1, True),
        ("VAT", inputs.get("tax_pct", 0.0) / 100.0, "", "Bahrain standard rate",
         PCT1, False),
        ("New mould (total for the job)", inputs.get("mould_cost", 0.0), "BHD",
         "0 if mould exists", MONEY, True),
        ("Mould life (pieces)", inputs.get("mould_life_qty") or qty, "pc",
         "Blank in app = batch", "0", False),
        ("Transport & installation per unit", inputs.get("delivery_bd", 0.0), "BHD",
         "App extras", MONEY, True),
        ("Testing & certification per unit", inputs.get("testing_bd", 0.0), "BHD",
         "App extras", MONEY, True),
    ]
    comm_row = {}
    for i, (name, value, unit, note, fmt, est) in enumerate(commercial):
        r = cr + 1 + i
        ws.cell(row=r, column=1, value=name)
        cell = ws.cell(row=r, column=2, value=value)
        if est:
            _est(cell, fmt)
        else:
            cell.number_format = fmt
        ws.cell(row=r, column=3, value=unit)
        ws.cell(row=r, column=6, value=note)
        comm_row[name] = r
    return {"rate": rate_row, "rule": rule_row, "comm": comm_row}


# --------------------------------------------------------------- Take-off ---

def _build_takeoff(wb, title, calc, inputs, avgs, coverage, gelcoat_on):
    layup = calc.get("layup") or "classic"
    ws = wb.create_sheet("Take-off")
    _widths(ws, [38, 12, 12, 8, 12, 11, 9, 9, 10, 11, 11, 14, 10, 10, 13, 11])
    ws["A1"] = "%s - TAKE-OFF PER PIECE" % title
    ws["A1"].font = BOLD
    ws["A2"] = "Areas come from the app estimate - openings are yours to fill."
    _hdr(ws, 4, ["Opening", "Width (m)", "Height (m)", "Qty", "Area (m2)"])
    detail = list(inputs.get("openings") or [])
    if len(detail) > 3:
        rest_m2 = sum(o["width_m"] * o["height_m"] * o["qty"] for o in detail[2:])
        detail = detail[:2] + [{"label": "Further openings (total)",
                                "width_m": round(rest_m2, 4), "height_m": 1,
                                "qty": 1}]
    if detail:
        for i, opening in enumerate(detail):
            r = 5 + i
            ws.cell(row=r, column=1, value=opening["label"])
            ws.cell(row=r, column=2, value=opening["width_m"]
                    ).number_format = "0.00"
            ws.cell(row=r, column=3, value=opening["height_m"]
                    ).number_format = "0.00"
            ws.cell(row=r, column=4, value=opening["qty"]).number_format = "0"
            ws.cell(row=r, column=5,
                    value="=B%d*C%d*D%d" % (r, r, r)).number_format = QTY2
        first_blank = 5 + len(detail)
    else:
        ws.cell(row=5, column=1, value="Doors / windows (total from app)")
        ws.cell(row=5, column=2, value=inputs.get("openings_m2") or 0.0
                ).number_format = "0.00"
        ws.cell(row=5, column=3, value=1).number_format = "0"
        ws.cell(row=5, column=4, value=1).number_format = "0"
        ws.cell(row=5, column=5, value="=B5*C5*D5").number_format = QTY2
        first_blank = 6
    for i in range(first_blank, 8):
        ws.cell(row=i, column=1, value="Opening (add as needed)")
        ws.cell(row=i, column=2, value=None).number_format = "0.00"
        ws.cell(row=i, column=3, value=None).number_format = "0.00"
        ws.cell(row=i, column=4, value=None).number_format = "0"
        ws.cell(row=i, column=5,
                value="=B%d*C%d*D%d" % (i, i, i)).number_format = QTY2
    ws.cell(row=8, column=1, value="Total openings").font = BOLD
    _tot(ws, 8, 5, "=SUM(E5:E7)", QTY2).font = BOLD
    ws.cell(row=9, column=1, value="Total opening perimeter (m)")
    ws.cell(row=9, column=5,
            value="=SUMPRODUCT(2*(B5:B7+C5:C7),D5:D7)").number_format = QTY2

    head = ["Component", "Area (m2)", "x", "Count", "Less openings (m2)",
            "Net area (m2)", "CSM plies", "WR plies", "Glass kg/m2", "Glass (kg)",
            "Resin (kg)", "Surface coat", "Coat (kg)", "Tissue (m2)", "Core",
            "Core area (m2)"]
    _hdr(ws, 11, head)
    parts = [p for p in calc["area_parts"] if p["area_m2"] >= 0]
    detailed = layup != "classic" and any("layup" in p for p in parts)
    walled = any(p.get("wall") for p in parts)
    first = 12
    tot_row = first + len(parts)
    for i, part in enumerate(parts):
        r = first + i
        ws.cell(row=r, column=1, value=part["label"])
        ws.cell(row=r, column=2, value=round(part["area_m2"], 4)).number_format = QTY2
        ws.cell(row=r, column=3, value=1).number_format = "0"
        ws.cell(row=r, column=4, value=1).number_format = "0"
        if part.get("wall"):
            ws.cell(row=r, column=5, value="=$E$8").number_format = QTY2
        elif walled:
            ws.cell(row=r, column=5, value=0).number_format = QTY2
        else:
            ws.cell(row=r, column=5,
                    value="=IF($B$%d=0,0,$E$8*B%d/$B$%d)"
                          % (tot_row, r, tot_row)).number_format = QTY2
        ws.cell(row=r, column=6,
                value="=MAX(0,B%d*C%d*D%d-E%d)" % (r, r, r, r)).number_format = QTY2
        if detailed and part.get("layup") and part["layup"] != layup:
            per = _schedule_avgs(part["layup"], None)
            csm_plies, wr_plies = per["csm_plies"], per["wr_plies"]
        else:
            csm_plies, wr_plies = avgs["csm_plies"], avgs["wr_plies"]
        ws.cell(row=r, column=7, value=csm_plies).number_format = "0"
        ws.cell(row=r, column=8, value=wr_plies).number_format = "0"
    csm_w, wr_w, ratio = LR + 1, LR + 2, LR + 3
    gel_cov = LR + 4
    flow_cov = LR + RULE_ROWS
    for i, part in enumerate(parts):
        r = first + i
        ws.cell(row=r, column=9,
                value="=G%d*Inputs!$B$%d+H%d*Inputs!$B$%d"
                      % (r, csm_w, r, wr_w)).number_format = QTY2
        ws.cell(row=r, column=10, value="=F%d*I%d" % (r, r)).number_format = QTY2
        ws.cell(row=r, column=11,
                value="=J%d*Inputs!$B$%d" % (r, ratio)).number_format = QTY2
        if not gelcoat_on:
            coat = "None" if part.get("coat") != "paint" else "Paint"
        elif detailed:
            coat = {"gelcoat": "Gelcoat", "flowcoat": "Flowcoat white",
                    "paint": "Paint",
                    "none": "None"}.get(part.get("coat", "gelcoat"), "Gelcoat")
        else:
            coat = "Gelcoat"
        ws.cell(row=r, column=12, value=coat)
        ws.cell(row=r, column=13,
                value='=IF(L%d="Gelcoat",F%d*Inputs!$B$%d,'
                      'IF(L%d="Flowcoat white",F%d*Inputs!$B$%d,0))'
                      % (r, r, gel_cov, r, r, flow_cov)).number_format = QTY2
        ws.cell(row=r, column=14,
                value='=IF(L%d="Gelcoat",F%d,0)' % (r, r)
                ).number_format = QTY2
        core = part.get("core") or {}
        if core.get("material") == "pufoam":
            ws.cell(row=r, column=15, value="PU foam board")
            ws.cell(row=r, column=16, value="=F%d" % r).number_format = QTY2
        elif core.get("material") == "plywood":
            ws.cell(row=r, column=15, value="Plywood 18 mm")
            ws.cell(row=r, column=16, value="=F%d" % r).number_format = QTY2
        else:
            ws.cell(row=r, column=16, value=0).number_format = QTY2
    last = first + len(parts) - 1
    t = last + 1
    assert t == first + len(parts), "take-off layout drift"
    ws.cell(row=t, column=1, value="TOTAL PER PIECE").font = BOLD
    _tot(ws, t, 2, "=SUM(B%d:B%d)" % (first, last), QTY2)
    _tot(ws, t, 6, "=SUM(F%d:F%d)" % (first, last), QTY2)
    _tot(ws, t, 10, "=SUM(J%d:J%d)" % (first, last), QTY2)
    _tot(ws, t, 11, "=SUM(K%d:K%d)" % (first, last), QTY2)
    _tot(ws, t, 13, "=SUM(M%d:M%d)" % (first, last), QTY2)
    _tot(ws, t, 14, "=SUM(N%d:N%d)" % (first, last), QTY2)
    _tot(ws, t, 16, "=SUM(P%d:P%d)" % (first, last), QTY2)
    g = t + 1
    ws.cell(row=g, column=1, value="Glass - CSM (kg)")
    ws.cell(row=g, column=6,
            value="=SUMPRODUCT(F%d:F%d,G%d:G%d)*Inputs!$B$%d"
                  % (first, last, first, last, csm_w)).number_format = QTY2
    ws.cell(row=g + 1, column=1, value="Glass - WR (kg)")
    ws.cell(row=g + 1, column=6,
            value="=SUMPRODUCT(F%d:F%d,H%d:H%d)*Inputs!$B$%d"
                  % (first, last, first, last, wr_w)).number_format = QTY2
    ws.cell(row=g + 2, column=1, value="GRP weight per piece (kg, excl. cores)")
    ws.cell(row=g + 2, column=6,
            value="=J%d+K%d+M%d" % (t, t, t)).number_format = QTY2
    return {"first": first, "last": last, "total": t, "csm": g, "wr": g + 1,
            "area": (t, 6), "glass": (t, 10), "resin": (t, 11), "coat": (t, 13),
            "tissue": (t, 14)}


# ---------------------------------------------------------------- Costing ---

def _cost_section(ws, row, title):
    _hdr(ws, row, [title, "Qty", "Unit", "Rate (BHD)", "Amount (BHD)", "Basis"])
    return row + 1


def _cost_row(ws, row, label, qty, unit, rate, amount, basis,
              qty_fmt=QTY2, rate_fmt=MONEY, est_rate=False, est_qty=False):
    ws.cell(row=row, column=1, value=label)
    qcell = ws.cell(row=row, column=2, value=qty)
    if est_qty:
        _est(qcell, qty_fmt)
    else:
        qcell.number_format = qty_fmt
    ws.cell(row=row, column=3, value=unit)
    rcell = ws.cell(row=row, column=4, value=rate)
    if est_rate:
        _est(rcell, rate_fmt)
    else:
        rcell.number_format = rate_fmt
    ws.cell(row=row, column=5, value=amount).number_format = MONEY
    ws.cell(row=row, column=6, value=basis)
    return row + 1


def _build_costing(wb, title, qty, calc, inputs, rates, avgs, take):
    ws = wb.create_sheet("Costing")
    _widths(ws, [52, 12, 10, 13, 15, 52])
    ws["A1"] = "%s - COST & SELLING PRICE" % title
    ws["A1"].font = BOLD
    ws["A2"] = "Per piece unless stated. Quantity: %d. Edit yellow cells freely." % qty
    recipe = inputs["recipe"]
    lr, cr = LR, CR
    waste = "Inputs!$B$%d" % (lr + 8)
    mekp = "Inputs!$B$%d" % (lr + 6)
    pigment = "Inputs!$B$%d" % (lr + 7)
    paint_cov = "Inputs!$B$%d" % (lr + 5)
    gel_cov = "Inputs!$B$%d" % (lr + 4)
    q_qty = "Inputs!$B$%d" % (cr + 1)
    q_lab = "Inputs!$B$%d" % (cr + 2)
    q_mac = "Inputs!$B$%d" % (cr + 3)
    q_oh = "Inputs!B%d" % (cr + 4)
    q_margin = "Inputs!B%d" % (cr + 5)
    q_vat = "Inputs!B%d" % (cr + 6)
    q_mould = "Inputs!B%d" % (cr + 7)
    q_life = "Inputs!B%d" % (cr + 8)
    q_trans = "Inputs!B%d" % (cr + 9)
    q_test = "Inputs!B%d" % (cr + 10)
    rate_addr = {name: "=Inputs!D%d" % (MAT_START + i)
                 for i, (name, _, _) in enumerate(MATERIALS)}
    t, f = take["total"], take["first"]
    l = take["last"]

    row = 4
    row = _cost_section(ws, row, "A. GRP MATERIALS")
    a_first = row
    glass = calc.get("glass_kg") or {}
    if (calc.get("layup") or "classic") == "classic":
        glass = {"fiber": calc.get("fiber_kg", 0.0)}
        mat_names = {"fiber": "Fiberglass generic (classic)"}
    else:
        mat_names = {"csm300": "CSM 300 g/m2", "csm450": "CSM 450 g/m2",
                     "csm600": "CSM 600 g/m2", "wr600": "Woven roving 600 g/m2",
                     "wr800": "Woven roving 800 g/m2"}
    csm_total = sum(v for k, v in glass.items()
                    if k.startswith("csm") or k == "fiber")
    wr_total = sum(v for k, v in glass.items() if k.startswith("wr"))
    for key, kg in glass.items():
        if key == "fiber":
            base = "'Take-off'!F%d" % take["csm"]
            label = "Fiberglass (generic)"
            mat = mat_names[key]
            row = _cost_row(ws, row, label, "=(%s)*(1+%s)" % (base, waste), "kg",
                            rate_addr[mat], "=B%d*D%d" % (row, row),
                            "Take-off + wastage")
            continue
        label = "Glass - " + layups.REINFORCEMENTS[key]["label"]
        if key.startswith("csm") and csm_total:
            share = kg / (csm_total * (1 + recipe["wastage_pct"] / 100.0))
            base = "'Take-off'!F%d*%.6f" % (take["csm"], share)
        elif key.startswith("wr") and wr_total:
            share = kg / (wr_total * (1 + recipe["wastage_pct"] / 100.0))
            base = "'Take-off'!F%d*%.6f" % (take["wr"], share)
        else:
            base = "0"
        mat = mat_names[key]
        row = _cost_row(ws, row, label, "=(%s)*(1+%s)" % (base, waste), "kg",
                        rate_addr[mat], "=B%d*D%d" % (row, row),
                        "Take-off + wastage")
    iso_share = "Inputs!$B$%d" % (lr + 10)
    cons_pct = "Inputs!B%d" % (lr + 11)
    paste_addr = "Inputs!$B$%d" % (lr + 12)
    resin_labels = {"gp": "GP polyester resin", "iso": "Isophthalic resin",
                    "ve": "Vinyl ester resin"}
    resin_key = inputs.get("resin_type") or "gp"
    if calc.get("iso_kg"):
        row = _cost_row(ws, row, "GP resin",
                        "='Take-off'!K%d*(1-%s)*(1+%s)" % (t, iso_share, waste),
                        "kg", rate_addr["GP polyester resin"],
                        "=B%d*D%d" % (row, row), "Resin less ISO share")
        row = _cost_row(ws, row, "ISO resin (skin coat)",
                        "='Take-off'!K%d*%s*(1+%s)" % (t, iso_share, waste),
                        "kg", rate_addr["Isophthalic resin"],
                        "=B%d*D%d" % (row, row), "First layer behind gelcoat")
    else:
        row = _cost_row(ws, row, "Resin (%s)" % resin_labels[resin_key],
                        "='Take-off'!K%d*(1+%s)" % (t, waste), "kg",
                        rate_addr[resin_labels[resin_key]],
                        "=B%d*D%d" % (row, row), "Take-off + wastage")
    row = _cost_row(ws, row, "Surface tissue",
                    "='Take-off'!N%d*(1+%s)" % (t, waste), "m2",
                    rate_addr["Surface tissue 30 g/m2"],
                    "=B%d*D%d" % (row, row), "Behind gelcoat")
    row = _cost_row(ws, row, "Gelcoat + flowcoat",
                    "='Take-off'!M%d*(1+%s)" % (t, waste), "kg",
                    rate_addr["Gelcoat"], "=B%d*D%d" % (row, row),
                    "Take-off + wastage")
    row = _cost_row(ws, row, "Pigment paste",
                    "='Take-off'!M%d*%s*(1+%s)" % (t, pigment, waste), "kg",
                    rate_addr["Pigment paste"], "=B%d*D%d" % (row, row),
                    "% of gelcoat")
    row = _cost_row(ws, row, "Catalyst MEKP",
                    "=('Take-off'!K%d+'Take-off'!M%d)*%s*(1+%s)"
                    % (t, t, mekp, waste), "kg",
                    rate_addr["MEKP catalyst"], "=B%d*D%d" % (row, row),
                    "% of resin + gelcoat")
    if calc.get("paint"):
        row = _cost_row(ws, row, "Paint / topcoat",
                        "='Take-off'!F%d*%s*(1+%s)" % (t, paint_cov, waste), "kg",
                        rate_addr["Paint / topcoat"], "=B%d*D%d" % (row, row),
                        "Take-off area + wastage")
    cores = calc.get("core_m2") or {}
    if cores.get("pufoam"):
        row = _cost_row(ws, row, "PU foam core 20 mm",
                        "=SUMIF('Take-off'!O%d:O%d,\"PU foam*\","
                        "'Take-off'!P%d:P%d)*(1+%s)" % (f, l, f, l, waste), "m2",
                        rate_addr["PU foam board 20 mm"],
                        "=B%d*D%d" % (row, row), "Take-off cores + wastage")
    if cores.get("plywood"):
        row = _cost_row(ws, row, "Plywood floor core 18 mm",
                        "=SUMIF('Take-off'!O%d:O%d,\"Plywood*\","
                        "'Take-off'!P%d:P%d)*(1+%s)" % (f, l, f, l, waste), "m2",
                        rate_addr["Marine plywood 18 mm"],
                        "=B%d*D%d" % (row, row), "Take-off cores + wastage")
    row = _cost_row(ws, row, "Bonding paste / filler", "=" + paste_addr, "kg",
                    rate_addr["Bonding paste / filler"],
                    "=B%d*D%d" % (row, row), "Corner joints, filling",
                    est_qty=True)
    a_last = row - 1
    row = _cost_row(ws, row, "Consumables", "", "",
                    "=" + cons_pct,
                    "=SUM(E%d:E%d)*D%d" % (a_first, a_last, row),
                    "% of GRP materials", est_rate=True)
    a_last = row - 1
    ws.cell(row=row, column=1, value="Sub-total A").fill = SUB
    ws.cell(row=row, column=1).font = BOLD
    _sub(ws, row, 5, "=SUM(E%d:E%d)" % (a_first, a_last), MONEY)
    a_sub = row
    row += 2

    row = _cost_section(ws, row, "B. BOUGHT-IN ITEMS")
    b_first = row
    bought = []
    for item in inputs.get("bought_ins") or []:
        bought.append((item.get("label", ""), item.get("qty", 0),
                       item.get("unit", "no"), item.get("rate", 0),
                       item.get("basis") or "ESTIMATE - review qty and price",
                       bool(item.get("by_client", False))))
    if inputs.get("hardware_cost"):
        bought.append(("Hardware / fittings", 1, "lot", inputs["hardware_cost"],
                       "App extras", False))
    if inputs.get("plywood_m2"):
        bought.append(("Marine plywood 18 mm supports", inputs["plywood_m2"], "m2",
                       rates["plywood"], "App supports", False))
    if inputs.get("steel_kg"):
        bought.append(("Mild steel supports", inputs["steel_kg"], "kg", rates["steel"],
                       "App supports", False))
    if not bought:
        bought.append(("(add bought-in items here)", 0, "", 0, "", False))
    for label, q, unit, rate, basis, by_client in bought:
        if by_client:
            amount, note = 0, "By client - not charged (%s)" % basis
        else:
            amount, note = "=B%d*D%d" % (row, row), basis
        row = _cost_row(ws, row, label, q, unit, rate, amount, note,
                        qty_fmt="0.00", est_rate=True)
    b_last = row - 1
    ws.cell(row=row, column=1, value="Sub-total B").fill = SUB
    ws.cell(row=row, column=1).font = BOLD
    _sub(ws, row, 5, "=SUM(E%d:E%d)" % (b_first, b_last), MONEY)
    b_sub = row
    row += 2

    row = _cost_section(ws, row, "C. DIRECT LABOUR")
    c_first = row
    ops = calc.get("labour_ops") or []
    if ops:
        for op in ops:
            row = _cost_row(ws, row, op["label"], op["hours"], "hours",
                            "=" + q_lab, "=B%d*D%d" % (row, row),
                            "Cabin operation - adjust hours to shop",
                            qty_fmt="0.0", est_qty=True)
    else:
        row = _cost_row(ws, row, "Fabrication labour (all operations)",
                        recipe["labour_hours"], "hours", "=" + q_lab,
                        "=B%d*D%d" % (row, row),
                        "Hours are ESTIMATES - adjust to shop experience",
                        qty_fmt="0.0", est_qty=True)
    if recipe.get("machine_hours"):
        row = _cost_row(ws, row, "Machine time", recipe["machine_hours"], "hours",
                        "=" + q_mac, "=B%d*D%d" % (row, row), "", qty_fmt="0.0",
                        est_qty=True)
    c_last = row - 1
    ws.cell(row=row, column=1, value="Sub-total C").fill = SUB
    ws.cell(row=row, column=1).font = BOLD
    _sub(ws, row, 2, "=SUM(B%d:B%d)" % (c_first, c_last), "0.0")
    _sub(ws, row, 5, "=SUM(E%d:E%d)" % (c_first, c_last), MONEY)
    c_sub, c_qty = row, row
    row += 2

    row = _cost_section(ws, row, "D. OTHER DIRECT COSTS")
    d_first = row
    if (inputs.get("mould_option") or "have") == "need":
        row = _cost_row(ws, row, "Mould / plug share", "=1/MAX(1,%s)" % q_life,
                        "share", "=%s" % q_mould, "=B%d*D%d" % (row, row),
                        "New mould cost spread over the units", qty_fmt="0.00")
    if inputs.get("delivery_bd"):
        row = _cost_row(ws, row, "Transport & installation", 1, "lot",
                        "=%s" % q_trans, "=B%d*D%d" % (row, row), "",
                        qty_fmt="0")
    if inputs.get("testing_bd"):
        row = _cost_row(ws, row, "Testing & certification", 1, "lot",
                        "=%s" % q_test, "=B%d*D%d" % (row, row), "",
                        qty_fmt="0")
    if row == d_first:
        row = _cost_row(ws, row, "(no other direct costs)", 0, "", 0,
                        "=B%d*D%d" % (row, row), "", qty_fmt="0")
    d_last = row - 1
    ws.cell(row=row, column=1, value="Sub-total D").fill = SUB
    ws.cell(row=row, column=1).font = BOLD
    _sub(ws, row, 5, "=SUM(E%d:E%d)" % (d_first, d_last), MONEY)
    d_sub = row
    row += 2

    _hdr(ws, row, ["SUMMARY", "", "", "Per piece (BHD)", "Project (BHD)", ""])
    s = row + 1
    ws.cell(row=s, column=1, value="Direct cost (A + B + C + D)")
    ws.cell(row=s, column=4, value="=E%d+E%d+E%d+E%d" % (a_sub, b_sub, c_sub, d_sub)
            ).number_format = MONEY
    ws.cell(row=s, column=5, value="=D%d*%s" % (s, q_qty)).number_format = MONEY
    ws.cell(row=s + 1, column=1, value="Factory overhead")
    ws.cell(row=s + 1, column=4, value="=D%d*%s" % (s, q_oh)).number_format = MONEY
    ws.cell(row=s + 1, column=5, value="=D%d*%s" % (s + 1, q_qty)).number_format = MONEY
    ws.cell(row=s + 1, column=6,
            value='="Overhead "&TEXT(%s,"0%%")' % q_oh)
    for c in (1, 4, 5):
        _tot(ws, s + 2, c, None)
    ws.cell(row=s + 2, column=1, value="TOTAL COST")
    ws.cell(row=s + 2, column=4, value="=D%d+D%d" % (s, s + 1)).number_format = MONEY
    ws.cell(row=s + 2, column=5, value="=D%d*%s" % (s + 2, q_qty)).number_format = MONEY
    ws.cell(row=s + 3, column=1, value="Profit")
    ws.cell(row=s + 3, column=4, value="=D%d*%s" % (s + 2, q_margin)
            ).number_format = MONEY
    ws.cell(row=s + 3, column=5, value="=D%d*%s" % (s + 3, q_qty)).number_format = MONEY
    ws.cell(row=s + 3, column=6,
            value='="Margin "&TEXT(%s,"0%%")&" on cost"' % q_margin)
    ws.cell(row=s + 4, column=1, value="SELLING PRICE (excl. VAT)").font = BOLD
    ws.cell(row=s + 4, column=4, value="=D%d+D%d" % (s + 2, s + 3)
            ).number_format = MONEY
    ws.cell(row=s + 4, column=5, value="=D%d*%s" % (s + 4, q_qty)).number_format = MONEY
    for c in (1, 4, 5):
        _tot(ws, s + 5, c, None)
    ws.cell(row=s + 5, column=1, value="VAT")
    ws.cell(row=s + 5, column=4, value="=D%d*%s" % (s + 4, q_vat)).number_format = MONEY
    ws.cell(row=s + 5, column=5, value="=D%d*%s" % (s + 5, q_qty)).number_format = MONEY
    ws.cell(row=s + 6, column=1, value="SELLING PRICE (incl. VAT)").font = BOLD
    ws.cell(row=s + 6, column=4, value="=D%d+D%d" % (s + 4, s + 5)
            ).number_format = MONEY
    ws.cell(row=s + 6, column=5, value="=D%d*%s" % (s + 6, q_qty)).number_format = MONEY
    ws.cell(row=s + 6, column=6, value='="Quantity: "&%s&" units"' % q_qty)
    b = s + 8
    ws.cell(row=b, column=1, value="Cost breakdown per piece").font = BOLD
    for i, (label, addr) in enumerate((("GRP materials", a_sub),
                                       ("Bought-in items", b_sub),
                                       ("Labour", c_sub),
                                       ("Mould, transport, installation", d_sub))):
        ws.cell(row=b + 1 + i, column=1, value=label)
        ws.cell(row=b + 1 + i, column=4, value="=E%d" % addr).number_format = MONEY
        ws.cell(row=b + 1 + i, column=5,
                value="=IF(D%d=0,0,D%d/D%d)" % (s, b + 1 + i, s)).number_format = PCT1
    ws.cell(row=b + 5, column=1, value="Labour hours per piece")
    ws.cell(row=b + 5, column=4, value="=B%d" % c_qty).number_format = "0.0"
    ws.cell(row=b + 6, column=1, value="Approx. GRP weight per piece (kg)")
    ws.cell(row=b + 6, column=4,
            value="='Take-off'!J%d+'Take-off'!K%d+'Take-off'!M%d"
                  % (take["total"], take["total"], take["total"])).number_format = "0"
    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False
