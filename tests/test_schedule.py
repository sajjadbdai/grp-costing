"""Bought-in schedule reader checks."""

import unittest

from app import schedule

CABIN_TEXT = """
PLAN GFPF#24
Sliding Window -W1 800 x 1000
Fixed Window -W2 800 x 1000
DOOR 800 x 1850
LED RECESSED ROUND DOWN LIGHT (CEILING MOUNTED) QTY: 1
1 WAY SWITCH 1200MM ABOVE FFL QTY: 1
13A 2 GANG SWITCH SHUTTERED SOCKET QTY: 2
MAIN DISTRIBUTION BOARD (DB) SINGLE PHASE QTY: 1
SPLIT WINDOW A/C UNIT - 1.5 TON QTY: 1
"""


class ParseTests(unittest.TestCase):
    def test_cabin_schedule(self):
        found = schedule.parse_schedule(CABIN_TEXT)
        labels = [i["label"] for i in found["items"]]
        for needle in ("Aluminium sliding window", "Aluminium fixed window",
                       "Split AC 1.5 ton (0 if client supplies)",
                       "LED recessed down light", "13A 2-gang switched socket",
                       "Single-phase DB with MCBs/RCD", "1-way switch",
                       "GRP door"):
            self.assertIn(needle, labels)
        qtys = {i["label"]: i["qty"] for i in found["items"]}
        self.assertEqual(qtys["13A 2-gang switched socket"], 2)

    def test_openings_from_drawing_dims(self):
        found = schedule.parse_schedule(CABIN_TEXT)
        self.assertAlmostEqual(found["openings_m2"], 0.8 + 0.8 + 1.48)
        sources = {o["source"] for o in found["openings"]}
        self.assertEqual(sources, {"drawing"})

    def test_standard_sizes_fallback(self):
        found = schedule.parse_schedule("one door and a fixed window here")
        self.assertAlmostEqual(found["openings_m2"], 1.48 + 0.8)
        labels = [i["label"] for i in found["items"]]
        self.assertEqual(labels, ["Aluminium fixed window",
                                  "GRP door",
                                  "Silicone sealant, fixings, anchor bolts"])

    def test_no_false_positives(self):
        found = schedule.parse_schedule("GRP water tank 2000 litre, indoor use")
        self.assertEqual(found["items"], [])
        self.assertAlmostEqual(found["openings_m2"], 0.0)

    def test_empty_text(self):
        found = schedule.parse_schedule("")
        self.assertEqual(found["items"], [])
        self.assertEqual(found["openings"], [])

    def test_allowance_lots_follow_detected_items(self):
        found = schedule.parse_schedule(CABIN_TEXT)
        labels = [i["label"] for i in found["items"]]
        self.assertEqual(len(found["items"]), 11)
        self.assertEqual(labels[-3:], ["Cables, conduits, boxes (per electrical point)",
                                       "AC installation (copper pipe, bracket, drain)",
                                       "Silicone sealant, fixings, anchor bolts"])
        sources = {i["source"] for i in found["items"][-3:]}
        self.assertEqual(sources, {"allowance"})

    def test_allowances_need_related_work(self):
        found = schedule.parse_schedule("13A socket and 1-way switch, no doors")
        labels = [i["label"] for i in found["items"]]
        self.assertIn("Cables, conduits, boxes (per electrical point)", labels)
        self.assertNotIn("AC installation (copper pipe, bracket, drain)", labels)
        self.assertNotIn("Silicone sealant, fixings, anchor bolts", labels)

    def test_fitted_flag(self):
        self.assertTrue(schedule.parse_schedule(CABIN_TEXT)["fitted"])
        self.assertTrue(schedule.parse_schedule("door plus sliding window")["fitted"])
        self.assertFalse(schedule.parse_schedule("GRP water tank 2000 litre")["fitted"])
        self.assertFalse(schedule.parse_schedule("a door with no windows")["fitted"])

    def test_job_qty(self):
        self.assertEqual(schedule.parse_schedule("QTY : 2 NOS")["job_qty"], 2)
        self.assertEqual(schedule.parse_job_qty("qty:12 nos"), 12)
        self.assertIsNone(schedule.parse_job_qty("QTY:\n1\n1 NO"))
        self.assertIsNone(schedule.parse_job_qty("no quantity here"))

    def test_overall_dims(self):
        text = "GRP SECURITY CABIN Overall Size:-L. 1500 mm X W.1500mm X H.2400 mm"
        self.assertEqual(schedule.parse_schedule(text)["overall"],
                         {"length": 1500, "width": 1500, "height": 2400})
        self.assertIsNone(schedule.parse_overall_dims("1500 x 1500 x 2400"))

    def test_tolerant_overall_and_internal_dims(self):
        self.assertEqual(
            schedule.parse_overall_dims("Overall Size: L 1500 X W 1500 X H 2400"),
            {"length": 1500, "width": 1500, "height": 2400})
        self.assertEqual(
            schedule.parse_internal_dims(
                "Internal Size:-L. 1450mm X W.1450mm X H.2200 mm"),
            {"length": 1450, "width": 1450, "height": 2200})
        self.assertIsNone(schedule.parse_internal_dims("no internal line"))

    def test_ocr_variants_fire(self):
        found = schedule.parse_schedule(
            "SPLIT WINDOW AC UNIT - (1.5 TON)\n"
            "16A DOUBLE POLE SWITCH WITH NEON INDICATOR")
        labels = [i["label"] for i in found["items"]]
        self.assertIn("Split AC 1.5 ton (0 if client supplies)", labels)
        self.assertIn("45A DP switch with neon (AC)", labels)
        self.assertIn("AC installation (copper pipe, bracket, drain)", labels)

    def test_variant_words_need_not_be_first_occurrence(self):
        filler = "pad " * 120
        found = schedule.parse_schedule(
            "13A 2 GANG SWITCH SHUTTERED SOCKET\n" + filler +
            "16A DOUBLE POLE SWITCH WITH NEON INDICATOR")
        labels = [i["label"] for i in found["items"]]
        self.assertIn("45A DP switch with neon (AC)", labels)

    def test_qty_ignores_ratings_and_job_qty(self):
        found = schedule.parse_schedule(
            "LED RECESSED ROUND DOWN LIGHT\nQTY\n13A 2 GANG SWITCH\n"
            "Sliding Window W1 800x1000\n1 NO\nQTY : 2 NOS")
        qtys = {i["label"]: i["qty"] for i in found["items"]}
        self.assertEqual(qtys["LED recessed down light"], 1)
        self.assertEqual(qtys["Aluminium sliding window"], 1)
        self.assertEqual(found["job_qty"], 2)

    def test_finishes_and_supports(self):
        text = ("EXTERNAL WALL COLOR - BEIGE (RAL1001), INTERNAL ROUGH FINISH "
                "COLOR - WHITE (RAL 9010), GI PIPE SUPPORTS, plywood core")
        found = schedule.parse_schedule(text)
        for needle in ("RAL 1001", "RAL 9010", "beige", "white",
                       "rough finish"):
            self.assertIn(needle, found["finishes"])
        for needle in ("gi pipe", "supports", "plywood"):
            self.assertIn(needle, found["supports"])
        self.assertEqual(schedule.parse_finishes("no colors here"), [])
        self.assertEqual(schedule.parse_support_mentions("plain laminate"), [])


