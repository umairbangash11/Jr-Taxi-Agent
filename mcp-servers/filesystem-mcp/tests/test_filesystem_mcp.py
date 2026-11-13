import asyncio
import datetime as dt
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(HERE, "..")
sys.path.insert(0, SERVER_DIR)

from fs_store import PROJECT_ROOT, FsError, FsStore  # noqa: E402

sys.path.insert(0, os.path.join(PROJECT_ROOT, ".claude", "skills", "document-reader", "tests"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "mcp-servers", "ledger-mcp"))
from test_read_document import make_pdf  # noqa: E402
from ledger_store import LedgerStore  # noqa: E402

CLIENT = "JR Taxi AS"


def tiny_png():
    raw = b"\x00\xff\x00\x00"
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def build_tree(root):
    def put(rel, data):
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path
    c = CLIENT
    invoice = make_pdf(["Verksted Service AS", "FAKTURA", "Fakturanr: 2025-0417",
                        "Fakturadato: 10.03.2025", "Å betale NOK 6 000,00"])
    put(f"{c}/Bank/kontoutskrift_2025-06.csv",
        "Dato;Forklaring;Uttak\n24.03.2025;Bensin Ørje;250,00\n".encode("cp1252"))
    put(f"{c}/Bank/camt_2025-07.xml", b"<Document/>")
    put(f"{c}/Bokført/2025/verksted_0417.pdf", invoice)
    put(f"{c}/Innboks/skannet_kopi.pdf", invoice)               # same bytes, renamed
    put(f"{c}/Innboks/kvittering.png", tiny_png())
    put(f"{c}/Innboks/ny_faktura.pdf", make_pdf(["Ny leverandør AS", "FAKTURA"]))
    ledgered = put(f"{c}/Innboks/allerede_i_ledger.pdf", make_pdf(["Booked AS", "Kvittering"]))
    put(f"{c}/Innboks/.hidden.pdf", b"x")
    put(f"{c}/SAF-T/saft_2024.xml", b"<AuditFile/>")
    saft25 = put(f"{c}/SAF-T/saft_2025.xml", b"<AuditFile/>")
    os.utime(saft25, (2_000_000_000, 2_000_000_000))
    put(f"{c}/Diverse/notat.txt", "Møte med revisor".encode("utf-8"))
    put("Annen Klient/Bank/hemmelig.csv", b"Dato;Belop\n")
    return ledgered


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "Klienter")
        self.ledgered = build_tree(self.root)
        self.db = os.path.join(self.tmp, "ledger.sqlite")
        self.store = FsStore(self.root, ledger_db=self.db)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ListingTest(Base):
    def test_clients_and_roles(self):
        r = self.store.list_clients()
        self.assertFalse(r["single_client"])
        jr = next(c for c in r["clients"] if c["client"] == CLIENT)
        self.assertEqual(jr["roles"], {"bank": "Bank", "booked": "Bokført",
                                       "inbox": "Innboks", "saft": "SAF-T"})
        self.assertEqual([c["client"] for c in r["clients"]], ["Annen Klient", CLIENT])

    def test_client_lookup_case_insensitive_and_folders(self):
        folders = {f["folder"]: f for f in self.store.list_folders("jr taxi as")["folders"]}
        self.assertEqual(folders["Innboks"]["files"], 4)      # hidden file skipped
        self.assertIsNone(folders["Diverse"]["role"])
        with self.assertRaises(FsError):
            self.store.list_folders("Ukjent")

    def test_list_files_filters(self):
        r = self.store.list_files(CLIENT, "Bank", pattern="*.csv")
        self.assertEqual([i["path"] for i in r["items"]], ["Bank/kontoutskrift_2025-06.csv"])
        self.assertEqual(r["items"][0]["role"], "bank")
        self.assertTrue(os.path.isabs(r["items"][0]["absolute_path"]))
        self.assertEqual(self.store.list_files(CLIENT, "Bokført", recursive=False)["total"], 0)
        later = self.store.list_files(CLIENT, modified_after="2030-01-01")
        self.assertEqual([i["name"] for i in later["items"]], ["saft_2025.xml"])
        self.assertTrue(self.store.list_files(CLIENT, limit=2)["truncated"])

    def test_find_files_across_clients(self):
        r = self.store.find_files("kontoutskrift")
        self.assertEqual(r["items"][0]["client"], CLIENT)
        self.assertEqual(self.store.find_files("bank", ext=".csv")["total"], 2)
        self.assertEqual(self.store.find_files("bank", client=CLIENT, ext=".csv")["total"], 1)

    def test_single_client_root(self):
        single = FsStore(os.path.join(self.root, CLIENT), ledger_db=self.db)
        self.assertTrue(single.list_clients()["single_client"])
        self.assertEqual(single.list_files(None, "Bank")["total"], 2)


