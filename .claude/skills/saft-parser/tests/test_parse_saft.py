import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from parse_saft import SaftError, parse_file  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "sample_v130.xml")


class ParseSaftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = parse_file(FIXTURE)

    def test_meta(self):
        meta = self.result["meta"]
        self.assertEqual(meta["namespace"], "urn:StandardAuditFile-Taxation-Financial:NO")
        self.assertEqual(meta["audit_file_version"], "1.30")
        self.assertEqual(meta["company"]["name"], "Taxi Drift AS")
        self.assertEqual(meta["warnings"], [])

    def test_gl_accounts(self):
        accounts = {a["id"]: a["description"] for a in self.result["gl_accounts"]}
        self.assertEqual(accounts["7000"], "Drivstoff")
        self.assertEqual(accounts["2400"], "Leverandørgjeld")
        self.assertEqual(len(accounts), 4)

    def test_vat_codes(self):
        codes = {c["code"]: c["percentage"] for c in self.result["vat_codes"]}
        self.assertEqual(codes, {"1": 25, "11": 15})

    def test_suppliers(self):
        suppliers = {s["id"]: s["name"] for s in self.result["suppliers"]}
        self.assertEqual(suppliers, {"50001": "Circle K Norge AS",
                                     "50002": "Ubrukt Leverandør AS"})

    def test_supplier_mapping_excludes_payment_bank_account(self):
        (m,) = self.result["supplier_account_mappings"]
        self.assertEqual(m["supplier_id"], "50001")
        self.assertEqual(m["invoice_transactions"], 1)
        self.assertEqual(m["other_transactions"], 1)
        self.assertEqual(m["primary_expense_account"], "7000")
        expense = {e["account_id"]: e for e in m["expense_accounts"]}
        self.assertEqual(set(expense), {"7000", "2710"})
        self.assertEqual(expense["7000"]["tax_codes"], ["1"])
        self.assertEqual(expense["7000"]["total_debit"], 1000)
        self.assertEqual(m["payable_accounts"][0], {
            "account_id": "2400", "account_description": "Leverandørgjeld", "count": 2})

    def test_read_account_postings_bank_account(self):
        from parse_saft import read_account_postings
        r = read_account_postings(FIXTURE, ["1920", "9999"])
        self.assertEqual(r["accounts"]["1920"]["opening_balance"], 10000)
        self.assertEqual(r["accounts"]["1920"]["closing_balance"], 5000)
        (p,) = r["postings"]
        self.assertEqual((p["transaction_id"], p["journal_id"], p["date"], p["amount"]),
                         ("2001", "BANK", "2025-03-20", -1250))
        self.assertEqual([ln["account_id"] for ln in p["voucher"]["lines"]], ["2400", "1920"])
        self.assertTrue(any("9999" in w for w in r["meta"]["warnings"]))

    def _write(self, content):
        fd, path = tempfile.mkstemp(suffix=".xml")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        self.addCleanup(os.remove, path)
        return path

    def test_wrong_namespace_rejected(self):
        path = self._write('<AuditFile xmlns="urn:OECD:StandardAuditFile-Tax:PT_1.04_01"/>')
        with self.assertRaises(SaftError) as ctx:
            parse_file(path)
        self.assertEqual(ctx.exception.exit_code, 2)

    def test_wrong_namespace_allowed_with_flag(self):
        path = self._write('<AuditFile xmlns="urn:other"><Header>'
                           '<AuditFileVersion>1.30</AuditFileVersion></Header></AuditFile>')
        result = parse_file(path, allow_other_namespace=True)
        self.assertEqual(len(result["meta"]["warnings"]), 1)

    def test_invalid_xml(self):
        path = self._write("<AuditFile")
        with self.assertRaises(SaftError) as ctx:
            parse_file(path)
        self.assertEqual(ctx.exception.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
