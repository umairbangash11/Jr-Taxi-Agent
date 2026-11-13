import asyncio
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(HERE, "..")
sys.path.insert(0, SERVER_DIR)

from doc_store import PROJECT_ROOT, DocError, DocStore  # noqa: E402

READER_TESTS = os.path.join(PROJECT_ROOT, ".claude", "skills", "document-reader", "tests")
sys.path.insert(0, READER_TESTS)
from test_read_document import make_pdf  # noqa: E402  (minimal text-layer PDF builder)


def fixture_text(name):
    with open(os.path.join(READER_TESTS, "fixtures", name), encoding="utf-8") as fh:
        return fh.read()


class DocStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.receipt = self._pdf("kvittering.pdf", fixture_text("kvittering.txt"))
        self.scan = self._pdf("scan.pdf", "")
        self.store = DocStore(roots=[])

    def _pdf(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(make_pdf(text.splitlines()))
        return path

    def _need_pdf_backend(self):
        if not DocStore.backends()["can_read_text_pdfs"]:
            self.skipTest("no PDF text backend installed")

    def test_read_receipt_summary(self):
        self._need_pdf_backend()
        doc = self.store.read(self.receipt, allow_ocr=False)
        self.assertEqual(doc["status"], "ok")
        self.assertEqual(doc["summary"]["supplier"], "OSLO TAXI SENTRAL AS")
        self.assertEqual(doc["summary"]["amount"], 845)
        self.assertEqual(doc["summary"]["vat_rate"], 12)
        self.assertEqual(doc["summary"]["type"], "kvittering")
        self.assertEqual(doc["summary"]["date"], "2025-06-14")
        self.assertNotIn("text", doc)
        self.assertIn("text", self.store.read(self.receipt, include_text=True, allow_ocr=False))

    def test_cache_and_invalidation(self):
        self._need_pdf_backend()
        first = self.store.read(self.receipt, allow_ocr=False)
        self.assertEqual(len(self.store._cache), 1)
        self.store.read(self.receipt, allow_ocr=False)
        self.assertEqual(len(self.store._cache), 1)
        with open(self.receipt, "wb") as fh:
            fh.write(make_pdf(fixture_text("faktura.txt").splitlines()))
        os.utime(self.receipt, ns=(1, 1))
        second = self.store.read(self.receipt, allow_ocr=False)
        self.assertNotEqual(first["summary"]["type"], second["summary"]["type"])

    def test_scan_needs_ocr(self):
        doc = self.store.read(self.scan, allow_ocr=False)
        self.assertEqual(doc["status"], "needs_ocr")
        self.assertNotIn("summary", doc)

    def test_unclear_fields_not_in_summary(self):
        doc = self.store.from_text(fixture_text("uklar.txt"), "uklar.jpg")
        s = doc["summary"]
        self.assertIsNone(s["amount"])
        self.assertIsNone(s["vat_rate"])
        self.assertIn("amount", s["unclear_fields"])
        self.assertIn("type", s["missing_fields"])
        self.assertEqual(doc["extraction"]["method"], "transcription")

    def test_from_text_rejects_empty(self):
        with self.assertRaises(DocError):
            self.store.from_text("  ")

    def test_path_validation(self):
        with self.assertRaises(DocError):
            self.store.read(os.path.join(self.tmp, "missing.pdf"))
        txt = os.path.join(self.tmp, "notes.txt")
        with open(txt, "w") as fh:
            fh.write("x")
        with self.assertRaises(DocError) as ctx:
            self.store.read(txt)
        self.assertIn("Unsupported", str(ctx.exception))

    def test_document_roots_sandbox(self):
        inside = DocStore(roots=[self.tmp])
        inside.read(self.scan, allow_ocr=False)  # allowed
        other = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, other)
        with self.assertRaises(DocError) as ctx:
            DocStore(roots=[other]).read(self.scan, allow_ocr=False)
        self.assertIn("outside", str(ctx.exception))

    def test_batch_and_folder(self):
        batch = self.store.read_many([self.scan, os.path.join(self.tmp, "nope.pdf")],
                                     allow_ocr=False)
        self.assertEqual(batch["status_counts"], {"needs_ocr": 1, "error": 1})
        self.assertEqual(len(batch["needs_review"]), 2)
        folder = self.store.read_folder(self.tmp, allow_ocr=False)
        self.assertEqual(folder["files_found"], 2)
        self.assertFalse(folder["truncated"])
        with self.assertRaises(DocError):
            self.store.read_folder(self.tmp, pattern="../*.pdf")
        self.assertIn("No matching", self.store.read_folder(self.tmp, pattern="*.png")["note"])

    def test_backends_report(self):
        b = DocStore.backends()
        self.assertIn("can_ocr_scans", b)
        self.assertIn(".pdf", b["allowed_extensions"])


class StdioServerTest(unittest.TestCase):
    def test_tools_over_stdio(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            self.skipTest("mcp SDK not installed")
        tmp = tempfile.mkdtemp()
        scan = os.path.join(tmp, "scan.pdf")
        with open(scan, "wb") as fh:
            fh.write(make_pdf([]))

        async def scenario():
            params = StdioServerParameters(
                command=sys.executable, args=[os.path.join(SERVER_DIR, "server.py")],
                env={**os.environ, "DOCUMENT_ROOTS": tmp})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    scan_r = await session.call_tool("read_document",
                                                     {"path": scan, "allow_ocr": False})
                    text_r = await session.call_tool(
                        "extract_from_text",
                        {"text": fixture_text("faktura.txt"), "source_name": "f.jpg"})
                    outside = await session.call_tool("read_document",
                                                      {"path": os.path.abspath(__file__)})
                    return names, scan_r, text_r, outside

        try:
            names, scan_r, text_r, outside = asyncio.run(scenario())
        finally:
            os.remove(scan)
            os.rmdir(tmp)
        self.assertEqual(names, {"read_document", "read_documents", "read_folder",
                                 "extract_from_text", "get_extraction_backends"})
        self.assertEqual(json.loads(scan_r.content[0].text)["status"], "needs_ocr")
        summary = json.loads(text_r.content[0].text)["summary"]
        self.assertEqual((summary["supplier"], summary["amount"], summary["type"]),
                         ("Verksted Service AS", 6000, "faktura"))
        self.assertTrue(outside.isError)
        self.assertIn("outside", outside.content[0].text)


if __name__ == "__main__":
    unittest.main()
