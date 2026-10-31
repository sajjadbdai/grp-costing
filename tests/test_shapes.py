"""Geometry checks against independently worked values."""

import math
import unittest

from app import shapes


class PanelTests(unittest.TestCase):
    def test_legacy_panel_numbers(self):
        # Original MVP defaults: 675 x 675, flange 100 (mm).
        result = shapes.panel_area(675, 675, 100)
        self.assertAlmostEqual(result["area_m2"], 0.765625)
        parts = {p["label"]: p["area_m2"] for p in result["parts"]}
        self.assertAlmostEqual(parts["Panel face"], 0.455625)
        self.assertAlmostEqual(parts["All-round flange border"], 0.31)

    def test_no_flange(self):
        result = shapes.panel_area(1000, 500, 0)
        self.assertAlmostEqual(result["area_m2"], 0.5)

    def test_invalid(self):
        with self.assertRaises(shapes.ShapeError):
            shapes.panel_area(0, 100)
        with self.assertRaises(shapes.ShapeError):
            shapes.panel_area(100, -5)
        with self.assertRaises(shapes.ShapeError):
            shapes.panel_area(100, 100, -1)
        with self.assertRaises(shapes.ShapeError):
            shapes.panel_area("wide", 100)


class CylinderTests(unittest.TestCase):
    def test_open_tube(self):
        result = shapes.cylinder_area(400, 1000, False, False)
        self.assertAlmostEqual(result["area_m2"], math.pi * 0.4 * 1.0)

    def test_tank_with_bottom(self):
        # D=1m H=2m: pi*1*2 + pi/4 = 7.0685835 m2.
        result = shapes.cylinder_area(1000, 2000, True, False)
        self.assertAlmostEqual(result["area_m2"], 7.0685835, places=6)

    def test_closed_both_ends(self):
        result = shapes.cylinder_area(500, 500, True, True)
        expect = math.pi * 0.5 * 0.5 + 2 * math.pi * 0.25 * 0.25
        self.assertAlmostEqual(result["area_m2"], expect)

    def test_invalid(self):
        with self.assertRaises(shapes.ShapeError):
            shapes.cylinder_area(-100, 500)


class ReducerTests(unittest.TestCase):
    def test_frustum(self):
        # 600/400 dia, 500 high: pi*(0.3+0.2)*hypot(0.1, 0.5) = 0.80095 m2.
        result = shapes.reducer_area(600, 400, 500)
        self.assertAlmostEqual(result["area_m2"], 0.80095, places=4)
        self.assertEqual(result["warnings"], [])

    def test_swapped_diameters_warn(self):
        result = shapes.reducer_area(400, 600, 500)
        self.assertTrue(result["warnings"])
        self.assertAlmostEqual(result["area_m2"], 0.80095, places=4)

    def test_invalid(self):
        with self.assertRaises(shapes.ShapeError):
            shapes.reducer_area(600, 0, 500)


class RegistryTests(unittest.TestCase):
    def test_shape_ids(self):
        self.assertEqual(set(shapes.SHAPE_IDS), {"panel", "cylinder", "reducer"})

    def test_unknown_shape(self):
        with self.assertRaises(shapes.ShapeError):
            shapes.get_shape("sphere")

    def test_compute_area_dispatch(self):
        panel = shapes.compute_area("panel", {"length": 1000, "width": 1000})
        self.assertAlmostEqual(panel["area_m2"], 1.0)
        tube = shapes.compute_area("cylinder", {"diameter": 400, "height": 1000},
                                   {"closed_bottom": False})
        self.assertAlmostEqual(tube["area_m2"], math.pi * 0.4)
        cone = shapes.compute_area("reducer", {"d_large": 600, "d_small": 400, "height": 500})
        self.assertAlmostEqual(cone["area_m2"], 0.80095, places=4)


if __name__ == "__main__":
    unittest.main()