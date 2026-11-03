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


class BoxTests(unittest.TestCase):
    def test_open_top(self):
        # 1x1x1 m: walls 4 + bottom 1 = 5 m2.
        result = shapes.box_area(1000, 1000, 1000, open_top=True)
        self.assertAlmostEqual(result["area_m2"], 5.0)

    def test_closed_lid(self):
        result = shapes.box_area(2000, 1000, 500, open_top=False)
        self.assertAlmostEqual(result["area_m2"], 2 * (2 * 0.5 + 1 * 0.5) + 2 * 2 * 1)

    def test_invalid(self):
        with self.assertRaises(shapes.ShapeError):
            shapes.box_area(100, 100, 0)


class CustomTests(unittest.TestCase):
    def test_measured_area(self):
        result = shapes.custom_area(12.5)
        self.assertAlmostEqual(result["area_m2"], 12.5)

    def test_invalid(self):
        with self.assertRaises(shapes.ShapeError):
            shapes.custom_area(0)
        with self.assertRaises(shapes.ShapeError):
            shapes.custom_area(-3)


class CabinTests(unittest.TestCase):
    def test_sandwich_parts(self):
        # 1500 x 1500 x 2400 cabin: inner 1450 x 1450 x 2200, 3 openings.
        result = shapes.cabin_area(1500, 1500, 2400, openings_count=3)
        parts = {p["label"]: p["area_m2"] for p in result["parts"]}
        self.assertAlmostEqual(parts["Walls - outer skin"], 6.0 * 2.2)
        self.assertAlmostEqual(parts["Walls - inner skin"], 5.8 * 2.2)
        self.assertAlmostEqual(parts["Roof - top skin"], 1.7 * 1.7)
        self.assertAlmostEqual(parts["Ceiling - inner skin"], 1.45 * 1.45)
        self.assertAlmostEqual(parts["Floor - top laminate"], 1.45 * 1.45)
        self.assertAlmostEqual(parts["Base - underside skin"], 1.54 * 1.54)
        self.assertAlmostEqual(parts["Plinth"], 6.16 * 0.2)
        self.assertAlmostEqual(parts["Joint / corner bonding strips"],
                               (4 * 2.2 + 4 * 3.0) * 0.15)
        self.assertAlmostEqual(parts["Cornice moulding"], 6.8 * 0.35)
        self.assertAlmostEqual(parts["Hoods over openings"], 3 * 0.35)
        self.assertAlmostEqual(result["area_m2"], sum(parts.values()))

    def test_part_schedules_and_cores(self):
        result = shapes.cabin_area(1500, 1500, 2400, openings_count=3)
        by_label = {p["label"]: p for p in result["parts"]}
        self.assertEqual(by_label["Walls - outer skin"]["layup"], "cabin_outer")
        self.assertEqual(by_label["Walls - inner skin"]["layup"], "cabin_inner")
        self.assertEqual(by_label["Roof - top skin"]["layup"], "cabin_roof")
        self.assertEqual(by_label["Floor - top laminate"]["layup"], "cabin_floor")
        self.assertTrue(by_label["Walls - outer skin"]["wall"])
        self.assertTrue(by_label["Walls - inner skin"]["wall"])
        self.assertNotIn("wall", by_label["Roof - top skin"])
        self.assertEqual(by_label["Walls - inner skin"]["core"]["material"], "pufoam")
        self.assertEqual(by_label["Roof - top skin"]["core"]["material"], "pufoam")
        self.assertEqual(by_label["Floor - top laminate"]["core"]["material"], "plywood")
        self.assertNotIn("core", by_label["Ceiling - inner skin"])
        self.assertEqual(by_label["Base - underside skin"]["coat"], "none")
        self.assertEqual(by_label["Ceiling - inner skin"]["coat"], "flowcoat")

    def test_hoods_follow_opening_count(self):
        two = shapes.cabin_area(1500, 1500, 2400, openings_count=2)
        none = shapes.cabin_area(1500, 1500, 2400, openings_count=0)
        hoods = {p["label"]: p["area_m2"] for p in two["parts"]}
        self.assertAlmostEqual(hoods["Hoods over openings"], 0.7)
        hoods = {p["label"]: p["area_m2"] for p in none["parts"]}
        self.assertAlmostEqual(hoods["Hoods over openings"], 0.0)

    def test_too_small_for_sandwich(self):
        with self.assertRaises(shapes.ShapeError):
            shapes.cabin_area(40, 1500, 2400, openings_count=0)
        with self.assertRaises(shapes.ShapeError):
            shapes.cabin_area(1500, 1500, 150, openings_count=0)


