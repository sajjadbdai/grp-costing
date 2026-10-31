"""Costing checks: legacy regression, scaling, guards and exclusions."""

import unittest

from app import costing


LEGACY_DIMS = {"length": 675.0, "width": 675.0, "thickness": 4.0, "flange": 100.0}


class LegacyRegressionTests(unittest.TestCase):
    """Hand-worked original MVP defaults must reproduce exactly."""

    def test_panel_totals(self):
        result = costing.calculate("panel", LEGACY_DIMS)
        self.assertAlmostEqual(result["area_m2"], 0.765625)
        self.assertAlmostEqual(result["laminate_kg"], 4.59375)
        self.assertAlmostEqual(result["fiber_kg"], 1.5159375)
        self.assertAlmostEqual(result["resin_kg"], 3.5371875)
        self.assertAlmostEqual(result["mekp_kg"], 0.0530578125)
        self.assertAlmostEqual(result["material_bd"], 5.68556875)
        self.assertAlmostEqual(result["labour_bd"], 2.0)
        self.assertAlmostEqual(result["batch_bd"], 7.68556875)
        self.assertAlmostEqual(result["overhead_bd"], 0.768556875)
        self.assertAlmostEqual(result["total_bd"], 8.454125625)
        self.assertAlmostEqual(result["per_piece_bd"], 8.454125625)

    def test_quantity_scaling(self):
        one = costing.calculate("panel", LEGACY_DIMS, qty=1)
        ten = costing.calculate("panel", LEGACY_DIMS, qty=10)
        self.assertAlmostEqual(ten["total_bd"], one["total_bd"] * 10)
        self.assertAlmostEqual(ten["per_piece_bd"], one["per_piece_bd"])
        self.assertAlmostEqual(ten["resin_kg"], one["resin_kg"])  # per-piece quantities

    def test_lines_add_up(self):
        result = costing.calculate("panel", LEGACY_DIMS)
        material_lines = [line for line in result["lines"] if line["label"] != "Labour"]
        self.assertAlmostEqual(sum(line["amount"] for line in material_lines),
                               result["material_bd"])


class GuardTests(unittest.TestCase):
    def test_resin_fiber_must_sum_100(self):
        with self.assertRaises(costing.CostingError):
            costing.calculate("panel", LEGACY_DIMS, recipe={"resin_pct": 60.0, "fiber_pct": 30.0})

    def test_negative_rate_rejected(self):
        with self.assertRaises(costing.CostingError):
            costing.calculate("panel", LEGACY_DIMS, rates={"resin": -1.0})

    def test_zero_qty_rejected(self):
        with self.assertRaises(costing.CostingError):
            costing.calculate("panel", LEGACY_DIMS, qty=0)

    def test_zero_thickness_rejected(self):
        dims = dict(LEGACY_DIMS, thickness=0.0)
        with self.assertRaises(costing.CostingError):
            costing.calculate("panel", dims)

    def test_negative_dimension_rejected(self):
        dims = dict(LEGACY_DIMS, length=-50.0)
        with self.assertRaises(ValueError):
            costing.calculate("panel", dims)

    def test_unknown_shape_rejected(self):
        with self.assertRaises(ValueError):
            costing.calculate("sphere", LEGACY_DIMS)


class CoverageTests(unittest.TestCase):
    def test_exclusions_listed(self):
        self.assertGreaterEqual(len(costing.EXCLUSIONS), 5)
        joined = " ".join(costing.EXCLUSIONS).lower()
        self.assertIn("tooling", joined)
        self.assertIn("margin", joined)

    def test_cylinder_and_reducer_run(self):
        tank = costing.calculate("cylinder", {"diameter": 1000.0, "height": 2000.0,
                                              "thickness": 6.0}, qty=2)
        self.assertGreater(tank["total_bd"], 0)
        self.assertAlmostEqual(tank["per_piece_bd"], tank["total_bd"] / 2)
        cone = costing.calculate("reducer", {"d_large": 600.0, "d_small": 400.0,
                                             "height": 500.0, "thickness": 5.0})
        self.assertGreater(cone["area_m2"], 0)
        self.assertIn("Material and cost estimate only", " ".join(cone["assumptions"]))


if __name__ == "__main__":
    unittest.main()