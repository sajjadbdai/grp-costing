"""Excel workbook checks: sheets, live formulas and editable cells."""

import unittest

try:
    from app import costing, xlsx_report
except ImportError:
    costing = xlsx_report = None


def _inputs(**over):
    base = {
        "shape_id": "box",
        "dims_mm": {"length": 2000.0, "width": 1000.0, "height": 500.0,
                    "thickness": 11.1},
        "options": {"open_top": False}, "qty": 2, "layup": "tank_heavy",
        "gelcoat": None, "mould_option": "need", "mould_cost": 250.0,
        "mould_life_qty": None, "plywood_m2": 2.0, "steel_kg": 10.0,
        "hardware_cost": 5.0, "resin_type": "iso", "paint": False,
        "extra_area_m2": 0.0, "delivery_bd": 40.0, "testing_bd": 25.0,
        "markup_pct": 10.0, "tax_pct": 10.0,
        "bought_ins": [{"label": "Aluminium door", "qty": 1, "unit": "no",
                        "rate": 120.0}],
        "openings_m2": 1.48,
        "recipe": dict(costing.DEFAULT_RECIPE), "rates": dict(costing.DEFAULT_RATES),
        "description": "Test tank", "drawing": "",
    }
    base.update(over)
    return base


CABIN_OPENINGS = [
    {"label": "Aluminium sliding window", "width_m": 0.8, "height_m": 1.0,
     "qty": 1},
    {"label": "Aluminium fixed window", "width_m": 0.8, "height_m": 1.0,
     "qty": 1},
    {"label": "Aluminium door (glass top, lock)", "width_m": 0.8,
     "height_m": 1.85, "qty": 1},
]


def _calc(inputs):
    return costing.calculate(
        inputs["shape_id"], inputs["dims_mm"], inputs["qty"], inputs["recipe"],
        inputs["rates"], inputs["options"], layup=inputs["layup"],
        gelcoat=inputs["gelcoat"], mould_option=inputs["mould_option"],
        mould_cost=inputs["mould_cost"], plywood_m2=inputs["plywood_m2"],
        steel_kg=inputs["steel_kg"], resin_type=inputs["resin_type"],
        mould_life_qty=inputs["mould_life_qty"], hardware_cost=inputs["hardware_cost"],
        paint=inputs["paint"], extra_area_m2=inputs["extra_area_m2"],
        delivery_bd=inputs["delivery_bd"], testing_bd=inputs["testing_bd"],
        markup_pct=inputs["markup_pct"], tax_pct=inputs["tax_pct"],
        bought_ins=inputs["bought_ins"], openings_m2=inputs["openings_m2"],
        openings=inputs.get("openings"))


