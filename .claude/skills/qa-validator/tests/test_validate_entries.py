import copy
import csv
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from validate_entries import main, validate_all  # noqa: E402

TODAY = dt.date(2026, 11, 10)
SAFT = {
    "gl_accounts": [{"id": a} for a in ("1920", "2400", "2710", "3000", "6600", "7000")],
    "vat_codes": [
        {"code": "0", "standard_tax_code": "0"},
        {"code": "1", "percentage": 25, "standard_tax_code": "1"},
        {"code": "3", "percentage": 25, "standard_tax_code": "3"},
        {"code": "8", "percentage": 10, "standard_tax_code": "13",
         "effective_date": "2020-04-01", "expiration_date": "2021-09-30"},
    ],
    "suppliers": [{"id": "50010"}, {"id": "50001"}],
}
CFG = {"payable_account": "2400",
       "loyver": [{"loyve": "L-101", "bil": "EL12345"}, {"loyve": "L-102", "bil": "EK54321"}]}


def bilag(**over):
    b = {
        "source_file": "verksted.pdf", "status": "ready",
        "header": {"date": "2025-03-10", "document_type": "faktura",
                   "vendor_name": "Verksted Service AS", "supplier_id": "50010",
                   "invoice_number": "2025-0417", "total_amount": 6000.0, "currency": "NOK"},
        "lines": [
            {"konto": "6600", "mk": "1", "debet": 6000.0, "kredit": None,
             "loyve": "L-101", "bil": "EL12345", "supplier_id": None},
            {"konto": "2400", "mk": None, "debet": None, "kredit": 6000.0,
             "loyve": None, "bil": None, "supplier_id": "50010"},
        ],
        "totals": {"debet": 6000.0, "kredit": 6000.0, "balanced": True},
        "review_reasons": [], "blocked_reasons": [],
    }
    for path, value in over.items():
        target, *keys = path.split("__")
        obj = b[target]
        for k in keys[:-1]:
            obj = obj[int(k)] if isinstance(obj, list) else obj[k]
        last = keys[-1] if keys else None
        if last is None:
            b[target] = value
        elif isinstance(obj, list):
            obj[int(last)] = value
        else:
            obj[last] = value
    return b


def codes(result, i=0):
    return [e["code"] for e in result["bilag"][i]["qa_errors"]]


def check(*bilag_list, cfg=CFG):
    return validate_all(list(bilag_list), copy.deepcopy(SAFT), cfg, TODAY)


class PassTest(unittest.TestCase):
    def test_valid_bilag_passes(self):
        r = check(bilag())
        self.assertEqual(r["bilag"][0]["qa_status"], "passed", r["bilag"][0]["qa_errors"])
        self.assertEqual(r["bilag"][0]["qa_warnings"], [])
        self.assertEqual(r["summary"], {"bilag": 1, "passed": 1, "blocked": 0, "error_codes": {}})

    def test_upstream_review_reason_is_warning_only(self):
        r = check(bilag(status="needs_review", review_reasons=["Amount ≥ 30000"]))
        self.assertEqual(r["bilag"][0]["qa_status"], "passed")
        self.assertEqual(r["bilag"][0]["qa_warnings"][0]["code"], "UPSTREAM_REVIEW")


class BalanceTest(unittest.TestCase):
    def test_unbalanced_blocked(self):
        r = check(bilag(lines__1__kredit=5999.99))
        self.assertIn("UNBALANCED", codes(r))
        self.assertEqual(r["bilag"][0]["qa_status"], "blocked")

    def test_false_balanced_claim_caught(self):
        self.assertIn("TOTALS_INCONSISTENT", codes(check(bilag(lines__1__kredit=100.0))))

    def test_header_total_mismatch(self):
        self.assertIn("AMOUNT_MISMATCH", codes(check(bilag(header__total_amount=6500.0))))

    def test_line_with_both_sides_or_negative(self):
        self.assertIn("LINE_AMOUNT_INVALID", codes(check(bilag(lines__0__kredit=1.0))))
        self.assertIn("LINE_AMOUNT_INVALID", codes(check(bilag(lines__0__debet=-6000.0))))

    def test_no_lines(self):
        self.assertIn("NO_LINES", codes(check(bilag(lines=[]))))


class AccountAndVatTest(unittest.TestCase):
    def test_unknown_and_missing_account(self):
        self.assertIn("UNKNOWN_ACCOUNT", codes(check(bilag(lines__0__konto="6601"))))
        self.assertIn("MISSING_ACCOUNT", codes(check(bilag(lines__0__konto=None))))

    def test_unknown_mk(self):
        self.assertIn("INVALID_MK", codes(check(bilag(lines__0__mk="99"))))

    def test_expired_mk(self):
        r = check(bilag(lines__0__mk="8"))
        self.assertIn("INVALID_MK", codes(r))
        self.assertIn("not valid on 2025-03-10", r["bilag"][0]["qa_errors"][0]["message"])

    def test_output_mk_on_cost_line(self):
        self.assertIn("OUTPUT_MK_ON_COST", codes(check(bilag(lines__0__mk="3"))))

    def test_missing_mk_on_pl_line(self):
        self.assertIn("MISSING_MK", codes(check(bilag(lines__0__mk=None))))

    def test_mk_zero_is_valid(self):
        self.assertEqual(check(bilag(lines__0__mk="0"))["bilag"][0]["qa_status"], "passed")

    def test_mk_on_balance_line_warns(self):
        r = check(bilag(lines__1__mk="1"))
        self.assertEqual(r["bilag"][0]["qa_status"], "passed")
        self.assertEqual(r["bilag"][0]["qa_warnings"][0]["code"], "MK_ON_BALANCE_LINE")


