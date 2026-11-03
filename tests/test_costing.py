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
        self.assertAlmostEqual(result["material_bd"], 5.549847188)
        self.assertAlmostEqual(result["labour_bd"], 2.0)
        self.assertAlmostEqual(result["batch_bd"], 7.549847188)
        self.assertAlmostEqual(result["overhead_bd"], 0.754984719)
        self.assertAlmostEqual(result["total_bd"], 8.304831906)
        self.assertAlmostEqual(result["per_piece_bd"], 8.304831906)

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
            costing.calculate("pyramid", LEGACY_DIMS)


class ScheduleTests(unittest.TestCase):
    """Hand-worked ply-schedule numbers on a 1 m2 panel."""

    def _enclosure(self, **kwargs):
        params = {"recipe": {"wastage_pct": 0.0, "mekp_pct": 0.0, "labour_hours": 0.0,
                             "overhead_pct": 0.0},
                  "layup": "enclosure"}
        params.update(kwargs)
        dims = {"length": 1000.0, "width": 1000.0, "thickness": 5.1, "flange": 0.0}
        return costing.calculate("panel", dims, **params)

    def test_schedule_quantities(self):
        result = self._enclosure()
        self.assertAlmostEqual(result["glass_kg"]["csm450"], 0.9)
        self.assertAlmostEqual(result["glass_kg"]["csm300"], 0.6)
        self.assertAlmostEqual(result["glass_kg"]["wr600"], 0.6)
        self.assertAlmostEqual(result["fiber_kg"], 2.1)
        self.assertAlmostEqual(result["resin_kg"], 4.08)
        self.assertAlmostEqual(result["gelcoat_kg"], 0.6)
        self.assertAlmostEqual(result["schedule_mm"], 5.1)
        # Basket 6.123 (resin, glass, tissue, gelcoat) + 5% consumables.
        self.assertAlmostEqual(result["total_bd"], 6.42915)
        labels = [line["label"] for line in result["lines"]]
        self.assertIn("Glass - CSM 450 g/m2", labels)
        self.assertIn("Glass - Woven roving 600 g/m2", labels)
        self.assertIn("Gelcoat (0.60 kg/m2)", labels)

    def test_mould_amortised_over_life(self):
        one = self._enclosure(mould_option="need", mould_cost=100.0)
        self.assertAlmostEqual(one["mould_bd"], 100.0)
        self.assertAlmostEqual(one["total_bd"], 106.42915)
        two = self._enclosure(mould_option="need", mould_cost=100.0, qty=2)
        self.assertAlmostEqual(two["total_bd"], 6.42915 * 2 + 100.0)
        self.assertAlmostEqual(two["per_piece_bd"], (6.42915 * 2 + 100.0) / 2)
        long = self._enclosure(mould_option="need", mould_cost=400.0,
                               mould_life_qty=200, qty=10)
        self.assertAlmostEqual(long["mould_pc_bd"], 2.0)
        self.assertAlmostEqual(long["mould_bd"], 20.0)
        self.assertAlmostEqual(long["total_bd"], 6.42915 * 10 + 20.0)

    def test_overhead_covers_mould(self):
        result = costing.calculate(
            "panel", {"length": 1000.0, "width": 1000.0, "thickness": 5.1,
                      "flange": 0.0},
            layup="enclosure", mould_option="need", mould_cost=100.0,
            recipe={"wastage_pct": 0.0, "mekp_pct": 0.0, "labour_hours": 0.0})
        self.assertAlmostEqual(result["overhead_bd"], 10.642915)
        self.assertAlmostEqual(result["total_bd"], 117.072065)

    def test_have_mould_costs_nothing(self):
        result = self._enclosure(mould_option="have", mould_cost=100.0)
        self.assertAlmostEqual(result["mould_bd"], 0.0)
        self.assertAlmostEqual(result["total_bd"], 6.42915)

    def test_supports_per_piece(self):
        result = self._enclosure(plywood_m2=2.0, steel_kg=5.0)
        self.assertAlmostEqual(result["supports_bd"], 2.0 * 4.000 + 5.0 * 0.280)
        labels = [line["label"] for line in result["lines"]]
        self.assertIn("Plywood supports", labels)
        self.assertIn("Steel supports", labels)

    def test_resin_types(self):
        result = self._enclosure(resin_type="ve")
        self.assertAlmostEqual(result["resin_kg"], 4.08)
        # VE resin + glass + tissue + gelcoat + 5% consumables.
        self.assertAlmostEqual(result["total_bd"], 8.14275)
        self.assertEqual(result["resin_label"], "Vinyl ester")
        with self.assertRaises(costing.CostingError):
            self._enclosure(resin_type="epoxy")

    def test_pigment_machine_hardware(self):
        pigmented = self._enclosure(recipe={"wastage_pct": 0.0, "mekp_pct": 0.0,
                                            "labour_hours": 0.0, "overhead_pct": 0.0,
                                            "pigment_pct": 5.0})
        self.assertAlmostEqual(pigmented["pigment_kg"], 0.03)
        self.assertAlmostEqual(pigmented["total_bd"], 6.489)
        machined = self._enclosure(recipe={"wastage_pct": 0.0, "mekp_pct": 0.0,
                                           "labour_hours": 0.0, "overhead_pct": 0.0,
                                           "machine_hours": 2.0})
        self.assertAlmostEqual(machined["machine_bd"], 4.0)
        self.assertAlmostEqual(machined["total_bd"], 6.42915 + 4.0)
        fitted = self._enclosure(hardware_cost=3.5)
        self.assertAlmostEqual(fitted["total_bd"], 6.42915 + 3.5)

    def test_bad_mould_life_rejected(self):
        with self.assertRaises(costing.CostingError):
            self._enclosure(mould_option="need", mould_cost=10, mould_life_qty=0)
        with self.assertRaises(costing.CostingError):
            self._enclosure(mould_life_qty="many")

    def test_thickness_drift_warns(self):
        dims = {"length": 1000.0, "width": 1000.0, "thickness": 12.0, "flange": 0.0}
        result = costing.calculate("panel", dims, layup="enclosure")
        self.assertTrue([w for w in result["warnings"] if "differs" in w])
        ok = self._enclosure()
        self.assertEqual([w for w in ok["warnings"] if "differs" in w], [])

    def test_classic_gelcoat_option(self):
        plain = costing.calculate("panel", LEGACY_DIMS)
        coated = costing.calculate("panel", LEGACY_DIMS, gelcoat=True)
        self.assertAlmostEqual(coated["gelcoat_kg"], 0.55 * 0.765625 * 1.1)
        self.assertGreater(coated["total_bd"], plain["total_bd"])

    def test_unknown_layup_rejected(self):
        with self.assertRaises(costing.CostingError):
            costing.calculate("panel", LEGACY_DIMS, layup="carbon")

    def test_negative_mould_rejected(self):
        with self.assertRaises(costing.CostingError):
            costing.calculate("panel", LEGACY_DIMS, mould_option="need", mould_cost=-5)

    def test_bad_mould_option_rejected(self):
        with self.assertRaises(costing.CostingError):
            costing.calculate("panel", LEGACY_DIMS, mould_option="rent")


