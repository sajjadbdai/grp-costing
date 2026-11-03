"""Laminate schedule checks: uptake ratios, thickness and catalogue."""

import unittest

from app import layup


class UptakeTests(unittest.TestCase):
    def test_csm_resin_ratio(self):
        # Enclosure: CSM450 0.9 kg, CSM300 0.6 kg, WR600 0.6 kg per m2.
        glass = layup.schedule_glass_per_m2("enclosure")
        self.assertAlmostEqual(glass["csm450"], 0.9)
        self.assertAlmostEqual(glass["csm300"], 0.6)
        self.assertAlmostEqual(glass["wr600"], 0.6)
        # 0.9*2.2 + 0.6*2.2 + 0.6*1.3 = 4.08 kg resin per m2.
        self.assertAlmostEqual(layup.schedule_resin_per_m2("enclosure"), 4.08)

    def test_woven_roving_ratio(self):
        # WR600 at 1.3:1 -> 0.78 kg resin per m2 per ply.
        glass = layup.schedule_glass_per_m2("tank_heavy")
        self.assertAlmostEqual(glass["csm450"], 0.9)
        self.assertAlmostEqual(glass["csm300"], 0.3)
        self.assertAlmostEqual(glass["csm600"], 1.2)
        self.assertAlmostEqual(glass["wr600"], 3.6)
        self.assertAlmostEqual(layup.schedule_resin_per_m2("tank_heavy"),
                               0.9 * 2.2 + 0.3 * 2.2 + 1.2 * 2.3 + 3.6 * 1.3)

    def test_gelcoat_allowance(self):
        self.assertAlmostEqual(layup.GELCOAT_KG_M2, 0.55)
        self.assertAlmostEqual(layup.GELCOAT_MM, 0.5)
        self.assertAlmostEqual(layup.schedule_gelcoat_per_m2("enclosure"), 0.60)
        self.assertAlmostEqual(layup.schedule_gelcoat_per_m2("tank_heavy"), 0.65)


class ThicknessTests(unittest.TestCase):
    def test_schedule_thickness(self):
        self.assertAlmostEqual(layup.schedule_thickness("enclosure"), 5.1)
        self.assertAlmostEqual(layup.schedule_thickness("tank_medium"), 5.9)
        self.assertAlmostEqual(layup.schedule_thickness("boat_hull"), 6.6)

    def test_gelcoat_toggle(self):
        with_gel = layup.schedule_thickness("panel_struct", True)
        without = layup.schedule_thickness("panel_struct", False)
        self.assertAlmostEqual(with_gel - without, 0.5)

    def test_classic_has_no_thickness(self):
        self.assertAlmostEqual(layup.schedule_thickness("classic"), 0.0)


class LabourTests(unittest.TestCase):
    def test_tank_example(self):
        # D1280 x L3000 closed tank ~14.64 m2, 11 plies -> ~18.8 hr.
        self.assertAlmostEqual(layup.estimate_labour_hours(14.64, "tank_heavy"),
                               18.8, places=1)

    def test_scales_with_area_and_plies(self):
        small = layup.estimate_labour_hours(1.0, "enclosure")
        big = layup.estimate_labour_hours(10.0, "enclosure")
        self.assertGreater(big, small * 4)
        heavy = layup.estimate_labour_hours(5.0, "tank_heavy")
        light = layup.estimate_labour_hours(5.0, "enclosure")
        self.assertGreater(heavy, light)

    def test_gelcoat_adds_time(self):
        with_gel = layup.estimate_labour_hours(10.0, "panel_struct", True)
        without = layup.estimate_labour_hours(10.0, "panel_struct", False)
        self.assertAlmostEqual(with_gel - without, 0.5)

    def test_classic_and_unknown(self):
        self.assertGreater(layup.estimate_labour_hours(2.0, "classic"), 1.0)
        with self.assertRaises(layup.LayupError):
            layup.estimate_labour_hours(2.0, "carbon")


class CatalogueTests(unittest.TestCase):
    def test_roving_never_against_gelcoat(self):
        for sid in layup.SCHEDULE_IDS:
            layers = layup.SCHEDULES[sid]["layers"]
            if layers:
                self.assertTrue(layers[0].startswith("csm"),
                                "%s: first ply must be CSM skin" % sid)

    def test_unknown_schedule(self):
        with self.assertRaises(layup.LayupError):
            layup.get_schedule("carbon")

    def test_labels_carry_thickness(self):
        self.assertNotIn("mm", layup.schedule_label("classic"))
        self.assertIn("5.9 mm", layup.schedule_label("tank_medium"))

    def test_dome_schedules(self):
        outer = layup.schedule_glass_per_m2("dome_outer")
        self.assertAlmostEqual(outer["csm450"], 2.7)
        self.assertAlmostEqual(outer["wr600"], 0.6)
        self.assertAlmostEqual(layup.schedule_resin_per_m2("dome_outer"), 6.72)
        self.assertAlmostEqual(layup.schedule_thickness("dome_outer"), 7.4)
        self.assertFalse(layup.get_schedule("dome_outer")["gelcoat"])
        inner = layup.schedule_glass_per_m2("dome_inner")
        self.assertAlmostEqual(inner["csm450"], 1.8)
        self.assertAlmostEqual(layup.schedule_thickness("dome_inner"), 4.4)

    def test_cabin_schedules(self):
        outer = layup.schedule_glass_per_m2("cabin_outer")
        self.assertAlmostEqual(outer["csm450"], 1.35)
        inner = layup.schedule_glass_per_m2("cabin_inner")
        self.assertAlmostEqual(inner["csm450"], 0.9)
        roof = layup.schedule_glass_per_m2("cabin_roof")
        self.assertAlmostEqual(roof["csm450"], 1.8)
        self.assertAlmostEqual(roof["wr600"], 0.6)
        self.assertAlmostEqual(layup.schedule_thickness("cabin_outer"), 3.8)
        self.assertAlmostEqual(layup.schedule_gelcoat_per_m2("cabin_inner"), 0.4)
        self.assertAlmostEqual(layup.schedule_gelcoat_per_m2("cabin_floor"), 0.4)


class CabinLabourTests(unittest.TestCase):
    def test_operation_total(self):
        ops = layup.estimate_cabin_labour(33.9286, 3, 1)
        self.assertEqual(len(ops), 8)
        self.assertAlmostEqual(sum(h for _, h in ops), 98.5, places=1)
        labels = [label for label, _ in ops]
        self.assertIn("Electrical installation", labels)

    def test_unwired_shell_skips_electrical(self):
        ops = layup.estimate_cabin_labour(33.9286, 3, 0)
        self.assertEqual(len(ops), 7)
        labels = [label for label, _ in ops]
        self.assertNotIn("Electrical installation", labels)

    def test_scales_with_area_and_openings(self):
        small = sum(h for _, h in layup.estimate_cabin_labour(10.0, 1, 0))
        big = sum(h for _, h in layup.estimate_cabin_labour(20.0, 3, 0))
        self.assertGreater(big, small)


if __name__ == "__main__":
    unittest.main()