class RequiredFieldTest(unittest.TestCase):
    def test_missing_date_and_future_date(self):
        self.assertIn("MISSING_DATE", codes(check(bilag(header__date=None))))
        self.assertIn("FUTURE_DATE", codes(check(bilag(header__date="2027-01-01"))))
        self.assertIn("INVALID_DATE", codes(check(bilag(header__date="10.03.2025"))))

    def test_missing_amount(self):
        self.assertIn("MISSING_AMOUNT", codes(check(bilag(header__total_amount=None))))

    def test_missing_loyve(self):
        self.assertIn("MISSING_LOYVE", codes(check(bilag(lines__0__loyve=None))))

    def test_unknown_loyve_and_bil_mismatch(self):
        self.assertIn("UNKNOWN_LOYVE", codes(check(bilag(lines__0__loyve="L-999"))))
        self.assertIn("BIL_MISMATCH", codes(check(bilag(lines__0__bil="EK54321"))))

    def test_loyve_unchecked_without_config(self):
        r = check(bilag(), cfg={})
        self.assertEqual(r["bilag"][0]["qa_status"], "passed")
        self.assertEqual(r["bilag"][0]["qa_warnings"][0]["code"], "LOYVE_UNCHECKED")

    def test_supplier_checks(self):
        self.assertIn("MISSING_SUPPLIER", codes(check(bilag(lines__1__supplier_id=None))))
        self.assertIn("UNKNOWN_SUPPLIER", codes(check(bilag(lines__1__supplier_id="99999"))))

    def test_foreign_currency(self):
        self.assertIn("FOREIGN_CURRENCY", codes(check(bilag(header__currency="EUR"))))


class BatchTest(unittest.TestCase):
    def test_duplicate_invoice_blocked(self):
        r = check(bilag(), bilag(source_file="kopi.pdf"))
        self.assertEqual([b["qa_status"] for b in r["bilag"]], ["passed", "blocked"])
        self.assertEqual(codes(r, 1), ["DUPLICATE_INVOICE"])

    def test_possible_duplicate_receipt_warns(self):
        a = bilag(header__invoice_number=None)
        r = check(a, copy.deepcopy(a))
        self.assertEqual(r["bilag"][1]["qa_warnings"][0]["code"], "POSSIBLE_DUPLICATE")

    def test_upstream_blocked_stays_blocked(self):
        r = check(bilag(status="blocked", lines=[], blocked_reasons=["Mixed VAT rates"]))
        self.assertEqual(codes(r), ["UPSTREAM_BLOCKED"])


class CliTest(unittest.TestCase):
    def test_exit_codes_and_csv_contains_only_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            def dump(name, data):
                p = os.path.join(tmp, name)
                with open(p, "w", encoding="utf-8") as fh:
                    json.dump(data, fh)
                return p
            saft, cfg = dump("s.json", SAFT), dump("c.json", CFG)
            good = dump("g.json", {"bilag": [bilag()]})
            mixed = dump("m.json", {"bilag": [bilag(), bilag(source_file="x.pdf",
                                                           lines__0__konto="9999")]})
            out, csv_path = os.path.join(tmp, "o.json"), os.path.join(tmp, "p.csv")
            self.assertEqual(main(["--entries", good, "--saft", saft, "--config", cfg,
                                   "-o", out]), 0)
            self.assertEqual(main(["--entries", mixed, "--saft", saft, "--config", cfg,
                                   "-o", out, "--csv", csv_path]), 2)
            with open(csv_path, encoding="utf-8-sig") as fh:
                rows = list(csv.reader(fh, delimiter=";"))
            self.assertEqual(main(["--entries", saft, "--saft", saft]), 1)
        self.assertEqual(len(rows), 3)  # header + 2 lines of the one passed bilag
        self.assertEqual(rows[1][2], "6600")


class PipelineTest(unittest.TestCase):
    def test_entry_builder_output_passes_gate(self):
        eb = os.path.join(SKILLS, "entry-builder")
        if not os.path.isdir(eb):
            self.skipTest("entry-builder skill not installed")
        sys.path.insert(0, os.path.join(eb, "scripts"))
        from build_entry import Ledger, build_bilag, load_config
        with open(os.path.join(eb, "tests", "fixtures", "saft.json"), encoding="utf-8") as fh:
            saft = json.load(fh)
        cfg = load_config(os.path.join(eb, "tests", "fixtures", "config.json"))
        fields = {k: {"value": v, "status": "ok", "candidates": []} for k, v in {
            "document_type": "faktura", "vendor_name": "Verksted Service AS",
            "vendor_org_number": "912345602", "date": "2025-03-10",
            "invoice_number": "2025-0417", "total_amount": 6000, "vat_rate": 25}.items()}
        fields["total_amount"]["currency"] = "NOK"
        doc = {"file": "v.pdf", "status": "ok", "fields": fields, "text": "bil EL12345"}
        ready = build_bilag(doc, Ledger(saft), cfg)
        draft = build_bilag({**doc, "text": ""}, Ledger(saft), cfg)  # no løyve found
        r = validate_all([ready, draft], saft, cfg, TODAY)
        self.assertEqual(r["bilag"][0]["qa_status"], "passed", r["bilag"][0]["qa_errors"])
        self.assertEqual(r["bilag"][1]["qa_status"], "blocked")
        self.assertIn("MISSING_LOYVE", codes(r, 1))


if __name__ == "__main__":
    unittest.main()
