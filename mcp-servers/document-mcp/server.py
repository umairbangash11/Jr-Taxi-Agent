#!/usr/bin/env python3
"""document-mcp: MCP server (stdio) that reads invoice/receipt PDFs and images and extracts
supplier, org number, date, amount, VAT rate, invoice number and type (faktura/kvittering).

Start: python mcp-servers/document-mcp/server.py
Optional: DOCUMENT_ROOTS=dir1;dir2 restricts readable paths (os.pathsep-separated).
"""

import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from doc_store import DocError, DocStore  # noqa: E402

mcp = FastMCP(
    "document-mcp",
    instructions=(
        "Extracts bookkeeping fields from invoice (faktura) and receipt (kvittering) PDFs/images. "
        "Each field has status ok | unclear | missing; 'summary' contains only confirmed values. "
        "Never fill an unclear or missing field yourself: show the candidates and ask the user. "
        "If a document comes back with status needs_ocr (scan, no OCR installed), view the file "
        "yourself, transcribe it verbatim and call extract_from_text."
    ),
)
store = DocStore()


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DocError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def read_document(path: str, include_text: bool = False, allow_ocr: bool = True,
                  max_pages: int = 10) -> dict:
    """Extract supplier, org number, date, total amount, VAT rate, invoice number and type
    from one PDF or image. Returns 'summary' (confirmed values only), per-field details with
    status/confidence/evidence/candidates, and flags. include_text adds the raw text."""
    return _call(store.read, path, include_text, allow_ocr, max_pages)


@mcp.tool()
def read_documents(paths: list[str], include_text: bool = False,
                   allow_ocr: bool = True) -> dict:
    """Extract fields from several files (max 100). Per-file errors don't fail the batch."""
    return _call(store.read_many, paths, include_text, allow_ocr)


@mcp.tool()
def read_folder(folder: str, pattern: str = "*.pdf", recursive: bool = False,
                allow_ocr: bool = True) -> dict:
    """Extract fields from every matching document in a folder (max 100, sorted by name).
    pattern is a file-name glob such as '*.pdf' or '*.jpg'."""
    return _call(store.read_folder, folder, pattern, recursive, allow_ocr)


@mcp.tool()
def extract_from_text(text: str, source_name: str | None = None) -> dict:
    """Apply the same field rules to text you transcribed from a scanned document
    (vision fallback when read_document returns needs_ocr). Transcribe verbatim, line by
    line, keeping labels next to values."""
    return _call(store.from_text, text, source_name)


@mcp.tool()
def get_extraction_backends() -> dict:
    """Which PDF-text and OCR backends are installed, i.e. whether scans can be read."""
    return store.backends()


def main():
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
