"""Material price store checks: defaults, updates, guards and history safety."""

import json
import os
import tempfile
import unittest

from app import costing, materials


class MaterialsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="gfpf-test-")
        self.path = os.path.join(self.dir, "rates.json")
        os.environ["GFPF_RATES_PATH"] = self.path

    def tearDown(self):
        os.environ.pop("GFPF_RATES_PATH", None)
        for name in ("rates.json", "rates.json.tmp"):
            try:
                os.remove(os.path.join(self.dir, name))
            except OSError:
                pass
        try:
            os.rmdir(self.dir)
        except OSError:
            pass

    def test_defaults_when_never_saved(self):
        state = materials.get_state()
        self.assertEqual(state["rates"], costing.DEFAULT_RATES)
        self.assertIsNone(state["updated_at"])
        self.assertFalse(state["customized"])
        self.assertEqual(materials.get_rates(), costing.DEFAULT_RATES)

    def test_update_persists_and_reloads(self):
        state = materials.update_rates({"resin": 1.10, "fiber": 1.35})
        self.assertAlmostEqual(state["rates"]["resin"], 1.10)
        self.assertAlmostEqual(state["rates"]["fiber"], 1.35)
        self.assertTrue(state["customized"])
        self.assertTrue(state["updated_at"])
        again = materials.get_state()
        self.assertAlmostEqual(again["rates"]["resin"], 1.10)
        self.assertAlmostEqual(again["rates"]["fiber"], 1.35)

    def test_partial_update_keeps_other_prices(self):
        materials.update_rates({"resin": 1.10})
        state = materials.get_state()
        self.assertAlmostEqual(state["rates"]["resin"], 1.10)
        self.assertAlmostEqual(state["rates"]["fiber"], costing.DEFAULT_RATES["fiber"])
        self.assertAlmostEqual(state["rates"]["mekp"], costing.DEFAULT_RATES["mekp"])

    def test_update_accepts_numeric_strings(self):
        state = materials.update_rates({"labour": "2.5"})
        self.assertAlmostEqual(state["rates"]["labour"], 2.5)

    def test_unknown_key_rejected(self):
        with self.assertRaises(materials.MaterialsError):
            materials.update_rates({"carbon": 5.0})
        self.assertFalse(os.path.exists(self.path))

    def test_negative_price_rejected(self):
        with self.assertRaises(materials.MaterialsError):
            materials.update_rates({"resin": -1.0})
        self.assertFalse(os.path.exists(self.path))

    def test_non_numeric_price_rejected(self):
        with self.assertRaises(materials.MaterialsError):
            materials.update_rates({"resin": "pricey"})
        self.assertFalse(os.path.exists(self.path))

    def test_empty_update_rejected(self):
        with self.assertRaises(materials.MaterialsError):
            materials.update_rates({})

    def test_corrupt_file(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(materials.MaterialsError):
            materials.get_rates()

    def test_bad_shape_file(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"rates": [1, 2, 3]}, handle)
        with self.assertRaises(materials.MaterialsError):
            materials.get_rates()

    def test_unknown_key_in_file_ignored(self):
        # Retired keys (e.g. the old flat consumables) never break old files.
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"rates": {"carbon": 5.0, "resin": 1.1},
                       "updated_at": "x"}, handle)
        state = materials.get_state()
        self.assertAlmostEqual(state["rates"]["resin"], 1.1)
        self.assertAlmostEqual(state["rates"]["fiber"],
                               costing.DEFAULT_RATES["fiber"])

    def test_saved_estimates_untouched_by_price_update(self):
        from app import store

        estimates_path = os.path.join(self.dir, "estimates.json")
        os.environ["GFPF_DATA_PATH"] = estimates_path
        try:
            snapshot = {"label": "frozen", "shape_id": "panel", "qty": 1,
                        "rates": dict(costing.DEFAULT_RATES),
                        "result": {"total_bd": 8.454, "per_piece_bd": 8.454}}
            saved = store.save_new(snapshot)
            materials.update_rates({"resin": 9.99})
            _, revision = store.get(saved["id"])
            self.assertAlmostEqual(revision["snapshot"]["rates"]["resin"],
                                   costing.DEFAULT_RATES["resin"])
            self.assertAlmostEqual(revision["snapshot"]["result"]["total_bd"], 8.454)
        finally:
            os.environ.pop("GFPF_DATA_PATH", None)
            try:
                os.remove(estimates_path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
