import os
import sys
import tempfile
import unittest
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from read_document import (extract_fields, extract_text, parse_amount,  # noqa: E402
                           process, valid_org_number)

FIXTURES = os.path.join(HERE, "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


def make_pdf(lines):
    """Minimal one-page PDF with a Helvetica text layer (WinAnsi encoded)."""
    ops = ["BT", "/F1 11 Tf", "14 TL", "50 780 Td"]
    for line in lines:
        esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({esc}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("cp1252")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


class HelperTest(unittest.TestCase):
    def test_parse_amount_formats(self):
        cases = {"1 234,50": "1234.50", "1.234,50": "1234.50", "1,234.50": "1234.50",
                 "1234.50": "1234.50", "845,-": "845.00", "12 000": "12000.00",
                 "1.200": "1200.00", " 999,9": "999.90"}
        for raw, expected in cases.items():
            self.assertEqual(parse_amount(raw), Decimal(expected), raw)

    def test_org_number_checksum(self):
        self.assertTrue(valid_org_number("912345602"))
        self.assertFalse(valid_org_number("912345603"))
        self.assertFalse(valid_org_number("123456785"))  # must start with 8 or 9


class FakturaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fields, cls.flags = extract_fields(fixture("faktura.txt"))

    def value(self, name):
        self.assertEqual(self.fields[name]["status"], "ok", self.fields[name])
        return self.fields[name]["value"]

    def test_all_fields(self):
        self.assertEqual(self.value("document_type"), "faktura")
        self.assertEqual(self.value("vendor_name"), "Verksted Service AS")
        self.assertEqual(self.value("vendor_org_number"), "912345602")
        self.assertEqual(self.value("invoice_number"), "2025-0417")
        self.assertEqual(self.value("total_amount"), 6000)
        self.assertEqual(self.fields["total_amount"]["currency"], "NOK")
        self.assertEqual(self.value("vat_rate"), 25)
        self.assertEqual(self.flags, [])

    def test_date_ignores_due_date_on_same_line(self):
        self.assertEqual(self.value("date"), "2025-03-10")

    def test_buyer_not_taken_as_vendor(self):
        self.assertNotIn("Taxi Drift AS", self.fields["vendor_name"]["candidates"])


class KvitteringTest(unittest.TestCase):
    def test_taxi_receipt(self):
        fields, flags = extract_fields(fixture("kvittering.txt"))
        self.assertEqual(fields["document_type"]["value"], "kvittering")
        self.assertEqual(fields["vendor_name"]["value"], "OSLO TAXI SENTRAL AS")
        self.assertEqual(fields["date"]["value"], "2025-06-14")
        self.assertEqual(fields["total_amount"]["value"], 845)  # not the 90,54 VAT line
        self.assertEqual(fields["vat_rate"]["value"], 12)
        self.assertEqual(fields["invoice_number"]["status"], "missing")
        self.assertEqual(flags, [])  # missing number on a receipt is not flagged


class UnclearTest(unittest.TestCase):
    """Conflicting or absent evidence must be flagged, never guessed."""

    @classmethod
    def setUpClass(cls):
        cls.fields, cls.flags = extract_fields(fixture("uklar.txt"))

    def test_nothing_guessed(self):
        for name in ("vendor_name", "date", "total_amount", "vat_rate", "document_type"):
            self.assertIsNone(self.fields[name]["value"], name)
            self.assertIn(self.fields[name]["status"], ("unclear", "missing"), name)

    def test_candidates_offered(self):
        self.assertEqual(self.fields["date"]["candidates"], ["2025-04-12", "2025-04-15"])
        self.assertEqual(self.fields["total_amount"]["candidates"], [54.8, 59.8])
        self.assertEqual(self.fields["vat_rate"]["candidates"], [15, 25])
        self.assertEqual(self.fields["vendor_name"]["candidates"], ["Kiosken på hjørnet"])

    def test_flags_listed(self):
        self.assertEqual(len(self.flags), 6)

    def test_ambiguous_slash_date_downgraded(self):
        fields, _ = extract_fields("Kvittering\nKjøpsdato: 03/04/2025\nTotalt 100,00\n")
        self.assertEqual(fields["date"]["value"], "2025-04-03")
        self.assertEqual(fields["date"]["confidence"], "medium")

    def test_unusual_vat_rate_flagged(self):
        fields, _ = extract_fields("Faktura\nMva 52 %  100,00\n")
        self.assertEqual(fields["vat_rate"]["status"], "unclear")

    def test_credit_note_not_classified(self):
        fields, _ = extract_fields("KREDITNOTA\nKreditnota nr 55\nÅ betale -100,00\n")
        self.assertEqual(fields["document_type"]["status"], "unclear")

    def test_ocr_caps_confidence(self):
        fields, _ = extract_fields(fixture("faktura.txt"), ocr=True)
        self.assertNotIn("high", {f["confidence"] for f in fields.values()})


class PdfTest(unittest.TestCase):
    def _pdf(self, lines):
        fd, path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as fh:
            fh.write(make_pdf(lines))
        self.addCleanup(os.remove, path)
        return path

    def test_text_pdf_end_to_end(self):
        path = self._pdf(fixture("kvittering.txt").splitlines())
        text, info = extract_text(path, allow_ocr=False)
        if not info["method"]:
            self.skipTest("no PDF text backend installed: " + "; ".join(info["tried"]))
        doc = process(path, allow_ocr=False)
        self.assertEqual(doc["status"], "ok")
        self.assertEqual(doc["fields"]["total_amount"]["value"], 845)
        self.assertEqual(doc["fields"]["vendor_org_number"]["value"], "912345610")

    def test_image_only_pdf_needs_ocr(self):
        doc = process(self._pdf([]), allow_ocr=False)
        self.assertEqual(doc["status"], "needs_ocr")
        self.assertTrue(doc["needs_review"])

    def test_missing_file(self):
        self.assertEqual(process("does-not-exist.pdf")["status"], "error")


if __name__ == "__main__":
    unittest.main()