DOME_TEXT = """
GRP DOME WITH EXTERNAL AND INTERNAL SURFACE SMOOTH PAINT FINISH
INTERNAL DIA. 4000 MM AS PER IFC DRAWING
GRP WALL PANEL INTERNAL 5MM THICK
GRP WALL PANEL EXTERNAL 8 MM THICK
100 MM THICK GLASS WOOL INSULATION
100 MM THICK PU FOAM INSULATION
48.3 MM DIA. x 3.6 MM THICK GI PIPE ROLLED TO SHAPE -8
250 x 150 x10mm THICK PAINTED MS BASE PLATE -4 Nos.
102 x 51 x 8 MM GALVANIZED MS C-CHANNEL RING
M14 SS 316 GRADE 160 MM LONG BOLT - 4 nos
1.0m DIA. FIBERGLASS GRP SPHERE (thick 6mm) (DIA 1000mm)
METALLIC GOLD FINISH (RAL 1036 CC4)
LIGHTNING ARRESTER (REFER TO ELECTRICAL)
"""


class RoundProductTests(unittest.TestCase):
    def test_diameters(self):
        self.assertEqual(
            schedule.parse_diameters(DOME_TEXT),
            ["internal dia 4000 mm", "dia 1000 mm"])

    def test_panels_and_insulation(self):
        self.assertEqual(
            schedule.parse_panel_mm(DOME_TEXT),
            ["internal 5 mm", "external 8 mm", "sphere 6 mm"])
        self.assertEqual(
            schedule.parse_insulation(DOME_TEXT),
            ["100 mm glass wool", "100 mm PU foam"])

    def test_steel_parts(self):
        parts = schedule.parse_steel_parts(DOME_TEXT)
        self.assertIn("GI pipe 48.3 dia x 3.6 thk (8 nos)", parts)
        self.assertIn("base plate 250x150x10 (4 nos)", parts)
        self.assertIn("C-channel 102x51x8 ring", parts)
        self.assertIn("M14 bolts 4 nos", parts)

    def test_arrester_item_priced(self):
        found = schedule.parse_schedule(DOME_TEXT)
        labels = {i["label"]: i["rate"] for i in found["items"]}
        self.assertIn("Lightning arrester", labels)
        self.assertEqual(labels["Lightning arrester"], 6.0)
        self.assertEqual(found["openings_m2"], 0)
        self.assertIsNone(found["job_qty"])

    def test_doors_windows_price_per_m2(self):
        found = schedule.parse_schedule(CABIN_TEXT)
        rates = {i["label"]: i["rate"] for i in found["items"]}
        self.assertAlmostEqual(rates["Aluminium sliding window"], 56.25 * 0.8)
        self.assertAlmostEqual(rates["Aluminium fixed window"], 43.75 * 0.8)
        self.assertAlmostEqual(rates["GRP door"], 81.0 * 1.48)
        basis = {i["label"]: i["basis"] for i in found["items"]}
        self.assertIn("BD/m2", basis["Aluminium sliding window"])

    def test_wiring_allowance_per_point(self):
        found = schedule.parse_schedule(CABIN_TEXT)
        qtys = {i["label"]: (i["qty"], i["unit"]) for i in found["items"]}
        qty, unit = qtys["Cables, conduits, boxes (per electrical point)"]
        self.assertEqual(unit, "point")
        self.assertEqual(qty, found["elec_points"])
        self.assertGreaterEqual(qty, 1)

    def test_dome_guess(self):
        text = ("INTERNAL DIA. 4000 MM\n1935\n285\n4570\n4230\n4380\n"
                "GRP WALL PANEL INTERNAL 5MM THICK\n"
                "GRP WALL PANEL EXTERNAL 8 MM THICK\n")
        self.assertEqual(schedule.parse_dome_guess(text),
                         {"inner_dia": 4000.0, "outer_dia": 4230,
                          "rise": 1935, "ring": 285, "base_dia": 4380,
                          "skin_outer": 8.0, "skin_inner": 5.0})
        self.assertIsNone(schedule.parse_dome_guess("no diameters here"))

    def test_ral_suffix_and_support_dedupe(self):
        found = schedule.parse_schedule(DOME_TEXT)
        self.assertIn("RAL 1036 CC4", found["finishes"])
        self.assertIn("gi pipe", found["supports"])
        self.assertNotIn("gi", found["supports"])


