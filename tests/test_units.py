"""Unit conversion, measurement parsing and conflict checks."""

import unittest

from app import units


class ConversionTests(unittest.TestCase):
    def test_to_mm(self):
        self.assertAlmostEqual(units.to_mm(67.5, "cm"), 675.0)
        self.assertAlmostEqual(units.to_mm(1.2, "m"), 1200.0)
        self.assertAlmostEqual(units.to_mm(675, "mm"), 675.0)

    def test_from_mm(self):
        self.assertAlmostEqual(units.from_mm(1500, "m"), 1.5)
        self.assertAlmostEqual(units.from_mm(675, "cm"), 67.5)

    def test_normalize_aliases(self):
        self.assertEqual(units.normalize_unit("M"), "m")
        self.assertEqual(units.normalize_unit("CM"), "cm")
        self.assertEqual(units.normalize_unit("millimetres"), "mm")
        self.assertEqual(units.normalize_unit(""), "mm")
        self.assertEqual(units.normalize_unit(None), "mm")

    def test_unknown_unit(self):
        with self.assertRaises(units.UnitError):
            units.normalize_unit("inch")


class ParseTests(unittest.TestCase):
    def test_bare_number_defaults_mm(self):
        parsed = units.parse_measurement("675")
        self.assertEqual((parsed["value"], parsed["unit"], parsed["mm"]), (675.0, "mm", 675.0))

    def test_embedded_units(self):
        parsed = units.parse_measurement("67.5 cm")
        self.assertEqual((parsed["value"], parsed["unit"], parsed["mm"]), (67.5, "cm", 675.0))
        parsed = units.parse_measurement("0.675m")
        self.assertEqual((parsed["value"], parsed["unit"], parsed["mm"]), (0.675, "m", 675.0))

    def test_unparsable(self):
        with self.assertRaises(units.UnitError):
            units.parse_measurement("about a metre")
        with self.assertRaises(units.UnitError):
            units.parse_measurement("12 inch")


class ConflictTests(unittest.TestCase):
    def test_equal_readings_ok(self):
        self.assertIsNone(units.conflict("Width", 1200, 1200, "1200 mm", "1.2 m"))

    def test_close_readings_ok(self):
        self.assertIsNone(units.conflict("Width", 1200, 1204, "1200 mm", "1204 mm"))

    def test_mismatch_flagged(self):
        message = units.conflict("Width", 1200, 900, "1200 mm on drawing", "900 mm in text")
        self.assertIn("conflicts", message)
        self.assertIn("Width", message)


if __name__ == "__main__":
    unittest.main()