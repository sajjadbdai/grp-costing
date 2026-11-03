"""Estimation sheet PDF export (fpdf2).

Builds a printable A4 estimation sheet from a calculated estimate: header,
item specification, dimensions, area, cost lines, totals, assumptions,
exclusions and approval lines.
"""

from __future__ import annotations

from fpdf import FPDF
from fpdf.fonts import FontFace

TITLE = "ESTIMATION SHEET"
SUBTITLE = "GFPF fiberglass costing"


def _txt(value):
    """Core-font-safe text (Helvetica covers latin-1)."""
    text = str(value)
    for old, new in (("²", "2"), ("×", "x"), ("–", "-"), ("—", "-"),
                     (""", '"'), (""", '"'), ("‘", "'"), ("’", "'"),
                     ("…", "..."), ("≈", "~"), ("✓", "v"), ("→", "->")):
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


def _bd(value):
    return "BD %.3f" % float(value)


class _Sheet(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, _txt("Page %d/{nb}  -  GFPF estimation (cost guidance only)"
                             % self.page_no()), align="C")


def _section(pdf, title):
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(18, 63, 99)
    pdf.cell(0, 8, _txt(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def _table(pdf, headings, rows, widths=None):
    pdf.set_font("Helvetica", "", 9)
    style = FontFace(emphasis="BOLD", color=(255, 255, 255),
                     fill_color=(18, 63, 99))
    align = tuple(["LEFT"] + ["RIGHT"] * (len(headings) - 1))
    with pdf.table(headings_style=style, line_height=6, col_widths=widths,
                   text_align=align) as table:
        head = table.row()
        for heading in headings:
            head.cell(_txt(heading))
        for record in rows:
            row = table.row()
            for datum in record:
                row.cell(_txt(datum))


def _bullets(pdf, items):
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "", 9)
    for item in items:
        pdf.multi_cell(0, 5, _txt("- " + item), new_x="LMARGIN", new_y="NEXT")


def build_pdf(sheet_no, sheet_date, sheet_status, calc, dims_display, spec_rows,
              description=""):
    """Render the estimation sheet; returns the PDF bytes."""
    pdf = _Sheet(orientation="P", unit="mm", format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(True, margin=20)
    pdf.alias_nb_pages("{nb}")
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(18, 63, 99)
    pdf.cell(0, 9, TITLE, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 6, _txt(SUBTITLE), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _txt("Sheet no: %s      Date: %s      Status: %s"
                        % (sheet_no, sheet_date, sheet_status)),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _txt("Batch total (cost): %s     Cost per piece: %s     "
                        "Laminate/pc: %.2f kg"
                        % (_bd(calc["total_bd"]), _bd(calc["per_piece_bd"]),
                           calc["laminate_kg"])),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if description:
        _section(pdf, "Project")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, _txt(description))
        pdf.ln(1)

    _section(pdf, "Item specification")
    _table(pdf, ("Item", "Detail"),
           [(s["label"], s["value"]) for s in spec_rows], widths=(60, 120))

    _section(pdf, "Dimensions")
    _table(pdf, ("Dimension", "Original", "Metric"),
           [(d["label"], "%s %s" % (d["value"], d["unit"]), d["metric"])
            for d in dims_display], widths=(70, 55, 55))

    _section(pdf, "Area")
    parts = [(p["label"], "%.4f m2" % p["area_m2"]) for p in calc["area_parts"]]
    parts.append(("Total area", "%.4f m2" % calc["area_m2"]))
    _table(pdf, ("Part", "Area"), parts, widths=(120, 60))

    _section(pdf, "Cost breakdown (per piece)")
    _table(pdf, ("Component", "Qty", "Rate BD", "Amount BD"),
           [(line["label"], "%.3f %s" % (line["qty"], line["unit"]),
             "%.3f" % line["rate"], "%.3f" % line["amount"])
            for line in calc["lines"]], widths=(75, 35, 35, 35))

    _section(pdf, "Totals")
    totals = [("Subtotal per piece", _bd(calc["subtotal_pc_bd"])),
              ("Batch of %d" % calc["qty"], _bd(calc["batch_bd"])),
              ("Overhead", _bd(calc["overhead_bd"]))]
    if calc.get("mould_bd"):
        totals.append(("New mould (amortised)", _bd(calc["mould_bd"])))
    if calc.get("delivery_batch_bd", calc.get("delivery_bd")):
        totals.append(("Delivery, packing, installation",
                       _bd(calc.get("delivery_batch_bd", calc.get("delivery_bd")))))
    if calc.get("testing_batch_bd", calc.get("testing_bd")):
        totals.append(("Testing, inspection, certification",
                       _bd(calc.get("testing_batch_bd", calc.get("testing_bd")))))
    totals.append(("ESTIMATED TOTAL (cost)", _bd(calc["total_bd"])))
    if calc.get("markup_bd"):
        totals.append(("Margin / markup (%.2f%%)" % calc.get("markup_pct", 0.0),
                       _bd(calc["markup_bd"])))
        totals.append(("SELLING PRICE", _bd(calc["selling_bd"])))
    if calc.get("tax_bd"):
        totals.append(("Tax / duties (%.2f%%)" % calc.get("tax_pct", 0.0),
                       _bd(calc["tax_bd"])))
        totals.append(("GRAND TOTAL", _bd(calc["grand_total_bd"])))
    _table(pdf, ("Item", "BD"), totals, widths=(120, 60))

    _section(pdf, "Assumptions")
    _bullets(pdf, calc["assumptions"])
    _section(pdf, "Excluded (not charged)")
    if calc["exclusions"]:
        _bullets(pdf, calc["exclusions"])
    else:
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, "Nothing excluded - every standard item is included.")

    _section(pdf, "Approval")
    pdf.set_font("Helvetica", "", 10)
    col = 56
    top = pdf.get_y() + 2
    for i, role in enumerate(("Prepared by", "Checked by", "Approved by")):
        x = 15 + i * (col + 6)
        pdf.set_xy(x, top)
        pdf.cell(col, 6, _txt(role))
        pdf.line(x, top + 18, x + col, top + 18)
        pdf.set_xy(x, top + 19)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(col, 5, "Signature / name / date")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 10)
    pdf.set_y(top + 28)

    return bytes(pdf.output())