class ExtrasTests(unittest.TestCase):
    """Answerable assumptions and includable exclusions."""

    def _base(self, **kwargs):
        params = {"recipe": {"wastage_pct": 0.0, "mekp_pct": 0.0, "labour_hours": 0.0,
                             "overhead_pct": 0.0},
                  "layup": "enclosure"}
        params.update(kwargs)
        dims = {"length": 1000.0, "width": 1000.0, "thickness": 5.1, "flange": 0.0}
        return costing.calculate("panel", dims, **params)

    def test_extra_area_scales_materials(self):
        result = self._base(extra_area_m2=1.0)
        self.assertAlmostEqual(result["area_m2"], 1.0)
        self.assertAlmostEqual(result["resin_kg"], 8.16)
        self.assertAlmostEqual(result["fiber_kg"], 4.2)
        self.assertAlmostEqual(result["gelcoat_kg"], 1.2)
        # All GRP materials incl. consumables double.
        self.assertAlmostEqual(result["total_bd"], 6.42915 * 2)
        parts = [p["label"] for p in result["area_parts"]]
        self.assertIn("Extra stiffening / nozzles / flanges (entered)", parts)

    def test_paint_line_and_exclusion_dropped(self):
        result = self._base(paint=True)
        self.assertAlmostEqual(result["paint_kg"], 0.15)
        self.assertAlmostEqual(result["total_bd"], 6.8229)
        labels = [line["label"] for line in result["lines"]]
        self.assertIn("Paint / topcoat", labels)
        joined = " ".join(result["exclusions"])
        self.assertNotIn("Surface extras", joined)

    def test_delivery_and_testing_in_total(self):
        result = self._base(delivery_bd=50.0, testing_bd=30.0)
        self.assertAlmostEqual(result["total_bd"], 6.42915 + 80.0)
        joined = " ".join(result["exclusions"])
        self.assertNotIn("Delivery", joined)
        self.assertNotIn("Testing", joined)

    def test_markup_and_tax(self):
        result = self._base(markup_pct=10.0, tax_pct=10.0)
        self.assertAlmostEqual(result["markup_bd"], 0.642915)
        self.assertAlmostEqual(result["selling_bd"], 7.072065)
        self.assertAlmostEqual(result["tax_bd"], 0.7072065)
        self.assertAlmostEqual(result["grand_total_bd"], 7.7792715)
        joined = " ".join(result["exclusions"])
        self.assertNotIn("Profit margin", joined)
        self.assertNotIn("Taxes", joined)

    def test_default_exclusions_complete(self):
        result = self._base()
        self.assertEqual(len(result["exclusions"]), 6)

    def test_mould_included_drops_exclusion(self):
        result = self._base(mould_option="need", mould_cost=100.0)
        joined = " ".join(result["exclusions"])
        self.assertNotIn("Mould", joined)

    def test_negative_extras_rejected(self):
        with self.assertRaises(costing.CostingError):
            self._base(delivery_bd=-1.0)
        with self.assertRaises(costing.CostingError):
            self._base(tax_pct=-5.0)

    def test_bought_ins_lines(self):
        items = [{"label": "Aluminium door", "qty": 1, "unit": "no", "rate": 120.0},
                 {"label": "LED light", "qty": 2, "unit": "no", "rate": 6.0}]
        result = self._base(bought_ins=items)
        self.assertAlmostEqual(result["bought_ins_bd"], 132.0)
        self.assertAlmostEqual(result["total_bd"], 6.42915 + 132.0)
        labels = [line["label"] for line in result["lines"]]
        self.assertIn("Bought-in: Aluminium door", labels)
        self.assertIn("Bought-in: LED light", labels)

    def test_bought_ins_rejected(self):
        with self.assertRaises(costing.CostingError):
            self._base(bought_ins=[{"label": "", "qty": 1, "rate": 5}])
        with self.assertRaises(costing.CostingError):
            self._base(bought_ins=[{"label": "X", "qty": 1, "rate": -5}])

    def test_openings_deduct_materials(self):
        result = self._base(extra_area_m2=1.0, openings_m2=0.5)
        # Effective 1.5 m2: everything scales x1.5.
        self.assertAlmostEqual(result["resin_kg"], 4.08 * 1.5)
        self.assertAlmostEqual(result["total_bd"], 6.42915 * 1.5)
        parts = [p["label"] for p in result["area_parts"]]
        self.assertIn("Less door / window openings", parts)

    def test_openings_excess_warns(self):
        result = self._base(openings_m2=99.0)
        self.assertAlmostEqual(result["resin_kg"], 0.0)
        self.assertTrue([w for w in result["warnings"] if "Openings exceed" in w])


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


