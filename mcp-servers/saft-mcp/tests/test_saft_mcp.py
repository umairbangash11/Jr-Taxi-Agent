import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(HERE, "..")
sys.path.insert(0, SERVER_DIR)

from saft_store import PROJECT_ROOT, SaftStore, StoreError  # noqa: E402

FIXTURE = os.path.join(PROJECT_ROOT, ".claude", "skills", "saft-parser", "tests", "fixtures",
                       "sample_v130.xml")


class StoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = SaftStore(FIXTURE)

    def test_no_file_loaded(self):
        with self.assertRaises(StoreError) as ctx:
            SaftStore().summary()
        self.assertIn("load_saft_file", str(ctx.exception))

    def test_missing_and_invalid_file(self):
        with self.assertRaises(StoreError):
            SaftStore("nope.xml")
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.xml")
            with open(bad, "w") as fh:
                fh.write("<AuditFile xmlns='urn:other'/>")
            with self.assertRaises(StoreError) as ctx:
                SaftStore(bad)
            self.assertIn("namespace", str(ctx.exception))

    def test_summary(self):
        s = self.store.summary()
        self.assertEqual(s["company"]["name"], "Taxi Drift AS")
        self.assertEqual(s["counts"]["gl_accounts"], 4)

    def test_list_accounts_filters(self):
        self.assertEqual(self.store.list_accounts()["total"], 4)
        self.assertEqual([a["id"] for a in self.store.list_accounts(prefix="2")["items"]],
                         ["2400", "2710"])
        self.assertEqual(self.store.list_accounts(query="drivstoff")["items"][0]["id"], "7000")
        r = self.store.list_accounts(limit=1)
        self.assertTrue(r["truncated"])
        self.assertEqual(r["returned"], 1)

    def test_get_account_with_reverse_lookup(self):
        acc = self.store.get_account("7000")
        self.assertEqual(acc["description"], "Drivstoff")
        self.assertEqual(acc["used_by_suppliers"][0]["supplier_id"], "50001")
        with self.assertRaises(StoreError):
            self.store.get_account("9999")

    def test_vat_codes_direction(self):
        codes = self.store.list_vat_codes()["items"]
        self.assertEqual({c["code"]: c["direction"] for c in codes}, {"1": "input", "11": "input"})
        self.assertEqual(self.store.list_vat_codes("output")["total"], 0)
        with self.assertRaises(StoreError):
            self.store.list_vat_codes("sideways")

    def test_find_vat_code(self):
        r = self.store.find_vat_code(25)
        self.assertEqual((r["status"], r["matches"][0]["code"]), ("unique", "1"))
        self.assertEqual(self.store.find_vat_code("15%")["matches"][0]["code"], "11")
        self.assertEqual(self.store.find_vat_code(12)["status"], "none")
        self.assertEqual(self.store.find_vat_code(25, direction="output")["status"], "none")
        with self.assertRaises(StoreError):
            self.store.find_vat_code("abc")

    def test_search_suppliers(self):
        self.assertEqual(self.store.search_suppliers()["total"], 2)
        hit = self.store.search_suppliers(query="circle k")["items"]
        self.assertEqual([(s["id"], s["has_history"]) for s in hit], [("50001", True)])
        self.assertEqual(self.store.search_suppliers(org_number="911 222 333")["items"][0]["id"],
                         "50001")
        self.assertEqual(self.store.search_suppliers(query="50002")["items"][0]["has_history"],
                         False)

    def test_supplier_history(self):
        h = self.store.get_supplier_history("50001")
        exp = {e["account_id"]: e for e in h["expense_accounts"]}
        self.assertEqual(exp["7000"]["share_of_cost_lines"], 1.0)
        self.assertTrue(exp["2710"]["is_vat_account"])
        self.assertIsNone(exp["2710"]["share_of_cost_lines"])
        self.assertEqual(h["payable_accounts"][0]["account_id"], "2400")
        self.assertIn("No transactions", self.store.get_supplier_history("50002")["note"])
        with self.assertRaises(StoreError):
            self.store.get_supplier_history("00000")

    def test_reload_on_file_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.xml")
            shutil.copy(FIXTURE, path)
            store = SaftStore(path)
            self.assertIsNone(store.list_accounts(query="Kontanter")["items"] or None)
            with open(FIXTURE, encoding="utf-8") as fh:
                xml = fh.read().replace(
                    "<n1:GeneralLedgerAccounts>",
                    "<n1:GeneralLedgerAccounts><n1:Account><n1:AccountID>1900</n1:AccountID>"
                    "<n1:AccountDescription>Kontanter</n1:AccountDescription></n1:Account>", 1)
            time.sleep(0.01)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(xml)
            self.assertEqual(store.list_accounts(query="Kontanter")["items"][0]["id"], "1900")

    def test_export_json_feeds_pipeline_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "saft.json")
            self.assertEqual(self.store.export_json(out)["written"], out)
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(set(data), {"meta", "gl_accounts", "vat_codes", "suppliers",
                                         "supplier_account_mappings"})
            with self.assertRaises(StoreError):
                self.store.export_json(os.path.join(tmp, "saft.txt"))


class StdioServerTest(unittest.TestCase):
    """Full MCP round trip: spawn server.py over stdio and call tools."""

    def test_tools_over_stdio(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            self.skipTest("mcp SDK not installed")

        async def scenario():
            params = StdioServerParameters(
                command=sys.executable, args=[os.path.join(SERVER_DIR, "server.py")],
                env={**os.environ, "SAFT_FILE": ""})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    not_loaded = await session.call_tool("get_saft_summary", {})
                    loaded = await session.call_tool("load_saft_file", {"path": FIXTURE})
                    vat = await session.call_tool("find_vat_code", {"rate": 25})
                    hist = await session.call_tool("get_supplier_history", {"supplier_id": "50001"})
                    bad = await session.call_tool("get_account", {"account_id": "9999"})
                    return names, not_loaded, loaded, vat, hist, bad

        names, not_loaded, loaded, vat, hist, bad = asyncio.run(scenario())
        self.assertEqual(names, {"load_saft_file", "get_saft_summary", "list_accounts",
                                 "get_account", "list_vat_codes", "find_vat_code",
                                 "search_suppliers", "get_supplier_history", "export_saft_json"})
        self.assertTrue(not_loaded.isError)
        self.assertIn("No SAF-T file loaded", not_loaded.content[0].text)
        self.assertFalse(loaded.isError)
        self.assertEqual(json.loads(loaded.content[0].text)["company"]["name"], "Taxi Drift AS")
        self.assertEqual(json.loads(vat.content[0].text)["matches"][0]["code"], "1")
        self.assertEqual(json.loads(hist.content[0].text)["supplier"]["name"], "Circle K Norge AS")
        self.assertTrue(bad.isError)


if __name__ == "__main__":
    unittest.main()
