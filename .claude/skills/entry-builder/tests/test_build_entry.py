import csv
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from build_entry import Ledger, build_bilag, load_config, main  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
with open(os.path.join(FIX, "saft.json"), encoding="utf-8") as fh:
    LEDGER = Ledger(json.load(fh))
CFG = load_config(os.path.join(FIX, "config.json"))


def doc(text="", **values):
    """document-reader shaped document; values given as field=value or field=(None, [cands])."""
    fields = {}
    for name in ("document_type", "vendor_name", "vendor_org_number", "date",
                 "invoice_number", "total_amount", "vat_rate"):
        v = values.get(name)
        if isinstance(v, tuple):
            fields[name] = {"value": None, "status": "unclear", "candidates": v[1], "reason": "x"}
        elif v is None:
            fields[name] = {"value": None, "status": "missing", "candidates": [], "reason": "x"}
        else:
            fields[name] = {"value": v, "status": "ok", "candidates": []}
    fields["total_amount"]["currency"] = values.get("currency", "NOK")
    return {"file": "t.pdf", "status": "ok", "fields": fields, "flags": [], "text": text}


FAKTURA = dict(document_type="faktura", vendor_name="Verksted Service AS",
               vendor_org_number="912345602", date="2025-03-10", invoice_number="2025-0417",
               total_amount=6000, vat_rate=25)


class FakturaTest(unittest.TestCase):
    def test_ready_balanced_entry(self):
        b = build_bilag(doc("Service bil EL 12345", **FAKTURA), LEDGER, CFG)
        self.assertEqual(b["status"], "ready", b["review_reasons"])
        debit, credit = b["lines"]
        self.assertEqual((debit["konto"], debit["mk"], debit["debet"]), ("6600", "1", 6000.0))
        self.assertEqual((debit["loyve"], debit["bil"]), ("L-101", "EL12345"))
        self.assertEqual((credit["konto"], credit["kredit"], credit["supplier_id"]),
                         ("2400", 6000.0, "50010"))
        self.assertIsNone(credit["loyve"])
        self.assertEqual(b["totals"], {"debet": 6000.0, "kredit": 6000.0, "balanced": True})

    def test_vat_account_never_chosen_as_expense(self):
        # 2710 ties with 6600 in history but is ignored.
        b = build_bilag(doc("EL12345", **FAKTURA), LEDGER, CFG)
        self.assertEqual(b["lines"][0]["konto"], "6600")

    def test_missing_loyve_flagged(self):
        b = build_bilag(doc("no car here", **FAKTURA), LEDGER, CFG)
        self.assertEqual(b["status"], "needs_review")
        self.assertIsNone(b["lines"][0]["loyve"])
        self.assertTrue(any("Løyve" in r for r in b["review_reasons"]))

    def test_unknown_supplier_has_no_account(self):
        d = doc("EL12345", **{**FAKTURA, "vendor_name": "Ukjent AS", "vendor_org_number": None})
        b = build_bilag(d, LEDGER, CFG)
        self.assertEqual(b["status"], "needs_review")
        self.assertIsNone(b["lines"][0]["konto"])
        self.assertIsNone(b["lines"][1]["supplier_id"])

    def test_ambiguous_supplier_history_not_guessed(self):
        d = doc("EL12345", **{**FAKTURA, "vendor_name": "Delt Leverandør AS",
                               "vendor_org_number": "987654384"})
        b = build_bilag(d, LEDGER, CFG)
        self.assertIsNone(b["lines"][0]["konto"])
        self.assertTrue(any("several accounts" in r for r in b["review_reasons"]))

    def test_large_amount_flagged_as_possible_asset(self):
        b = build_bilag(doc("EL12345", **{**FAKTURA, "total_amount": 45000}), LEDGER, CFG)
        self.assertEqual(b["status"], "needs_review")
        self.assertTrue(any("driftsmiddel" in r for r in b["review_reasons"]))


class KvitteringTest(unittest.TestCase):
    def test_paid_receipt_credits_bank(self):
        d = doc("Circle K  Bil: EK 54321", document_type="kvittering",
                vendor_name="Circle K Norge AS", vendor_org_number="912345629",
                date="2025-06-14", total_amount=845, vat_rate=25)
        b = build_bilag(d, LEDGER, CFG)
        self.assertEqual(b["status"], "ready", b["review_reasons"])
        self.assertEqual([ln["konto"] for ln in b["lines"]], ["7000", "1920"])
        self.assertIsNone(b["lines"][1]["supplier_id"])
        self.assertEqual(b["header"]["supplier_id"], "50001")
        self.assertEqual(b["lines"][0]["loyve"], "L-102")

    def test_12_percent_maps_to_input_code_not_output(self):
        d = doc("EL12345", document_type="kvittering", vendor_name="Circle K Norge AS",
                vendor_org_number="912345629", date="2025-06-14", total_amount=100, vat_rate=12)
        b = build_bilag(d, LEDGER, CFG)
        self.assertEqual(b["lines"][0]["mk"], "13")  # not 33 (utgående)
        self.assertTrue(any("differs from supplier history" in r for r in b["review_reasons"]))