@unittest.skipUnless(costing, "openpyxl not installed")
class XlsxTests(unittest.TestCase):
    def test_sheets_and_values(self):
        inputs = _inputs()
        wb = xlsx_report.build_workbook("Test tank", 2, _calc(inputs), inputs,
                                        inputs["rates"])
        self.assertEqual(wb.sheetnames, ["Inputs", "Take-off", "Costing"])
        ws = wb["Inputs"]
        csm_row = xlsx_report.MAT_START + 1
        self.assertAlmostEqual(ws.cell(row=csm_row, column=2).value, 0.53)
        self.assertEqual(ws.cell(row=csm_row, column=4).value,
                         "=B%d*1" % csm_row)
        lr = xlsx_report.LR
        self.assertAlmostEqual(ws.cell(row=lr + 1, column=2).value, 0.48)
        cr = xlsx_report.CR
        self.assertEqual(ws.cell(row=cr + 1, column=2).value, 2)
        self.assertAlmostEqual(ws.cell(row=cr + 2, column=2).value, 2.0)

    def test_takeoff_matches_parts(self):
        inputs = _inputs()
        calc = _calc(inputs)
        wb = xlsx_report.build_workbook("Test tank", 2, calc, inputs, inputs["rates"])
        ws = wb["Take-off"]
        self.assertEqual(ws.cell(row=12, column=1).value, calc["area_parts"][0]["label"])
        self.assertAlmostEqual(ws.cell(row=12, column=2).value,
                               round(calc["area_parts"][0]["area_m2"], 4))
        n = len([p for p in calc["area_parts"] if p["area_m2"] >= 0])
        self.assertEqual(ws.cell(row=12 + n, column=1).value, "TOTAL PER PIECE")
        self.assertIn("SUM(F12:F", ws.cell(row=12 + n, column=6).value)

    def test_costing_formulas_and_yellow_cells(self):
        inputs = _inputs()
        wb = xlsx_report.build_workbook("Test tank", 2, _calc(inputs), inputs,
                                        inputs["rates"])
        ws = wb["Costing"]
        self.assertIn("COST & SELLING PRICE", ws["A1"].value)
        found_resin = found_mould = False
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
            label = row[0].value or ""
            if label.startswith("Resin ("):
                found_resin = True
                self.assertIn("'Take-off'!K", row[1].value)
                self.assertIn("Inputs!$B$", row[1].value)
                self.assertTrue(row[3].value.startswith("=Inputs!D"),
                                "rate cell must be a live formula, got %r"
                                % row[3].value)
                self.assertEqual(row[4].value, "=B%d*D%d" % (row[0].row, row[0].row))
            if label == "Mould / plug share":
                found_mould = True
                self.assertIn("MAX(1,", row[1].value)
            if label == "Marine plywood 18 mm supports":
                self.assertEqual(row[3].fill.fgColor.rgb, "00FFFF00")
            if label == "Fabrication labour (all operations)":
                self.assertEqual(row[1].fill.fgColor.rgb, "00FFFF00")
                self.assertEqual(row[1].value, 1.0)
        self.assertTrue(found_resin and found_mould)
        summary = [r[0].value for r in ws.iter_rows(min_row=1, max_row=ws.max_row)]
        for needle in ("TOTAL COST", "SELLING PRICE (excl. VAT)",
                       "SELLING PRICE (incl. VAT)"):
            self.assertIn(needle, summary)

    def test_bought_ins_and_openings(self):
        inputs = _inputs()
        wb = xlsx_report.build_workbook("Test tank", 2, _calc(inputs), inputs,
                                        inputs["rates"])
        labels = [r[0].value for r in
                  wb["Costing"].iter_rows(min_row=1, max_row=wb["Costing"].max_row)]
        self.assertIn("Aluminium door", labels)
        ws = wb["Take-off"]
        self.assertEqual(ws.cell(row=5, column=1).value,
                         "Doors / windows (total from app)")
        self.assertAlmostEqual(ws.cell(row=5, column=2).value, 1.48)

    def test_classic_build(self):
        inputs = _inputs(layup="classic", shape_id="panel",
                         dims_mm={"length": 675.0, "width": 675.0,
                                  "thickness": 4.0, "flange": 100.0},
                         options={})
        wb = xlsx_report.build_workbook("Panel", 1, _calc(inputs), inputs,
                                        inputs["rates"])
        labels = [r[0].value for r in
                  wb["Costing"].iter_rows(min_row=1, max_row=wb["Costing"].max_row)]
        self.assertIn("Fiberglass (generic)", labels)