class DomeTests(unittest.TestCase):
    def test_hemisphere(self):
        # D=4000, rise=2000: 2*pi*R^2 = 25.1327 m2.
        result = shapes.dome_area(4000, 2000)
        self.assertAlmostEqual(result["area_m2"], 25.1327, places=3)
        self.assertEqual(len(result["parts"]), 1)

    def test_spherical_cap(self):
        # D=4000, rise=1500: R=2.0833, A=2*pi*R*h = 19.6350 m2.
        result = shapes.dome_area(4000, 1500)
        self.assertAlmostEqual(result["area_m2"], 19.6350, places=3)

    def test_sandwich_inner_skin(self):
        result = shapes.dome_area(4230, 2115, 4000)
        parts = {p["label"]: p for p in result["parts"]}
        self.assertAlmostEqual(parts["Dome - outer skin"]["area_m2"],
                               2 * math.pi * 2.115 ** 2, places=6)
        self.assertAlmostEqual(parts["Dome - outer skin"]["area_m2"],
                               28.1061, places=3)
        self.assertAlmostEqual(parts["Dome - inner skin"]["area_m2"],
                               25.1327, places=3)
        self.assertEqual(parts["Dome - inner skin"]["core"]["material"],
                         "pufoam")
        self.assertEqual(parts["Dome - outer skin"]["layup"], "dome_outer")

    def test_inner_guards(self):
        with self.assertRaises(shapes.ShapeError):
            shapes.dome_area(4000, 2000, 4000)
        with self.assertRaises(shapes.ShapeError):
            shapes.dome_area(4000, 2000, 5000)
        with self.assertRaises(shapes.ShapeError):
            shapes.dome_area(4000, 100, 3800)

    def test_sphere(self):
        # D=1000: 4*pi*R^2 = pi m2.
        result = shapes.sphere_area(1000)
        self.assertAlmostEqual(result["area_m2"], math.pi, places=4)
        sandwich = shapes.sphere_area(1000, 900)
        self.assertEqual(len(sandwich["parts"]), 2)
        with self.assertRaises(shapes.ShapeError):
            shapes.sphere_area(1000, 1000)


class RegistryTests(unittest.TestCase):
    def test_shape_ids(self):
        self.assertEqual(set(shapes.SHAPE_IDS),
                         {"panel", "cylinder", "reducer", "box", "cabin",
                          "dome", "sphere", "custom"})

    def test_unknown_shape(self):
        with self.assertRaises(shapes.ShapeError):
            shapes.get_shape("pyramid")

    def test_compute_area_dispatch(self):
        panel = shapes.compute_area("panel", {"length": 1000, "width": 1000})
        self.assertAlmostEqual(panel["area_m2"], 1.0)
        tube = shapes.compute_area("cylinder", {"diameter": 400, "height": 1000},
                                   {"closed_bottom": False})
        self.assertAlmostEqual(tube["area_m2"], math.pi * 0.4)
        cone = shapes.compute_area("reducer", {"d_large": 600, "d_small": 400, "height": 500})
        self.assertAlmostEqual(cone["area_m2"], 0.80095, places=4)
        box = shapes.compute_area("box", {"length": 1000, "width": 1000, "height": 1000},
                                  {"open_top": False})
        self.assertAlmostEqual(box["area_m2"], 6.0)
        free = shapes.compute_area("custom", {"area": 12.5, "thickness": 6.0})
        self.assertAlmostEqual(free["area_m2"], 12.5)
        cabin = shapes.compute_area(
            "cabin", {"length": 1500, "width": 1500, "height": 2400,
                      "thickness": 4.0}, {"openings_count": 3})
        self.assertAlmostEqual(cabin["area_m2"], 43.2086, places=3)
        dome = shapes.compute_area(
            "dome", {"diameter": 4000.0, "height": 2000.0, "thickness": 8.0,
                     "diameter_inner": 0.0}, {})
        self.assertAlmostEqual(dome["area_m2"], 25.1327, places=3)
        ball = shapes.compute_area(
            "sphere", {"diameter": 1000.0, "thickness": 6.0,
                       "diameter_inner": 0.0}, {})
        self.assertAlmostEqual(ball["area_m2"], math.pi, places=4)


if __name__ == "__main__":
    unittest.main()