import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(HERE, "..")
sys.path.insert(0, SERVER_DIR)

from bank_store import PROJECT_ROOT, BankError, BankStore  # noqa: E402

FIX = os.path.join(PROJECT_ROOT, ".claude", "skills", "bank-matcher", "tests", "fixtures")
CSV_BANK = os.path.join(FIX, "bank_dnb.csv")
CAMT_BANK = os.path.join(FIX, "bank_camt053.xml")

# document-mcp "summary" shaped documents (+ id)
DOCS = [
    {"id": "verksted.pdf", "supplier": "Verksted Service AS", "date": "2025-03-10",
     "amount": 6000, "invoice_number": "2025-0417", "type": "faktura"},
    {"id": "circlek.pdf", "supplier": "Circle K Norge AS", "date": "2025-06-13",
     "amount": 845, "type": "kvittering"},
    {"id": "kiwi.pdf", "supplier": "Kiwi Majorstuen", "date": "2025-06-19", "amount": 500,
     "type": "kvittering"},
    {"id": "telenor.pdf", "supplier": "Telenor Norge AS", "date": "2025-05-01",
     "amount": 1234, "type": "faktura"},
    {"id": "uklar.pdf", "supplier": "Bunnpris", "amount": None, "type": "kvittering"},
]


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.store = BankStore(roots=[])
        self.store.load(CSV_BANK)

    def test_not_loaded(self):
        with self.assertRaises(BankError) as ctx:
            BankStore(roots=[]).summary()
        self.assertIn("load_bank_statement", str(ctx.exception))

    def test_summary(self):
        s = self.store.summary()
        self.assertEqual((s["lines"], s["outgoing"], s["incoming"]), (6, 5, 1))
        self.assertEqual(s["total_out"], 8244.0)
        self.assertEqual(s["total_in"], 12500.0)
        self.assertEqual((s["date_from"], s["date_to"]), ("2025-03-24", "2025-07-05"))

    def test_list_transactions_filters(self):
        self.assertEqual(self.store.list_transactions("incoming")["total"], 1)
        r = self.store.list_transactions("outgoing", date_from="2025-06-01",
                                         date_to="20.06.2025", min_amount=500, max_amount=500)
        self.assertEqual(r["total"], 2)
        self.assertEqual(self.store.list_transactions(query="circle")["items"][0]["amount"],
                         -845.0)
        with self.assertRaises(BankError):
            self.store.list_transactions("sideways")
        with self.assertRaises(BankError):
            self.store.list_transactions(date_from="yesterday")

    def test_find_payment(self):
        r = self.store.find_payment(6000, "2025-03-10", "Verksted Service AS",
                                    invoice_number="2025-0417", document_type="faktura")
        self.assertEqual(r["candidates"][0]["vendor_signal"], "reference")
        self.assertEqual(r["window_days"], [-3, 60])
        two = self.store.find_payment(500, "2025-06-19", document_type="kvittering")
        self.assertEqual(len(two["candidates"]), 2)
        with self.assertRaises(BankError):
            self.store.find_payment(0)

    def test_match_documents_summary_shape(self):
        r = self.store.match_documents(DOCS)
        status = {d["id"]: d["status"] for d in r["documents"]}
        self.assertEqual(status, {"verksted.pdf": "paid", "circlek.pdf": "paid",
                                  "kiwi.pdf": "uncertain", "telenor.pdf": "not_found",
                                  "uklar.pdf": "unmatchable"})
        self.assertEqual([ln["text"] for ln in r["unmatched_outgoing_bank_lines"]
                          if "UKJENT" in ln["text"]], ["Kortkjøp UKJENT BUTIKK"])
        self.assertEqual(r["settings"]["tolerance"], 0.0)

    def test_match_validation(self):
        with self.assertRaises(BankError):
            self.store.match_documents([])
        with self.assertRaises(BankError):
            self.store.match_documents([{"amount": 1, "type": "kreditnota"}])
        with self.assertRaises(BankError):
            self.store.match_documents(DOCS, tolerance=-1)
        with self.assertRaises(BankError):
            self.store.match_documents(DOCS, invoice_days=0)

    def test_match_documents_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bilag.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"bilag": [{"source_file": "v.pdf", "header": {
                    "date": "2025-03-10", "document_type": "faktura",
                    "vendor_name": "Verksted Service AS", "invoice_number": "2025-0417",
                    "total_amount": 6000.0}}]}, fh)
            r = self.store.match_documents_file(path)
        self.assertEqual(r["documents"][0]["status"], "paid")

    def test_camt_and_reload_on_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.xml")
            shutil.copy(CAMT_BANK, path)
            store = BankStore(roots=[tmp])
            self.assertEqual(store.load(path)["format"], "camt")
            self.assertEqual(store.summary()["outgoing"], 1)
            with open(CAMT_BANK, encoding="utf-8") as fh:
                xml = fh.read().replace("<Amt Ccy=\"NOK\">12500.00</Amt>\n        "
                                        "<CdtDbtInd>CRDT</CdtDbtInd>",
                                        "<Amt Ccy=\"NOK\">12500.00</Amt>\n        "
                                        "<CdtDbtInd>DBIT</CdtDbtInd>")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(xml)
            os.utime(path, ns=(1, 1))
            self.assertEqual(store.summary()["outgoing"], 2)

    def test_sandbox_and_file_types(self):
        other = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, other)
        with self.assertRaises(BankError) as ctx:
            BankStore(roots=[other]).load(CSV_BANK)
        self.assertIn("outside", str(ctx.exception))
        with self.assertRaises(BankError):
            self.store.load(os.path.abspath(__file__))  # .py not allowed
        with self.assertRaises(BankError):
            self.store.match_documents_file(CSV_BANK)  # must be .json


class StdioServerTest(unittest.TestCase):
    def test_tools_over_stdio(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            self.skipTest("mcp SDK not installed")

        async def scenario():
            params = StdioServerParameters(
                command=sys.executable, args=[os.path.join(SERVER_DIR, "server.py")],
                env={**os.environ, "BANK_FILE": CSV_BANK, "BANK_ROOTS": FIX})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    summary = await session.call_tool("get_statement_summary", {})
                    match = await session.call_tool("match_documents", {"documents": DOCS})
                    outside = await session.call_tool("load_bank_statement",
                                                      {"path": os.path.abspath(__file__)})
                    return names, summary, match, outside

        names, summary, match, outside = asyncio.run(scenario())
        self.assertEqual(names, {"load_bank_statement", "get_statement_summary",
                                 "list_transactions", "find_payment", "match_documents",
                                 "match_documents_file"})
        self.assertEqual(json.loads(summary.content[0].text)["lines"], 6)  # preloaded
        counts = json.loads(match.content[0].text)["status_counts"]
        self.assertEqual(counts, {"paid": 2, "uncertain": 1, "not_found": 1, "unmatchable": 1})
        self.assertTrue(outside.isError)


if __name__ == "__main__":
    unittest.main()