class ReadTest(Base):
    def test_text_with_cp1252(self):
        info, img = self.store.read_file(CLIENT, "Bank/kontoutskrift_2025-06.csv")
        self.assertIsNone(img)
        self.assertEqual(info["encoding"], "cp1252")
        self.assertIn("Bensin Ørje", info["text"])

    def test_pdf_text(self):
        info, _ = self.store.read_file(CLIENT, "Innboks/ny_faktura.pdf")
        if not info["extraction"]["method"]:
            self.skipTest("no PDF text backend")
        self.assertIn("Ny leverandør AS", info["text"])

    def test_image(self):
        info, img = self.store.read_file(CLIENT, "Innboks/kvittering.png")
        self.assertEqual(info["kind"], "image")
        self.assertTrue(img.startswith(b"\x89PNG"))

    def test_path_safety(self):
        for bad in ("../Annen Klient/Bank/hemmelig.csv", "..\\Annen Klient\\Bank\\hemmelig.csv",
                    os.path.join(self.root, "Annen Klient", "Bank", "hemmelig.csv"),
                    "Bank/../../Annen Klient/Bank/hemmelig.csv"):
            with self.assertRaises(FsError, msg=bad):
                self.store.read_file(CLIENT, bad)
        with self.assertRaises(FsError):
            self.store.list_files(CLIENT, pattern="../*")
        with self.assertRaises(FsError):
            self.store.read_file(CLIENT, "Innboks/finnes_ikke.pdf")

    def test_symlink_escape_refused(self):
        outside = os.path.join(self.tmp, "outside.txt")
        with open(outside, "w") as fh:
            fh.write("secret")
        link = os.path.join(self.root, CLIENT, "Innboks", "lenke.txt")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not permitted on this system")
        with self.assertRaises(FsError):
            self.store.read_file(CLIENT, "Innboks/lenke.txt")
        names = [i["name"] for i in self.store.list_files(CLIENT, "Innboks")["items"]]
        self.assertNotIn("lenke.txt", names)

    def test_unsupported_type(self):
        path = os.path.join(self.root, CLIENT, "Diverse", "program.exe")
        with open(path, "wb") as fh:
            fh.write(b"MZ")
        with self.assertRaises(FsError):
            self.store.read_file(CLIENT, "Diverse/program.exe")


class PipelineTest(Base):
    def test_find_unbooked_folder_and_ledger(self):
        ledger = LedgerStore(self.db, today=dt.date(2026, 11, 12))
        ledger.book({"source_file": self.ledgered, "qa_status": "passed",
                     "header": {"date": "2025-06-01", "total_amount": 10, "currency": "NOK"},
                     "lines": [{"konto": "7000", "mk": "1", "debet": 10},
                               {"konto": "1920", "kredit": 10}]}, "Ola")
        ledger.close()
        r = self.store.find_unbooked(CLIENT)
        self.assertTrue(r["ledger_checked"])
        self.assertEqual(sorted(i["name"] for i in r["unbooked"]),
                         ["kvittering.png", "ny_faktura.pdf"])
        already = {i["name"]: i["already_booked"][0] for i in r["already_booked"]}
        self.assertIn("Bokført/2025/verksted_0417.pdf", already["skannet_kopi.pdf"])
        self.assertIn("booked in ledger as 2025-00001", already["allerede_i_ledger.pdf"])

    def test_find_unbooked_without_ledger(self):
        r = self.store.find_unbooked(CLIENT)
        self.assertFalse(r["ledger_checked"])
        self.assertEqual(len(r["unbooked"]), 3)
        with self.assertRaises(FsError):
            self.store.find_unbooked("Annen Klient")           # no inbox folder

    def test_locate_inputs(self):
        r = self.store.locate_inputs(CLIENT)
        self.assertTrue(r["saft_file"].endswith("saft_2025.xml"))
        self.assertEqual(len(r["bank_statements"]), 2)
        self.assertEqual(r["inbox_folders"], ["Innboks"])

    def test_missing_root(self):
        with self.assertRaises(FsError):
            FsStore(os.path.join(self.tmp, "nope"))


class StdioServerTest(Base):
    def test_tools_over_stdio(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            self.skipTest("mcp SDK not installed")

        async def scenario():
            params = StdioServerParameters(
                command=sys.executable, args=[os.path.join(SERVER_DIR, "server.py")],
                env={**os.environ, "CLIENTS_ROOT": self.root, "LEDGER_DB": self.db})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    clients = await session.call_tool("list_clients", {})
                    image = await session.call_tool("read_file", {
                        "client": CLIENT, "path": "Innboks/kvittering.png"})
                    escape = await session.call_tool("read_file", {
                        "client": CLIENT, "path": "../Annen Klient/Bank/hemmelig.csv"})
                    return names, clients, image, escape

        names, clients, image, escape = asyncio.run(scenario())
        self.assertEqual(names, {"list_clients", "list_folders", "list_files", "find_files",
                                 "read_file", "find_unbooked", "locate_inputs"})
        self.assertEqual(len(json.loads(clients.content[0].text)["clients"]), 2)
        kinds = [c.type for c in image.content]
        self.assertEqual(kinds, ["text", "image"])
        self.assertEqual(image.content[1].mimeType, "image/png")
        self.assertTrue(escape.isError)


if __name__ == "__main__":
    unittest.main()
