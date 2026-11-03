"""Review-form helper checks: row delete, blank counts, scan summary."""

import asyncio
import json
import os
import re
import unittest
from unittest import mock

from app import main


class DeleteTests(unittest.TestCase):
    def test_boughtin_delete_tick_skips_row(self):
        form = {"boughtin_count": "2",
                "boughtin_0_label": "Door", "boughtin_0_qty": "1",
                "boughtin_0_unit": "no", "boughtin_0_rate": "120",
                "boughtin_0_del": "1",
                "boughtin_1_label": "Window", "boughtin_1_qty": "2",
                "boughtin_1_unit": "no", "boughtin_1_rate": "45"}
        errors = []
        items = main._parse_bought_ins(form, errors)
        self.assertEqual(errors, [])
        self.assertEqual([i["label"] for i in items], ["Window"])

    def test_opening_delete_tick_skips_row(self):
        form = {"opening_count": "2",
                "opening_0_label": "D1", "opening_0_w": "0.8",
                "opening_0_h": "1.85", "opening_0_qty": "1",
                "opening_0_del": "1",
                "opening_1_label": "W1", "opening_1_w": "0.8",
                "opening_1_h": "1.0", "opening_1_qty": "1"}
        errors = []
        rows = main._parse_openings(form, errors)
        self.assertEqual(errors, [])
        self.assertEqual([r["label"] for r in rows], ["W1"])

    def test_delete_wins_over_bad_values(self):
        form = {"boughtin_count": "1", "boughtin_0_label": "X",
                "boughtin_0_qty": "abc", "boughtin_0_rate": "1",
                "boughtin_0_del": "1"}
        errors = []
        self.assertEqual(main._parse_bought_ins(form, errors), [])


class BlanksTests(unittest.TestCase):
    def test_keeps_posted_blanks(self):
        form = {"boughtin_count": "5",
                "boughtin_0_label": "Door", "boughtin_0_qty": "1",
                "boughtin_0_rate": "120",
                "boughtin_1_label": "Window", "boughtin_1_qty": "1",
                "boughtin_1_rate": "45"}
        blanks = main._posted_blanks(form, "boughtin_count", "boughtin",
                                     ("label", "qty", "rate"), 2)
        self.assertEqual(blanks, 3)

    def test_floor_and_cap(self):
        self.assertEqual(main._posted_blanks({}, "boughtin_count", "boughtin",
                                             ("label",), 2), 2)
        form = {"boughtin_count": "99"}
        self.assertEqual(main._posted_blanks(form, "boughtin_count", "boughtin",
                                             ("label",), 2), 10)


class ScanTests(unittest.TestCase):
    def test_build_scan_summary(self):
        info = {"overall": {"length": 1500, "width": 1500, "height": 2400},
                "internal": None, "finishes": ["beige"], "supports": [],
                "job_qty": 2}
        items = [{"label": "Door", "source": "drawing"},
                 {"label": "Cables", "source": "allowance"}]
        scan = main._build_scan("PDF text", info, items, 1.48)
        self.assertEqual(scan["n_items"], 1)
        self.assertEqual(scan["source"], "PDF text")
        self.assertFalse(scan["thin"])
        self.assertEqual(scan["job_qty"], 2)

    def test_thin_scan_flag(self):
        info = {"overall": None, "internal": None, "finishes": [],
                "supports": [], "job_qty": None}
        scan = main._build_scan("description only", info, [], 0.0)
        self.assertTrue(scan["thin"])

    def test_kept_scan_roundtrip(self):
        scan = {"source": "PDF text", "n_items": 3}
        import json
        back = main._kept_scan({"scan_json": json.dumps(scan)})
        self.assertEqual(back, scan)
        self.assertIsNone(main._kept_scan({}))
        self.assertIsNone(main._kept_scan({"scan_json": "not json"}))


class GuessProductTests(unittest.TestCase):
    def test_details_of_line(self):
        text = "SHEET CONTENT / DRWING TITLE\nDETAILS OF GRP ENCLOSURE\nGFPF#25"
        self.assertEqual(main._guess_product(text, "ENCLOSURE.pdf"),
                         "GRP Enclosure")

    def test_qty_title_line(self):
        text = ("CUSTOM-BUILT GRP ENCLOSURE - DOUBLE PANEL DOOR  WITH "
                "CANOPY DETAILS - QTY : 01 No.")
        self.assertEqual(main._guess_product(text, ""), "GRP Enclosure")

    def test_short_grp_line(self):
        self.assertEqual(main._guess_product("GRP Canopy\n1360\n980", ""),
                         "GRP Canopy")

    def test_filename_fallback(self):
        self.assertEqual(main._guess_product("1360\n980", "ENCLOSURE.pdf"),
                         "Enclosure")

    def test_blank(self):
        self.assertEqual(main._guess_product("", ""), "")
        self.assertEqual(main._guess_product("1360\n980", ""), "")

    def test_dome_text(self):
        self.assertEqual(main._guess_product("DETAILS OF GRP DOME\n4000 DIA",
                                             "DOME.pdf"),
                         "GRP Dome")


