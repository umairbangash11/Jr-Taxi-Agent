import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from match_bank import main, parse_amount, read_bank, run  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
CSV_BANK = os.path.join(FIX, "bank_dnb.csv")
CAMT_BANK = os.path.join(FIX, "bank_camt053.xml")
CFG = {"receipt_days": 7, "invoice_days": 60, "early_days": 3, "tolerance": Decimal("0")}


def reader_doc(file, **values):
    """document-reader shaped document; omitted fields are 'missing'."""
    fields = {}
    for name in ("document_type", "vendor_name", "vendor_org_number", "date",
                 "invoice_number", "total_amount", "vat_rate"):
        v = values.get(name)
        fields[name] = ({"value": v, "status": "ok"} if v is not None
                        else {"value": None, "status": "missing"})
    fields["total_amount"]["currency"] = values.get("currency", "NOK")
    return {"file": file, "status": "ok", "fields": fields}


DOCS = [
    reader_doc("verksted.pdf", document_type="faktura", vendor_name="Verksted Service AS",
               date="2025-03-10", invoice_number="2025-0417", total_amount=6000),
    reader_doc("circlek.pdf", document_type="kvittering", vendor_name="Circle K Norge AS",
               date="2025-06-13", total_amount=845),
    reader_doc("kiwi.pdf", document_type="kvittering", vendor_name="Kiwi Majorstuen",
               date="2025-06-19", total_amount=500),
    reader_doc("telenor.pdf", document_type="faktura", vendor_name="Telenor Norge AS",
               date="2025-05-01", total_amount=1234),
    reader_doc("uklar.pdf", document_type="kvittering", vendor_name="Bunnpris"),
    reader_doc("bunnpris.pdf", document_type="kvittering", vendor_name="Bunnpris Lade",
               date="2025-07-05", total_amount=399),
]


def write_json(tmp, name, data):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


class Base(unittest.TestCase):
    def run_match(self, docs, bank=CSV_BANK, key="documents"):
        with tempfile.TemporaryDirectory() as tmp:
            return run([write_json(tmp, "d.json", {key: docs})], bank, dict(CFG))

    def by_id(self, result):
        return {d["id"]: d for d in result["documents"]}


class ParseTest(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(parse_amount("6 000,00"), Decimal("6000.00"))
        self.assertEqual(parse_amount("-1.234,50"), Decimal("-1234.50"))
        self.assertEqual(parse_amount("845,00-"), Decimal("-845.00"))
        self.assertIsNone(parse_amount(""))

    def test_csv_columns_detected_and_signed(self):
        lines, warnings = read_bank(CSV_BANK)
        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[0]["amount"], Decimal("-6000.00"))   # Uttak -> outgoing
        self.assertEqual(lines[4]["amount"], Decimal("12500.00"))   # Innskudd -> incoming
        self.assertEqual(str(lines[0]["date"]), "2025-03-24")      # Dato, not Rentedato
        self.assertEqual(warnings, [])

    def test_cp1252_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.csv")
            with open(path, "w", encoding="cp1252") as fh:
                fh.write("Bokført dato;Beskrivelse;Beløp\n01.02.2025;Bensin Ørje;-250,00\n")
            lines, _ = read_bank(path)
        self.assertEqual(lines[0]["text"], "Bensin Ørje")
        self.assertEqual(lines[0]["amount"], Decimal("-250.00"))

    def test_camt(self):
        lines, _ = read_bank(CAMT_BANK)
        self.assertEqual([ln["amount"] for ln in lines], [Decimal("-6000.00"), Decimal("12500.00")])
        self.assertIn("Verksted Service AS", lines[0]["text"])