CABIN_DIMS = {"length": 1500.0, "width": 1500.0, "height": 2400.0,
              "thickness": 4.0}
CABIN_OPENINGS = [
    {"label": "Aluminium sliding window", "width_m": 0.8, "height_m": 1.0,
     "qty": 1},
    {"label": "Aluminium fixed window", "width_m": 0.8, "height_m": 1.0,
     "qty": 1},
    {"label": "Aluminium door (glass top, lock)", "width_m": 0.8,
     "height_m": 1.85, "qty": 1},
]
CABIN_ITEMS = [
    {"label": "Aluminium door (glass top, lock)", "qty": 1, "unit": "no",
     "rate": 120.0},
    {"label": "LED recessed down light", "qty": 1, "unit": "no", "rate": 6.0},
]


class CabinTests(unittest.TestCase):
    def _cabin(self, **over):
        params = {"recipe": {"overhead_pct": 15.0, "pigment_pct": 8.0,
                             "labour_hours": 107.3},
                  "rates": {"labour": 1.6}, "layup": "cabin_outer",
                  "mould_option": "need", "mould_cost": 600.0,
                  "hardware_cost": 12.0, "delivery_bd": 45.0,
                  "markup_pct": 20.0, "tax_pct": 10.0,
                  "bought_ins": [dict(i) for i in CABIN_ITEMS],
                  "openings": [dict(o) for o in CABIN_OPENINGS]}
        params.update(over)
        return costing.calculate("cabin", dict(CABIN_DIMS), qty=2, **params)

    def test_openings_deduct_from_each_wall_skin(self):
        calc = self._cabin()
        self.assertAlmostEqual(calc["openings_m2"], 3.08)
        negatives = [p for p in calc["area_parts"] if p["area_m2"] < 0]
        self.assertEqual(len(negatives), 2)
        for part in negatives:
            self.assertAlmostEqual(part["area_m2"], -3.08)

    def test_opening_rows_win_over_legacy_total(self):
        calc = self._cabin(openings_m2=999.0)
        self.assertAlmostEqual(calc["openings_m2"], 3.08)

    def test_bad_opening_row_rejected(self):
        with self.assertRaises(costing.CostingError):
            self._cabin(openings=[{"label": "X", "width_m": -1, "height_m": 1,
                                   "qty": 1}])

    def test_cores_costed(self):
        calc = self._cabin()
        self.assertAlmostEqual(calc["core_m2"]["pufoam"], 13.827, places=2)
        self.assertAlmostEqual(calc["core_m2"]["plywood"], 2.3128, places=3)
        labels = [line["label"] for line in calc["lines"]]
        self.assertIn("PU foam core 20 mm", labels)
        self.assertIn("Plywood floor core 18 mm", labels)

    def test_labour_operations(self):
        calc = self._cabin()
        self.assertEqual(len(calc["labour_ops"]), 8)
        self.assertAlmostEqual(sum(o["hours"] for o in calc["labour_ops"]),
                               107.3, places=1)
        labels = [line["label"] for line in calc["lines"]]
        self.assertIn("Labour - Electrical installation", labels)
        self.assertNotIn("Labour", labels)

    def test_labour_override_collapses_operations(self):
        calc = self._cabin(recipe={"labour_hours": 100.0})
        self.assertIsNone(calc["labour_ops"])
        labels = [line["label"] for line in calc["lines"]]
        self.assertIn("Labour", labels)

    def test_unwired_cabin_skips_electrical_op(self):
        calc = self._cabin(bought_ins=[],
                           recipe={"labour_hours": 106.0})
        self.assertEqual(len(calc["labour_ops"]), 7)

    def test_delivery_scales_per_piece(self):
        calc = self._cabin()
        self.assertAlmostEqual(calc["delivery_batch_bd"], 90.0)
        self.assertAlmostEqual(calc["overhead_bd"],
                               (calc["batch_bd"] + calc["mould_bd"] + 90.0) * 0.15)

    def test_cabin_totals(self):
        calc = self._cabin()
        self.assertAlmostEqual(calc["bought_ins_bd"], 126.0)
        self.assertAlmostEqual(calc["labour_bd"], 171.68, places=2)
        self.assertAlmostEqual(calc["mould_pc_bd"], 300.0)
        self.assertAlmostEqual(calc["material_bd"], 393.524, places=2)
        self.assertAlmostEqual(calc["grand_total_bd"] / 2, 1381.690, places=2)