class BlockedTest(unittest.TestCase):
    def test_mixed_vat_blocked(self):
        d = doc("EL12345", **{**FAKTURA, "vat_rate": (None, [15, 25])})
        b = build_bilag(d, LEDGER, CFG)
        self.assertEqual(b["status"], "blocked")
        self.assertEqual(b["lines"], [])
        self.assertIn("Mixed VAT", b["blocked_reasons"][0])

    def test_mixed_vat_resolved_with_split(self):
        d = doc("EL12345", **{**FAKTURA, "vat_rate": (None, [15, 25])})
        b = build_bilag(d, LEDGER, CFG, splits=[("6600", "1", Decimal("5000.00")),
                                                ("7140", "11", Decimal("1000.00"))])
        self.assertEqual(b["status"], "ready", b["review_reasons"])
        self.assertEqual(len(b["lines"]), 3)
        self.assertTrue(b["totals"]["balanced"])

    def test_split_not_matching_total_blocked(self):
        b = build_bilag(doc("EL12345", **FAKTURA), LEDGER, CFG,
                        splits=[("6600", "1", Decimal("5000.00"))])
        self.assertEqual(b["status"], "blocked")
        self.assertIn("sum to 5000.00", b["blocked_reasons"][0])

    def test_unclear_total_blocked_then_override(self):
        d = doc("EL12345", **{**FAKTURA, "total_amount": (None, [54.8, 59.8])})
        self.assertEqual(build_bilag(d, LEDGER, CFG)["status"], "blocked")
        b = build_bilag(d, LEDGER, CFG, overrides={"total_amount": "59,80"})
        self.assertEqual(b["status"], "ready", b["review_reasons"])
        self.assertEqual(b["totals"]["debet"], 59.8)

    def test_credit_note_or_unclear_type_blocked(self):
        d = doc("EL12345", **{**FAKTURA, "document_type": (None, ["faktura", "kvittering"])})
        self.assertEqual(build_bilag(d, LEDGER, CFG)["status"], "blocked")

    def test_needs_ocr_document_blocked(self):
        b = build_bilag({"file": "s.pdf", "status": "needs_ocr", "fields": None,
                         "flags": ["no text"]}, LEDGER, CFG)
        self.assertEqual(b["status"], "blocked")


class CliTest(unittest.TestCase):
    def test_csv_and_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            dpath = os.path.join(tmp, "docs.json")
            with open(dpath, "w", encoding="utf-8") as fh:
                json.dump({"documents": [doc("EL12345", **FAKTURA)]}, fh)
            out, cpath = os.path.join(tmp, "out.json"), os.path.join(tmp, "out.csv")
            rc = main(["--document", dpath, "--saft", os.path.join(FIX, "saft.json"),
                       "--config", os.path.join(FIX, "config.json"), "-o", out, "--csv", cpath])
            self.assertEqual(rc, 0)
            with open(cpath, encoding="utf-8-sig") as fh:
                rows = list(csv.reader(fh, delimiter=";"))
        self.assertEqual(rows[0], ["Bilag", "Dato", "Konto", "MK", "Debet", "Kredit",
                                   "Løyve", "Bil", "Tekst"])
        self.assertEqual(rows[1][2:8], ["6600", "1", "6000,00", "", "L-101", "EL12345"])
        self.assertEqual(rows[2][2:6], ["2400", "", "", "6000,00"])

    def test_bad_config_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "c.json")
            with open(cfg, "w") as fh:
                json.dump({"payable_acount": "2400"}, fh)
            rc = main(["--document", cfg, "--saft", os.path.join(FIX, "saft.json"),
                       "--config", cfg])
        self.assertEqual(rc, 1)


class PipelineTest(unittest.TestCase):
    """document-reader fixture -> entry-builder, if the sibling skill is present."""

    def test_faktura_fixture_end_to_end(self):
        reader_dir = os.path.join(SKILLS, "document-reader")
        if not os.path.isdir(reader_dir):
            self.skipTest("document-reader skill not installed")
        sys.path.insert(0, os.path.join(reader_dir, "scripts"))
        from read_document import process
        with open(os.path.join(reader_dir, "tests", "fixtures", "faktura.txt"),
                  encoding="utf-8") as fh:
            d = process("faktura.txt", fh.read(), include_text=True)
        b = build_bilag(d, LEDGER, CFG)
        self.assertEqual(b["status"], "ready", b["review_reasons"])
        self.assertEqual([(ln["konto"], ln["debet"], ln["kredit"]) for ln in b["lines"]],
                         [("6600", 6000.0, None), ("2400", None, 6000.0)])


if __name__ == "__main__":
    unittest.main()
