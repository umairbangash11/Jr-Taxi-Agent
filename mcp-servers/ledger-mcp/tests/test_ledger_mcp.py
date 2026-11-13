import asyncio
import copy
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(HERE, "..")
sys.path.insert(0, SERVER_DIR)

from ledger_store import LedgerError, LedgerStore, invoice_key  # noqa: E402

TODAY = dt.date(2026, 11, 12)


def bilag(source="verksted.pdf", date="2025-03-10", inv="2025-0417", amount=6000.0,
          supplier="50010", vendor="Verksted Service AS", qa="passed", **header):
    return {
        "source_file": source, "status": "ready", "qa_status": qa,
        "header": {"date": date, "document_type": "faktura", "vendor_name": vendor,
                   "supplier_id": supplier, "invoice_number": inv, "total_amount": amount,
                   "currency": "NOK", **header},
        "lines": [
            {"konto": "6600", "mk": "1", "debet": amount, "kredit": None,
             "loyve": "L-101", "bil": "EL12345", "tekst": "Service", "supplier_id": None},
            {"konto": "2400", "mk": None, "debet": None, "kredit": amount,
             "loyve": None, "bil": None, "tekst": "Service", "supplier_id": supplier},
        ],
    }


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "ledger.sqlite")
        self.store = LedgerStore(self.db, today=TODAY)

    def tearDown(self):
        self.store.close()
        __import__("shutil").rmtree(self.tmp, ignore_errors=True)


class BookingTest(Base):
    def test_book_assigns_gapless_numbers_per_year(self):
        r1 = self.store.book(bilag(), "Ola")
        r2 = self.store.book(bilag("b.pdf", inv="2", amount=100, date="2025-04-01"), "Ola")
        r3 = self.store.book(bilag("c.pdf", inv="3", amount=200, date="2026-01-02"), "Ola")
        self.assertEqual([r1["bilag_no"], r2["bilag_no"], r3["bilag_no"]],
                         ["2025-00001", "2025-00002", "2026-00001"])
        e = self.store.get_entry("2025-00001")
        self.assertEqual((e["total_amount"], e["status"], e["booked_by"]), (6000.0, "booked", "Ola"))
        self.assertEqual([ln["konto"] for ln in e["lines"]], ["6600", "2400"])

    def test_requires_qa_passed_and_booked_by(self):
        with self.assertRaises(LedgerError) as ctx:
            self.store.book(bilag(qa=None), "Ola")
        self.assertIn("qa-validator", str(ctx.exception))
        with self.assertRaises(LedgerError):
            self.store.book(bilag(qa="blocked"), "Ola")
        with self.assertRaises(LedgerError):
            self.store.book(bilag(), "  ")

    def test_validation(self):
        b = bilag()
        b["lines"][1]["kredit"] = 5999.99
        with self.assertRaises(LedgerError) as ctx:
            self.store.book(b, "Ola")
        self.assertIn("Unbalanced", str(ctx.exception))
        with self.assertRaises(LedgerError):
            self.store.book(bilag(date="2027-01-01"), "Ola")      # future
        with self.assertRaises(LedgerError):
            self.store.book(bilag(currency="EUR"), "Ola")
        b = bilag()
        b["lines"][0]["debet"] = 6000.001
        with self.assertRaises(LedgerError):
            self.store.book(b, "Ola")                              # sub-øre
        self.assertEqual(self.store.summary()["by_status"], {})   # nothing written