def _render_review(description="GRP Enclosure"):
    from starlette.requests import Request
    req = Request({"type": "http", "http_version": "1.1", "method": "GET",
                   "scheme": "http", "path": "/", "query_string": b"",
                   "headers": []})
    info = {"overall": None, "internal": None, "finishes": [],
            "supports": [], "job_qty": None}
    ctx = main._review_context(
        req, "box", main._blank_extraction("box"), description, "",
        bought_ins=[], openings_m2=0.0, openings_detail=[],
        scan=main._build_scan("description only", info, [], 0.0))
    return main._render("review.html", ctx).body.decode("utf-8")


class ReviewRenderTests(unittest.TestCase):
    def test_product_input_editable(self):
        html = _render_review()
        self.assertIn('name="description"', html)
        self.assertNotIn("description_text", html)
        found = re.search(r'<input[^>]*name="description"[^>]*>', html)
        self.assertIsNotNone(found)
        self.assertNotIn("disabled", found.group(0))
        self.assertIn('value="GRP Enclosure"', found.group(0))

    def test_side_by_side_fields(self):
        html = _render_review()
        self.assertIn('class="field"', html)
        self.assertIn("flabel", html)
        self.assertIn("finput", html)


def _render_rates(ai_on=True):
    from starlette.requests import Request
    from app import costing
    req = Request({"type": "http", "http_version": "1.1", "method": "GET",
                   "scheme": "http", "path": "/rates", "query_string": b"",
                   "headers": []})
    ctx = {"request": req, "rates": dict(costing.DEFAULT_RATES),
           "labels": costing.RATE_LABELS, "updated_at": None,
           "customized": False, "message": None, "errors": [],
           "ai_on": ai_on}
    return main._render("rates.html", ctx).body.decode("utf-8")


class RatesRenderTests(unittest.TestCase):
    def test_price_check_table(self):
        from app import costing
        html = _render_rates()
        self.assertIn("Previous rate", html)
        self.assertIn("New rate", html)
        self.assertIn("Check online prices", html)
        self.assertEqual(html.count('<button type="button" class="update-btn'),
                         len(costing.RATE_LABELS))
        self.assertNotIn("google.com", html)
        self.assertNotIn('target="_blank"', html)

    def test_check_disabled_without_ai(self):
        html = _render_rates(ai_on=False)
        self.assertIn("MODEL_API_KEY", html)


class PriceCheckTests(unittest.TestCase):
    def test_check_returns_current_and_found(self):
        from app import costing
        found = {"resin": {"price": 0.72, "note": "supplier quote"}}
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}, clear=True):
            with mock.patch("app.main.muse_client.suggest_prices",
                            return_value=found):
                resp = asyncio.run(main.api_price_check())
        body = json.loads(resp.body.decode("utf-8"))
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["prices"]), len(costing.DEFAULT_RATES))
        self.assertEqual(body["prices"]["resin"]["price"], 0.72)
        self.assertEqual(body["prices"]["resin"]["note"], "supplier quote")
        self.assertIn("current", body["prices"]["resin"])
        self.assertIsNone(body["prices"]["steel"]["price"])

    def test_check_needs_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            resp = asyncio.run(main.api_price_check())
        body = json.loads(resp.body.decode("utf-8"))
        self.assertFalse(body["ok"])
        self.assertIn("MODEL_API_KEY", body["error"])


class LayoutRegressionTests(unittest.TestCase):
    def test_stylesheet_versioned(self):
        self.assertIn("style.css?v=", _render_review())

    def test_css_side_by_side_and_top_drawing(self):
        from pathlib import Path
        css = (Path(main.__file__).parent / "static" / "style.css").read_text(
            encoding="utf-8")
        self.assertIn(".field{display:flex", css)
        self.assertIn(".flabel{flex:0 0", css)
        self.assertIn(".review-grid{display:grid;grid-template-columns:1fr",
                      css)


if __name__ == "__main__":
    unittest.main()
