"""Revision store checks: snapshots stay immutable across revisions."""

import os
import tempfile
import unittest

from app import store


def _snapshot(total):
    return {"label": "demo", "shape_id": "panel", "qty": 1,
            "result": {"total_bd": total, "per_piece_bd": total}}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="gfpf-test-")
        self.path = os.path.join(self.dir, "estimates.json")
        os.environ["GFPF_DATA_PATH"] = self.path

    def tearDown(self):
        os.environ.pop("GFPF_DATA_PATH", None)
        try:
            os.remove(self.path)
            os.rmdir(self.dir)
        except OSError:
            pass

    def test_save_and_get(self):
        saved = store.save_new(_snapshot(8.454))
        self.assertEqual(saved["rev"], 1)
        meta, revision = store.get(saved["id"])
        self.assertEqual(meta["rev_count"], 1)
        self.assertAlmostEqual(revision["snapshot"]["result"]["total_bd"], 8.454)

    def test_revisions_are_immutable(self):
        saved = store.save_new(_snapshot(8.454))
        rev2 = store.add_revision(saved["id"], _snapshot(9.100))
        self.assertEqual(rev2, 2)
        _, first = store.get(saved["id"], 1)
        self.assertAlmostEqual(first["snapshot"]["result"]["total_bd"], 8.454)
        _, latest = store.get(saved["id"])
        self.assertEqual(latest["rev"], 2)
        self.assertAlmostEqual(latest["snapshot"]["result"]["total_bd"], 9.100)

    def test_list_summaries(self):
        store.save_new(_snapshot(8.454))
        summaries = store.list_all()
        self.assertEqual(len(summaries), 1)
        self.assertAlmostEqual(summaries[0]["total_bd"], 8.454)

    def test_missing_estimate(self):
        with self.assertRaises(store.StoreError):
            store.get("no-such-id")

    def test_missing_revision(self):
        saved = store.save_new(_snapshot(8.454))
        with self.assertRaises(store.StoreError):
            store.get(saved["id"], 99)

    def test_corrupt_file(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(store.StoreError):
            store.list_all()


if __name__ == "__main__":
    unittest.main()