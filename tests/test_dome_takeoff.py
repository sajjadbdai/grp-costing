"""Dome take-off truth (DOME.pdf Dome #1) + Claude-file engine parity.

Dome #1: internal dia 4000, external dia 4230, rise ~1935 inner
(2050 outer with the 115 mm sandwich build-up), 285 mm ring beam,
100 mm PU sandwich, paint finish both faces (no gelcoat).
"""

import math
import unittest

from app import costing, layup, shapes


def _cap(a, h):
    r = (a * a + h * h) / (2.0 * h)
    return 2.0 * math.pi * r * h


class DomeTruthTests(unittest.TestCase):
    def test_dome1_full_takeoff(self):
        result = shapes.dome_area(4230, 2050, 4000, ring_mm=285,
                                  joints_n=12, joint_w_mm=150)
        parts = {p["label"]: p for p in result["parts"]}
        outer = _cap(2.115, 2.05)
        inner = _cap(2.0, 1.935)
        self.assertAlmostEqual(parts["Dome - outer skin"]["area_m2"],
                               outer, places=3)
        self.assertAlmostEqual(parts["Dome - inner skin"]["area_m2"],
                               inner, places=3)
        self.assertAlmostEqual(outer, 27.256, places=2)
        self.assertAlmostEqual(inner, 24.331, places=2)
        self.assertAlmostEqual(parts["Ring beam - outer"]["area_m2"],
                               math.pi * 4.23 * 0.285, places=3)
        self.assertAlmostEqual(parts["Ring beam - inner"]["area_m2"],
                               math.pi * 4.0 * 0.285, places=3)
        # Site joint strips: 12 joints x outer meridian arc x 0.15 m.
        sphere_r = (2.115 ** 2 + 2.05 ** 2) / (2.0 * 2.05)
        arc = sphere_r * math.acos((sphere_r - 2.05) / sphere_r)
        self.assertAlmostEqual(parts["Site joint strips"]["area_m2"],
                               12 * arc * 0.15, places=3)
        self.assertAlmostEqual(result["area_m2"],
                               outer + inner + math.pi * 4.23 * 0.285
                               + math.pi * 4.0 * 0.285 + 12 * arc * 0.15,
                               places=3)
        # PU core is the mean sandwich area (between the skins).
        self.assertAlmostEqual(
            parts["Dome - inner skin"]["core"]["area_m2"],
            (outer + inner) / 2, places=3)
        self.assertEqual(parts["Dome - outer skin"]["coat"], "paint")
        self.assertEqual(parts["Dome - inner skin"]["layup"], "dome_inner")

    def test_dome_defaults_stay_single_cap(self):
        result = shapes.dome_area(4000, 2000)
        self.assertEqual(len(result["parts"]), 1)
        self.assertAlmostEqual(result["area_m2"], 25.1327, places=3)

    def test_dome1_costing_complete(self):
        calc = costing.calculate(
            "dome", {"diameter": 4230.0, "height": 2050.0,
                     "diameter_inner": 4000.0, "thickness": 8.0,
                     "ring_mm": 285.0, "joints_n": 12.0,
                     "joint_w_mm": 150.0},
            layup="dome_outer", paint=True, paste_kg=8.0,
            recipe={"labour_hours": 161.3})
        self.assertAlmostEqual(calc["area_m2"], 64.82, places=1)
        self.assertAlmostEqual(calc["gelcoat_kg"], 0.0)
        self.assertAlmostEqual(calc["tissue_m2"], 0.0)  # paint, no gelcoat
        self.assertAlmostEqual(calc["core_m2"]["pufoam"], 29.48 * 1.1,
                               places=1)
        self.assertGreater(calc["material_bd"], 500.0)  # both skins + core
        labels = [line["label"] for line in calc["lines"]]
        self.assertIn("Bonding paste / filler", labels)
        self.assertIn("Paint / topcoat", labels)
        self.assertNotIn("Labour", labels)  # operation lines instead
        self.assertEqual(len(calc["labour_ops"]), 7)  # unwired: no elec op

    def test_arrester_is_not_a_wiring_point(self):
        calc = costing.calculate(
            "dome", {"diameter": 4230.0, "height": 2050.0,
                     "diameter_inner": 4000.0, "thickness": 8.0,
                     "ring_mm": 285.0, "joints_n": 12.0,
                     "joint_w_mm": 150.0},
            layup="dome_outer", paint=True, paste_kg=8.0,
            bought_ins=[{"label": "Lightning arrester", "qty": 1,
                         "unit": "no", "rate": 6.0}],
            recipe={"labour_hours": 161.3})
        self.assertEqual(len(calc["labour_ops"]), 7)
        labels = [line["label"] for line in calc["lines"]]
        self.assertNotIn("Labour - Electrical installation", labels)