@unittest.skipUnless(costing, "openpyxl not installed")
class CabinXlsxTests(unittest.TestCase):
    def _cabin_inputs(self):
        recipe = dict(costing.DEFAULT_RECIPE)
        recipe["labour_hours"] = 107.3
        return _inputs(
            shape_id="cabin",
            dims_mm={"length": 1500.0, "width": 1500.0, "height": 2400.0,
                     "thickness": 4.0},
            options={}, layup="cabin_outer", mould_cost=600.0,
            delivery_bd=45.0, testing_bd=0.0, markup_pct=20.0, tax_pct=10.0,
            bought_ins=[{"label": "LED recessed down light", "qty": 1,
                         "unit": "no", "rate": 6.0}],
            openings_m2=0.0, openings=[dict(o) for o in CABIN_OPENINGS],
            recipe=recipe)

    def test_labour_operations_replace_single_row(self):
        inputs = self._cabin_inputs()
        wb = xlsx_report.build_workbook("Cabin", 2, _calc(inputs), inputs,
                                        inputs["rates"])
        rows = {r[0].value: r for r in
                wb["Costing"].iter_rows(min_row=1, max_row=wb["Costing"].max_row)}
        self.assertNotIn("Fabrication labour (all operations)", rows)
        self.assertIn("Mould preparation, wax & release", rows)
        self.assertIn("Electrical installation", rows)
        op = rows["Mould preparation, wax & release"]
        self.assertAlmostEqual(op[1].value, 6.0)
        self.assertEqual(op[1].fill.fgColor.rgb, "00FFFF00")
        self.assertEqual(op[4].value, "=B%d*D%d" % (op[0].row, op[0].row))
        subtotal = rows["Sub-total C"]
        self.assertIn("SUM(B", subtotal[1].value)
        self.assertIn("SUM(E", subtotal[4].value)

    def test_core_rows_use_live_takeoff_refs(self):
        inputs = self._cabin_inputs()
        wb = xlsx_report.build_workbook("Cabin", 2, _calc(inputs), inputs,
                                        inputs["rates"])
        rows = {r[0].value: r for r in
                wb["Costing"].iter_rows(min_row=1, max_row=wb["Costing"].max_row)}
        pu = rows["PU foam core 20 mm"]
        self.assertIn("SUMIF('Take-off'!O", pu[1].value)
        self.assertTrue(pu[3].value.startswith("=Inputs!D"),
                        "rate cell must be a live formula, got %r" % pu[3].value)
        self.assertIn("Plywood floor core 18 mm", rows)

    def test_takeoff_per_part_plies_coats_and_cores(self):
        inputs = self._cabin_inputs()
        wb = xlsx_report.build_workbook("Cabin", 2, _calc(inputs), inputs,
                                        inputs["rates"])
        ws = wb["Take-off"]
        self.assertEqual(ws.cell(row=12, column=1).value, "Walls - outer skin")
        self.assertEqual((ws.cell(row=12, column=7).value,
                          ws.cell(row=12, column=8).value), (3, 0))
        self.assertEqual((ws.cell(row=14, column=7).value,
                          ws.cell(row=14, column=8).value), (4, 1))
        self.assertEqual(ws.cell(row=13, column=12).value, "Flowcoat white")
        self.assertEqual(ws.cell(row=17, column=12).value, "None")
        self.assertEqual(ws.cell(row=12, column=5).value, "=$E$8")
        self.assertEqual(ws.cell(row=14, column=5).value, 0)
        self.assertEqual(ws.cell(row=13, column=15).value, "PU foam board")
        self.assertEqual(ws.cell(row=16, column=15).value, "Plywood 18 mm")
        self.assertIn("Inputs!$B$", ws.cell(row=12, column=13).value)

    def test_openings_prefilled_from_detail(self):
        inputs = self._cabin_inputs()
        wb = xlsx_report.build_workbook("Cabin", 2, _calc(inputs), inputs,
                                        inputs["rates"])
        ws = wb["Take-off"]
        self.assertEqual(ws.cell(row=5, column=1).value,
                         "Aluminium sliding window")
        self.assertAlmostEqual(ws.cell(row=5, column=2).value, 0.8)
        self.assertAlmostEqual(ws.cell(row=7, column=2).value, 0.8)
        self.assertAlmostEqual(ws.cell(row=7, column=3).value, 1.85)
        self.assertEqual(ws.cell(row=8, column=5).value, "=SUM(E5:E7)")

    def test_inputs_gain_foam_and_flowcoat(self):
        inputs = self._cabin_inputs()
        wb = xlsx_report.build_workbook("Cabin", 2, _calc(inputs), inputs,
                                        inputs["rates"])
        ws = wb["Inputs"]
        foam_row = xlsx_report.MAT_START + len(xlsx_report.MATERIALS) - 1
        self.assertEqual(ws.cell(row=foam_row, column=1).value,
                         "PU foam board 20 mm")
        self.assertAlmostEqual(ws.cell(row=foam_row, column=2).value, 4.5)
        flow_row = xlsx_report.LR + 9
        self.assertEqual(ws.cell(row=flow_row, column=1).value,
                         "Flowcoat coverage")
        self.assertAlmostEqual(ws.cell(row=flow_row, column=2).value, 0.4)
        self.assertEqual(ws.cell(row=xlsx_report.LR + 10, column=1).value,
                         "ISO resin skin-coat share")
        self.assertEqual(ws.cell(row=xlsx_report.LR + 11, column=1).value,
                         "Consumables")
        self.assertEqual(ws.cell(row=xlsx_report.LR + 12, column=1).value,
                         "Bonding paste / filler per piece")


if __name__ == "__main__":
    unittest.main()