class DuplicateTest(Base):
    def setUp(self):
        super().setUp()
        self.store.book(bilag(), "Ola")

    def test_same_supplier_and_invoice_number_refused(self):
        r = self.store.book(bilag("kopi.pdf", inv="2025-417", amount=6000.0), "Ola")
        self.assertFalse(r["booked"])
        self.assertEqual(r["duplicate_check"]["status"], "duplicate")
        self.assertIn("same supplier and invoice number (2025-0417)",
                      r["duplicate_check"]["matches"][0]["reasons"])

    def test_invoice_key_normalisation(self):
        self.assertEqual(invoice_key("INV-000417"), invoice_key("inv 417"))
        self.assertEqual(invoice_key("2025-0417"), invoice_key("2025-417"))
        self.assertEqual(invoice_key("INV000417"), invoice_key("INV-417"))
        self.assertNotEqual(invoice_key("1001"), invoice_key("101"))

    def test_same_invoice_number_other_supplier_is_fine(self):
        r = self.store.book(bilag("other.pdf", supplier="50099", vendor="Annen AS",
                                  amount=10), "Ola")
        self.assertTrue(r["booked"])

    def test_same_source_file_hash_refused(self):
        src = os.path.join(self.tmp, "faktura.pdf")
        with open(src, "wb") as fh:
            fh.write(b"%PDF-1.4 same bytes")
        self.store.book(bilag(src, inv="900", amount=50), "Ola")
        renamed = os.path.join(self.tmp, "faktura (1).pdf")
        with open(renamed, "wb") as fh:
            fh.write(b"%PDF-1.4 same bytes")
        r = self.store.check_duplicate(bilag(renamed, inv=None, amount=77, supplier=None,
                                             vendor=None))
        self.assertEqual(r["status"], "duplicate")
        self.assertIn("same source document", r["matches"][0]["reasons"][0])

    def test_possible_duplicate_needs_override(self):
        later = bilag("ny.pdf", inv=None, date="2025-03-14")       # same supplier+amount, 4 days
        r = self.store.book(later, "Ola")
        self.assertFalse(r["booked"])
        self.assertEqual(r["duplicate_check"]["status"], "possible_duplicate")
        r = self.store.book(later, "Ola", allow_possible_duplicate=True)
        self.assertFalse(r["booked"])
        self.assertIn("override_reason", r["reason"])
        r = self.store.book(later, "Ola", allow_possible_duplicate=True,
                            override_reason="Two separate services, confirmed with supplier")
        self.assertTrue(r["booked"])
        self.assertIn("confirmed with supplier", self.store.get_entry(r["bilag_no"])["note"])
        actions = [a["action"] for a in self.store.audit_log()]
        self.assertEqual(actions, ["book", "refused", "refused", "book"])

    def test_different_invoice_numbers_same_supplier_not_flagged_unless_same_day(self):
        r = self.store.check_duplicate(bilag("x.pdf", inv="2025-0500", date="2025-03-12"))
        self.assertEqual(r["status"], "unique")
        r = self.store.check_duplicate(bilag("x.pdf", inv="2025-0500"))  # identical lines too
        self.assertEqual(r["status"], "possible_duplicate")
        self.assertIn("different invoice number", r["matches"][0]["reasons"][0])

    def test_loose_fields_check(self):
        r = self.store.check_duplicate({"vendor": "Verksted Service", "amount": "6 000,00",
                                        "date": "2025-03-10"})
        self.assertEqual(r["status"], "possible_duplicate")
        r = self.store.check_duplicate({"amount": 6000, "date": "2025-03-10"})
        self.assertEqual(r["status"], "possible_duplicate")       # supplier unknown
        r = self.store.check_duplicate({"supplier_id": "50099", "amount": 6000,
                                        "date": "2025-03-10"})
        self.assertEqual(r["status"], "unique")                   # different supplier
        with self.assertRaises(LedgerError):
            self.store.check_duplicate({"vendor": "x"})

    def test_identical_entry_refused(self):
        # Same date and lines, other file, no supplier/invoice info to tell them apart.
        b = bilag("annen-fil.pdf", inv=None, supplier=None, vendor=None)
        r = self.store.book(b, "Ola")
        self.assertEqual(r["duplicate_check"]["status"], "duplicate")
        self.assertIn("identical date and lines", r["duplicate_check"]["matches"][0]["reasons"])


class ReversalTest(Base):
    def test_reverse_and_rebook(self):
        self.store.book(bilag(), "Ola")
        r = self.store.reverse("2025-00001", "Wrong account", "Kari")
        # Dated today (2026), so it takes the next number in the 2026 series.
        self.assertEqual(r["reversal_bilag_no"], "2026-00001")
        rev = r["entry"]
        self.assertEqual((rev["status"], rev["reversal_of"], rev["date"]),
                         ("reversal", "2025-00001", "2026-11-12"))
        self.assertEqual([(ln["debet"], ln["kredit"]) for ln in rev["lines"]],
                         [(None, 6000.0), (6000.0, None)])
        orig = self.store.get_entry("2025-00001")
        self.assertEqual((orig["status"], orig["reversed_by"]), ("reversed", "2026-00001"))
        same_day = self.store.book(bilag("z.pdf", inv="9", amount=10), "Ola")
        self.assertEqual(self.store.reverse(same_day["bilag_no"], "x", "Kari",
                                            date="2025-03-10")["reversal_bilag_no"],
                         "2025-00003")
        with self.assertRaises(LedgerError):
            self.store.reverse("2025-00001", "again", "Kari")
        with self.assertRaises(LedgerError):
            self.store.reverse("2026-00001", "reverse the reversal", "Kari")
        # Corrected entry can be booked again: reversed original is info only.
        b = bilag()
        b["lines"][0]["konto"] = "6620"
        res = self.store.book(b, "Ola")
        self.assertTrue(res["booked"], res)
        self.assertEqual(res["duplicate_check"]["previously_reversed"][0]["bilag_no"],
                         "2025-00001")

    def test_reverse_validation(self):
        self.store.book(bilag(), "Ola")
        with self.assertRaises(LedgerError):
            self.store.reverse("2025-00001", "", "Kari")
        with self.assertRaises(LedgerError):
            self.store.reverse("2025-00001", "x", "Kari", date="2025-01-01")
        with self.assertRaises(LedgerError):
            self.store.reverse("2099-00001", "x", "Kari")