class DoorMaterialTests(unittest.TestCase):
    def _door_labels(self, text):
        found = schedule.parse_schedule(text)
        return [i["label"] for i in found["items"]
                if i["kind"] == "door"]

    def test_bare_door_is_grp(self):
        self.assertEqual(self._door_labels("DOOR 800 x 1850"), ["GRP door"])

    def test_aluminium_door_named(self):
        self.assertEqual(self._door_labels("ALUMINIUM DOOR 900 x 2100"),
                         ["Aluminium door (glass top, lock)"])
        self.assertEqual(self._door_labels("aluminum door"),
                         ["Aluminium door (glass top, lock)"])

    def test_steel_door_named(self):
        for text in ("SS DOOR 900 x 2100", "stainless steel door",
                     "steel door"):
            self.assertEqual(self._door_labels(text), ["Steel door"])

    def test_distant_ss_is_not_a_steel_door(self):
        text = "SS Hinges\n" + "1360\n" * 20 + "Double Panel Door"
        self.assertEqual(self._door_labels(text), ["GRP door"])

    def test_grp_door_stays_grp(self):
        self.assertEqual(self._door_labels("GRP DOOR"), ["GRP door"])

    def test_grp_door_rate_unchanged(self):
        found = schedule.parse_schedule("DOOR 800 x 1850")
        rates = {i["label"]: (i["rate"], i["basis"]) for i in found["items"]}
        rate, basis = rates["GRP door"]
        self.assertAlmostEqual(rate, 81.0 * 1.48)
        self.assertIn("BD/m2", basis)


if __name__ == "__main__":
    unittest.main()
