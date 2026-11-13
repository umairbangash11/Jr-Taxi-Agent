r"""Scenario (hand-checked):

SAF-T 1920 opening 10 000. Postings (bilag):
  100  2025-02-10  -1000   before period
  101  2025-03-24  -6000   Verksted (supplier 50010)        bank 24.03 -6000
  102  2025-06-15   -845   Circle K                         bank 15.06  -845
  103  2025-06-20   -300 \  two invoices paid in one        bank 20.06  -500
  104  2025-06-20   -200 /  bank transfer
  105  2025-06-30  -1500   supplier 50030, NOT on bank      -> ledger_only
  106  2025-07-01 +12500   income                           bank 01.07 +12500
  107  2025-08-15   -999   after period
Bank only: 05.07 -399 (UKJENT BUTIKK), 10.07 -50 (Gebyr)    -> bank_only

Period 2025-03-01..2025-07-31, bank opening 9000:
  ledger open 9000, movement +3655, close 12655
  bank   open 9000, movement +4706, close 13706
  difference -1051 = ledger_only (-1500) - bank_only (-449); unexplained 0
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(HERE, "..")
sys.path.insert(0, SERVER_DIR)

from reconcile_store import ReconcileError, ReconcileStore  # noqa: E402

LEDGER = [  # (bilag, date, amount on 1920, counter account, supplier)
    ("100", "2025-02-10", -1000, "6300", None),
    ("101", "2025-03-24", -6000, "2400", "50010"),
    ("102", "2025-06-15", -845, "7000", None),
    ("103", "2025-06-20", -300, "2400", "50020"),
    ("104", "2025-06-20", -200, "2400", "50021"),
    ("105", "2025-06-30", -1500, "2400", "50030"),
    ("106", "2025-07-01", 12500, "3000", None),
    ("107", "2025-08-15", -999, "6300", None),
]
BANK = [  # (date, amount, text)
    ("2025-03-24", -6000, "Nettgiro til Verksted Service AS"),
    ("2025-06-15", -845, "CIRCLE K TRONDHEIM"),
    ("2025-06-20", -500, "Samlebetaling 2 fakturaer"),
    ("2025-07-01", 12500, "Innbetaling turer"),
    ("2025-07-05", -399, "Kortkjøp UKJENT BUTIKK"),
    ("2025-07-10", -50, "Gebyr"),
]


def saft_xml(ledger, opening=10000):
    def line(rid, acct, amount, sup=None):
        side = "DebitAmount" if amount > 0 else "CreditAmount"
        s = f"<n1:SupplierID>{sup}</n1:SupplierID>" if sup else ""
        return (f"<n1:Line><n1:RecordID>{rid}</n1:RecordID><n1:AccountID>{acct}</n1:AccountID>{s}"
                f"<n1:Description>Linje</n1:Description>"
                f"<n1:{side}><n1:Amount>{abs(amount):.2f}</n1:Amount></n1:{side}></n1:Line>")
    txs = "".join(
        f"<n1:Transaction><n1:TransactionID>{b}</n1:TransactionID>"
        f"<n1:TransactionDate>{d}</n1:TransactionDate><n1:Description>Bilag {b}</n1:Description>"
        + line(1, "1920", amt) + line(2, acct, -amt, sup) + "</n1:Transaction>"
        for b, d, amt, acct, sup in ledger)
    accounts = "".join(f"<n1:Account><n1:AccountID>{a}</n1:AccountID>"
                       f"<n1:AccountDescription>K{a}</n1:AccountDescription>"
                       f"<n1:OpeningDebitBalance>{opening if a == '1920' else 0}"
                       f"</n1:OpeningDebitBalance></n1:Account>"
                       for a in ("1920", "2400", "3000", "6300", "7000"))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<n1:AuditFile xmlns:n1="urn:StandardAuditFile-Taxation-Financial:NO">'
            "<n1:Header><n1:AuditFileVersion>1.30</n1:AuditFileVersion></n1:Header>"
            f"<n1:MasterFiles><n1:GeneralLedgerAccounts>{accounts}</n1:GeneralLedgerAccounts>"
            "</n1:MasterFiles><n1:GeneralLedgerEntries><n1:Journal>"
            f"<n1:JournalID>GL</n1:JournalID>{txs}</n1:Journal></n1:GeneralLedgerEntries>"
            "</n1:AuditFile>")


def bank_csv(rows):
    out = ["Dato;Forklaring;Uttak;Innskudd"]
    for d, amt, text in rows:
        y, m, dd = d.split("-")
        money = f"{abs(amt):.2f}".replace(".", ",")
        out.append(f"{dd}.{m}.{y};{text};{money if amt < 0 else ''};{money if amt > 0 else ''}")
    return "\n".join(out) + "\n"


def camt_xml(rows, opening, closing):
    def bal(code, amt, date):
        ind = "CRDT" if amt >= 0 else "DBIT"
        return (f"<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp>"
                f"<Amt Ccy=\"NOK\">{abs(amt):.2f}</Amt><CdtDbtInd>{ind}</CdtDbtInd>"
                f"<Dt><Dt>{date}</Dt></Dt></Bal>")
    ntry = "".join(f"<Ntry><Amt Ccy=\"NOK\">{abs(a):.2f}</Amt>"
                   f"<CdtDbtInd>{'CRDT' if a > 0 else 'DBIT'}</CdtDbtInd>"
                   f"<BookgDt><Dt>{d}</Dt></BookgDt><AddtlNtryInf>{t}</AddtlNtryInf></Ntry>"
                   for d, a, t in rows)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt>'
            f"<Stmt><Id>S</Id>{bal('OPBD', opening[1], opening[0])}"
            f"{bal('CLBD', closing[1], closing[0])}{ntry}</Stmt></BkToCstmrStmt></Document>")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def write(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def store(self, ledger=LEDGER, bank=BANK, camt=None):
        s = ReconcileStore(roots=[self.tmp])
        s.load_ledger(self.write("saft.xml", saft_xml(ledger)))
        if camt:
            s.load_bank(self.write("bank.xml", camt_xml(bank, *camt)))
        else:
            s.load_bank(self.write("bank.csv", bank_csv(bank)))
        return s


class ReconcileTest(Base):
    def test_full_period_difference_itemised(self):
        r = self.store().reconcile("2025-03-01", "2025-07-31", bank_opening_balance=9000)
        self.assertEqual(r["status"], "differences")
        self.assertEqual(r["ledger"], {"opening_balance": 9000.0, "movement": 3655.0,
                                       "closing_balance": 12655.0, "postings": 6})
        self.assertEqual((r["bank"]["closing_balance"], r["bank"]["balance_source"]),
                         (13706.0, "user"))
        d = r["difference"]
        self.assertEqual((d["closing_balance"], d["opening_balance"], d["explained_by_items"],
                          d["unexplained"]), (-1051.0, 0.0, -1051.0, 0.0))
        (lo,) = r["ledger_only"]
        self.assertEqual((lo["bilag"], lo["amount"], lo["date"]), ("105", -1500.0, "2025-06-30"))
        self.assertEqual(lo["counter_lines"][0]["supplier_id"], "50030")
        self.assertEqual([b["amount"] for b in r["bank_only"]], [-399.0, -50.0])
        (combo,) = r["combined_matches"]
        self.assertEqual((sorted(combo["bilag"]), combo["type"]),
                         (["103", "104"], "several bilag, one bank line"))
        self.assertEqual(r["matched_one_to_one"], 3)

    def test_movement_only_without_bank_balance(self):
        r = self.store().reconcile("2025-03-01", "2025-07-31")
        self.assertIsNone(r["difference"]["closing_balance"])
        self.assertEqual(r["difference"]["movement"], -1051.0)
        self.assertTrue(any("Bank balances unknown" in w for w in r["warnings"]))

    def test_default_period_is_statement_range(self):
        r = self.store().reconcile(bank_closing_balance=13706)
        self.assertEqual(r["period"], {"from": "2025-03-24", "to": "2025-07-10"})
        self.assertEqual(r["difference"]["unexplained"], 0.0)

    def test_reconciled_when_everything_matches(self):
        ledger = [x for x in LEDGER if x[0] != "105"] + [
            ("108", "2025-07-05", -399, "7000", None), ("109", "2025-07-10", -50, "7770", None)]
        r = self.store(ledger=ledger).reconcile("2025-03-01", "2025-07-31",
                                                bank_opening_balance=9000)
        self.assertEqual(r["status"], "reconciled")
        self.assertEqual(r["difference"]["closing_balance"], 0.0)
        self.assertEqual((r["ledger_only"], r["bank_only"]), ([], []))

    def test_unexplained_when_opening_differs(self):
        r = self.store().reconcile("2025-03-01", "2025-07-31", bank_opening_balance=9100)
        self.assertEqual(r["difference"]["opening_balance"], -100.0)
        self.assertEqual(r["difference"]["unexplained"], -100.0)
        self.assertTrue(any("Unexplained difference" in w for w in r["warnings"]))

    def test_camt_balances_rolled_to_subperiod(self):
        s = self.store(camt=(("2025-03-01", 9000), ("2025-07-31", 13706)))
        r = s.reconcile("2025-06-01", "2025-06-30")
        self.assertEqual(r["bank"]["balance_source"], "statement")
        self.assertEqual((r["ledger"]["opening_balance"], r["bank"]["opening_balance"]),
                         (3000.0, 3000.0))
        self.assertEqual(r["difference"]["closing_balance"], -1500.0)
        self.assertEqual([x["bilag"] for x in r["ledger_only"]], ["105"])
        self.assertEqual(r["difference"]["unexplained"], 0.0)

    def test_camt_inconsistent_balances_warned(self):
        s = self.store(camt=(("2025-03-01", 9000), ("2025-07-31", 99999)))
        r = s.reconcile("2025-03-01", "2025-07-31")
        self.assertTrue(any("inconsistent" in w for w in r["warnings"]))

    def test_ambiguous_pairing_reported(self):
        ledger = [("201", "2025-06-15", -845, "7000", None), ("202", "2025-06-15", -845, "7000", None)]
        bank = [("2025-06-15", -845, "CIRCLE K A"), ("2025-06-15", -845, "CIRCLE K B")]
        r = self.store(ledger, bank).reconcile(bank_opening_balance=10000)
        self.assertEqual(r["status"], "reconciled")
        self.assertEqual(len(r["ambiguous_pairings"]), 2)

    def test_ambiguous_combinations_left_unmatched(self):
        ledger = [(b, "2025-06-20", a, "2400", None)
                  for b, a in (("301", -300), ("302", -200), ("303", -250), ("304", -250))]
        bank = [("2025-06-20", -500, "Samlebetaling")]
        r = self.store(ledger, bank).reconcile()
        self.assertEqual(r["combined_matches"], [])
        self.assertEqual(len(r["possible_combinations"][0]["options"]), 2)
        self.assertEqual(len(r["ledger_only"]), 4)

    def test_one_bilag_several_bank_lines(self):
        ledger = [("401", "2025-06-20", -500, "2400", None)]
        bank = [("2025-06-20", -300, "Del 1"), ("2025-06-21", -200, "Del 2")]
        r = self.store(ledger, bank).reconcile()
        self.assertEqual(r["combined_matches"][0]["type"], "one bilag, several bank lines")
        self.assertEqual(r["status"], "reconciled")

    def test_date_window(self):
        bank = [("2025-03-31", -6000, "Verksted")]  # 7 days after bilag 101
        ledger = [x for x in LEDGER if x[0] == "101"]
        self.assertEqual(len(self.store(ledger, bank).reconcile(
            "2025-03-20", "2025-03-31", date_window=5)["ledger_only"]), 1)
        self.assertEqual(self.store(ledger, bank).reconcile(
            "2025-03-20", "2025-03-31", date_window=7)["matched_one_to_one"], 1)

    def test_get_bilag(self):
        v = self.store().get_bilag("105")
        self.assertEqual([ln["account_id"] for ln in v["lines"]], ["1920", "2400"])
        with self.assertRaises(ReconcileError):
            self.store().get_bilag("999")

    def test_errors(self):
        s = ReconcileStore(roots=[self.tmp])
        with self.assertRaises(ReconcileError) as ctx:
            s.reconcile()
        self.assertIn("No ledger loaded", str(ctx.exception))
        saft = self.write("saft.xml", saft_xml(LEDGER))
        with self.assertRaises(ReconcileError):
            s.load_ledger(saft, account_id="1999")
        with self.assertRaises(ReconcileError):
            ReconcileStore(roots=[tempfile.gettempdir() + "_nope"]).load_ledger(saft)
        s2 = self.store()
        with self.assertRaises(ReconcileError):
            s2.reconcile("2025-07-31", "2025-03-01")
        with self.assertRaises(ReconcileError):
            s2.reconcile(date_window=90)

    def test_reload_on_bank_change(self):
        s = self.store()
        self.assertEqual(len(s.reconcile()["bank_only"]), 2)
        path = os.path.join(self.tmp, "bank.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(bank_csv(BANK + [("2025-07-10", -1, "Ekstra")]))
        os.utime(path, ns=(1, 1))
        self.assertEqual(len(s.reconcile()["bank_only"]), 3)


class StdioServerTest(Base):
    def test_tools_over_stdio(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            self.skipTest("mcp SDK not installed")
        saft = self.write("saft.xml", saft_xml(LEDGER))
        bank = self.write("bank.csv", bank_csv(BANK))

        async def scenario():
            params = StdioServerParameters(
                command=sys.executable, args=[os.path.join(SERVER_DIR, "server.py")],
                env={**os.environ, "SAFT_FILE": saft, "BANK_FILE": bank,
                     "RECONCILE_ROOTS": self.tmp})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    rec = await session.call_tool("reconcile", {
                        "date_from": "2025-03-01", "date_to": "2025-07-31",
                        "bank_opening_balance": 9000})
                    bilag = await session.call_tool("get_bilag", {"transaction_id": "105"})
                    outside = await session.call_tool("load_ledger",
                                                      {"saft_path": os.path.abspath(__file__)})
                    return names, rec, bilag, outside

        names, rec, bilag, outside = asyncio.run(scenario())
        self.assertEqual(names, {"load_ledger", "load_bank_statement", "reconcile", "get_bilag"})
        r = json.loads(rec.content[0].text)
        self.assertEqual(r["difference"]["closing_balance"], -1051.0)
        self.assertEqual([x["bilag"] for x in r["ledger_only"]], ["105"])
        self.assertEqual(json.loads(bilag.content[0].text)["transaction_id"], "105")
        self.assertTrue(outside.isError)


if __name__ == "__main__":
    unittest.main()
