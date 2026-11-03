"""PDF sheet checks: valid file with the estimate's key contents."""

import unittest

try:
    import pymupdf
except ImportError:
    pymupdf = None

try:
    from app import costing, pdf_report
    from app.main import _dims_display, _spec_rows
except ImportError:
    costing = pdf_report = None


def _text(data):
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


@unittest.skipUnless(costing and pymupdf, "fpdf2/pymupdf not installed")
class PdfTests(unittest.TestCase):
    def _calc(self):
        dims = {"length": 2000.0, "width": 1000.0, "height": 500.0,
                "thickness": 11.1}
        return costing.calculate("box", dims, qty=3, layup="tank_heavy",
                                 mould_option="need", mould_cost=250.0,
                                 markup_pct=10.0, tax_pct=10.0)

    def _pdf(self, calc):
        dims_original = [{"field": k, "value": v, "unit": "mm"}
                         for k, v in (("length", 2000.0), ("width", 1000.0),
                                       ("height", 500.0), ("thickness", 11.1))]
        return pdf_report.build_pdf("ABC123", "2026-11-02 12:00", "Revision 1 of 1",
                                    calc, _dims_display("box", dims_original),
                                    _spec_rows(calc), "Test tank")

    def test_valid_pdf_with_key_contents(self):
        calc = self._calc()
        data = self._pdf(calc)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 3000)
        text = _text(data)
        for needle in ("ESTIMATION SHEET", "ABC123", "Test tank",
                       "Water tank heavy", "New mould (amortised)",
                       "SELLING PRICE", "GRAND TOTAL", "Approval",
                       "BD %.3f" % calc["total_bd"],
                       "BD %.3f" % calc["grand_total_bd"]):
            self.assertIn(needle, text)

    def test_plain_estimate_has_no_pricing_rows(self):
        calc = costing.calculate(
            "panel", {"length": 675.0, "width": 675.0, "thickness": 4.0,
                      "flange": 100.0})
        text = _text(self._pdf(calc))
        self.assertIn("ESTIMATED TOTAL", text)
        self.assertNotIn("SELLING PRICE", text)
        self.assertNotIn("GRAND TOTAL", text)


if __name__ == "__main__":
    unittest.main()