class MatchTest(Base):
    @classmethod
    def setUpClass(cls):
        cls.res = cls.by_id(cls, cls.run_match(cls, DOCS))
        cls.full = cls.run_match(cls, DOCS)

    def test_invoice_paid_by_reference(self):
        r = self.res["verksted.pdf"]
        self.assertEqual((r["status"], r["confidence"]), ("paid", "high"))
        self.assertEqual(r["match"]["vendor_signal"], "reference")
        self.assertEqual(r["match"]["days_after_document"], 14)

    def test_card_receipt_paid_by_vendor_name(self):
        r = self.res["circlek.pdf"]
        self.assertEqual(r["status"], "paid")
        self.assertEqual(r["match"]["vendor_signal"], "strong")

    def test_two_equal_lines_and_place_name_only_is_uncertain(self):
        # "Kiwi Majorstuen" vs "REMA 1000 MAJORSTUEN": shared place name is only a weak signal.
        r = self.res["kiwi.pdf"]
        self.assertEqual(r["status"], "uncertain")
        self.assertEqual(r["match"]["vendor_signal"], "weak")
        self.assertTrue(any("Several bank lines" in x for x in r["reasons"]))
        self.assertTrue(any("partially recognised" in x for x in r["reasons"]))

    def test_not_found(self):
        self.assertEqual(self.res["telenor.pdf"]["status"], "not_found")

    def test_unmatchable_without_amount(self):
        self.assertEqual(self.res["uklar.pdf"]["status"], "unmatchable")

    def test_amount_only_match_is_uncertain(self):
        r = self.res["bunnpris.pdf"]
        self.assertEqual(r["status"], "uncertain")
        self.assertEqual(r["match"]["bank_line"], "row7")

    def test_incoming_lines_never_matched_and_unmatched_reported(self):
        unmatched = self.full["unmatched_outgoing_bank_lines"]
        self.assertEqual(len(unmatched), 1)  # one of the two 500,00 lines
        self.assertEqual(unmatched[0]["amount"], -500.0)
        self.assertEqual(self.full["meta"]["status_counts"],
                         {"paid": 2, "uncertain": 2, "not_found": 1, "unmatchable": 1})


class ConflictTest(Base):
    def test_two_documents_one_bank_line(self):
        docs = [reader_doc("a.pdf", document_type="kvittering", vendor_name="Circle K Norge AS",
                           date="2025-06-13", total_amount=845),
                reader_doc("b.pdf", document_type="kvittering", vendor_name="Circle K Norge AS",
                           date="2025-06-13", total_amount=845)]
        res = self.by_id(self.run_match(docs))
        self.assertEqual({r["status"] for r in res.values()}, {"uncertain"})
        lost = next(r for r in res.values() if r["match"] is None)
        self.assertIn("already matched", lost["reasons"][0])

    def test_outside_receipt_window_not_found(self):
        docs = [reader_doc("old.pdf", document_type="kvittering", vendor_name="Circle K",
                           date="2025-05-01", total_amount=845)]
        self.assertEqual(self.run_match(docs)["documents"][0]["status"], "not_found")

    def test_camt_and_entry_builder_input(self):
        bilag = [{"source_file": "verksted.pdf", "status": "ready",
                  "header": {"date": "2025-03-10", "document_type": "faktura",
                             "vendor_name": "Verksted Service AS", "invoice_number": "2025-0417",
                             "total_amount": 6000.0, "currency": "NOK"}}]
        r = self.run_match(bilag, bank=CAMT_BANK, key="bilag")["documents"][0]
        self.assertEqual((r["status"], r["match"]["vendor_signal"]), ("paid", "reference"))


class CliTest(unittest.TestCase):
    def test_cli_and_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = write_json(tmp, "d.json", {"documents": DOCS})
            out = os.path.join(tmp, "o.json")
            self.assertEqual(main(["--documents", docs, "--bank", CSV_BANK, "-o", out]), 0)
            with open(out, encoding="utf-8") as fh:
                self.assertEqual(len(json.load(fh)["documents"]), 6)
            self.assertEqual(main(["--documents", docs, "--bank", "missing.csv"]), 1)


if __name__ == "__main__":
    unittest.main()