class ImmutabilityTest(Base):
    def test_database_refuses_edits_and_deletes(self):
        self.store.book(bilag(), "Ola")
        raw = sqlite3.connect(self.db)
        for sql in ("DELETE FROM entries", "UPDATE entries SET total_cents = 1",
                    "UPDATE entries SET status = 'reversal'", "DELETE FROM lines",
                    "UPDATE lines SET konto = '9999'", "DELETE FROM audit_log",
                    "UPDATE audit_log SET actor = 'x'"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                raw.execute(sql)
        raw.close()

    def test_persistence_across_restart(self):
        self.store.book(bilag(), "Ola")
        self.store.close()
        self.store = LedgerStore(self.db, today=TODAY)
        self.assertEqual(self.store.check_duplicate(bilag("k.pdf"))["status"], "duplicate")
        self.assertEqual(self.store.summary()["by_year"][0]["last_bilag_no"], "2025-00001")


class ListingTest(Base):
    def test_list_file_booking_and_summary(self):
        qa = {"bilag": [bilag(), bilag("b.pdf", inv="2", amount=50, date="2025-05-01"),
                        bilag("c.pdf", qa="blocked"), bilag("d.pdf")]}
        path = os.path.join(self.tmp, "qa.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(qa, fh)
        r = self.store.book_file(path, "Ola")
        self.assertEqual((r["booked"], r["refused"]), (2, 2))
        self.assertEqual(r["results"][3]["duplicate_check"]["status"], "duplicate")
        self.assertEqual(self.store.list_entries(date_from="2025-04-01")["total"], 1)
        self.assertEqual(self.store.list_entries(supplier="Verksted")["total"], 2)
        self.assertEqual(self.store.list_entries(status="reversed")["total"], 0)
        s = self.store.summary()
        self.assertEqual(s["by_status"]["booked"], {"count": 2, "amount": 6050.0})
        with self.assertRaises(LedgerError):
            self.store.list_entries(status="deleted")


class StdioServerTest(unittest.TestCase):
    def test_tools_over_stdio(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            self.skipTest("mcp SDK not installed")
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "l.sqlite")
        b = bilag(date="2025-03-10")

        async def scenario():
            params = StdioServerParameters(
                command=sys.executable, args=[os.path.join(SERVER_DIR, "server.py")],
                env={**os.environ, "LEDGER_DB": db})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    first = await session.call_tool("book_entry", {"bilag": b, "booked_by": "Ola"})
                    again = await session.call_tool("book_entry",
                                                    {"bilag": copy.deepcopy(b), "booked_by": "Ola"})
                    check = await session.call_tool("check_duplicate", {"bilag": {
                        "supplier_id": "50010", "invoice_number": "2025-0417"}})
                    bad = await session.call_tool("book_entry",
                                                  {"bilag": {**b, "qa_status": "blocked"},
                                                   "booked_by": "Ola"})
                    return names, first, again, check, bad

        try:
            names, first, again, check, bad = asyncio.run(scenario())
        finally:
            __import__("shutil").rmtree(tmp, ignore_errors=True)
        self.assertEqual(names, {"check_duplicate", "book_entry", "book_qa_file", "reverse_entry",
                                 "get_entry", "list_entries", "get_audit_log",
                                 "get_ledger_summary"})
        self.assertEqual(json.loads(first.content[0].text)["bilag_no"], "2025-00001")
        self.assertFalse(json.loads(again.content[0].text)["booked"])
        self.assertEqual(json.loads(check.content[0].text)["status"], "duplicate")
        self.assertTrue(bad.isError)


if __name__ == "__main__":
    unittest.main()