class DomeTests(unittest.TestCase):
    def test_sandwich_dome(self):
        calc = costing.calculate(
            "dome", {"diameter": 4230.0, "height": 2115.0,
                     "diameter_inner": 4000.0, "thickness": 8.0},
            layup="dome_outer")
        self.assertAlmostEqual(calc["area_m2"], 28.1061 + 25.1327, places=3)
        self.assertAlmostEqual(calc["glass_kg"]["csm450"], 133.24, places=1)
        self.assertAlmostEqual(calc["glass_kg"]["wr600"], 18.55, places=1)
        self.assertAlmostEqual(calc["resin_kg"], 317.2, places=0)
        self.assertAlmostEqual(calc["gelcoat_kg"], 0.0)
        self.assertAlmostEqual(calc["core_m2"]["pufoam"], 29.28, places=1)
        self.assertIsNone(calc["labour_ops"])
        labels = [line["label"] for line in calc["lines"]]
        self.assertIn("Labour", labels)
        self.assertIn("PU foam core 20 mm", labels)
        self.assertEqual(calc["warnings"], [])

    def test_single_skin_sphere(self):
        calc = costing.calculate(
            "sphere", {"diameter": 1000.0, "diameter_inner": 0.0,
                       "thickness": 6.0}, layup="dome_outer")
        self.assertAlmostEqual(calc["area_m2"], 3.1416, places=3)
        self.assertAlmostEqual(calc["core_m2"]["pufoam"], 0.0)
        labels = [line["label"] for line in calc["lines"]]
        self.assertNotIn("PU foam core 20 mm", labels)


if __name__ == "__main__":
    unittest.main()