class CabinTakeoffTests(unittest.TestCase):
    def test_reveals_and_bonding_strips(self):
        openings = [
            {"label": "W1", "width_m": 0.8, "height_m": 1.0, "qty": 1},
            {"label": "W2", "width_m": 0.8, "height_m": 1.0, "qty": 1},
            {"label": "D1", "width_m": 0.8, "height_m": 1.85, "qty": 1},
        ]
        result = shapes.cabin_area(1500, 1500, 2400, openings_count=3,
                                   openings=openings)
        parts = {p["label"]: p["area_m2"] for p in result["parts"]}
        self.assertAlmostEqual(parts["Reveals around openings"],
                               (3.6 + 3.6 + 5.3) * 0.05, places=4)
        self.assertAlmostEqual(parts["Joint / corner bonding strips"],
                               (4 * 2.2 + 4 * 3.0) * 0.15, places=4)


class EngineParityTests(unittest.TestCase):
    def _enclosure(self, **kwargs):
        params = {"recipe": {"wastage_pct": 0.0, "labour_hours": 0.0,
                             "overhead_pct": 0.0},
                  "layup": "enclosure"}
        params.update(kwargs)
        dims = {"length": 1000.0, "width": 1000.0, "thickness": 5.1,
                "flange": 0.0}
        return costing.calculate("panel", dims, **params)

    def test_mekp_on_resin_plus_gelcoat(self):
        result = self._enclosure(recipe={"wastage_pct": 0.0,
                                         "labour_hours": 0.0,
                                         "overhead_pct": 0.0,
                                         "mekp_pct": 1.5})
        self.assertAlmostEqual(result["mekp_kg"], (4.08 + 0.6) * 0.015)

    def test_iso_skin_coat_split(self):
        result = self._enclosure()
        self.assertAlmostEqual(result["iso_kg"], 4.08 * 0.15)
        labels = [line["label"] for line in result["lines"]]
        self.assertIn("ISO resin (skin coat)", labels)
        gp_line = [line for line in result["lines"]
                   if line["label"].startswith("Resin (")][0]
        self.assertAlmostEqual(gp_line["qty"], 4.08 * 0.85)

    def test_tissue_behind_gelcoat(self):
        result = self._enclosure()
        self.assertAlmostEqual(result["tissue_m2"], 1.0)
        labels = [line["label"] for line in result["lines"]]
        self.assertIn("Surface tissue", labels)

    def test_consumables_percent_of_grp_materials(self):
        result = self._enclosure()
        basket = sum(line["amount"] for line in result["lines"]
                     if line["label"] not in ("Consumables (% of GRP materials)",
                                              "Labour"))
        self.assertAlmostEqual(result["consumables_bd"], basket * 0.05)
        self.assertGreater(result["consumables_bd"], 0.0)

    def test_labour_coefficients(self):
        ops = layup.estimate_cabin_labour(33.9286, 3, 1)
        self.assertEqual(len(ops), 8)
        by_label = dict(ops)
        self.assertAlmostEqual(by_label["Mould preparation, wax & release"],
                               6.0)
        self.assertAlmostEqual(by_label["Gelcoat + lamination"],
                               33.9286 * 1.062, places=1)
        self.assertAlmostEqual(by_label["Electrical installation"], 1.3,
                               places=2)
        self.assertAlmostEqual(sum(h for _, h in ops), 98.5, places=1)


if __name__ == "__main__":
    unittest.main()
