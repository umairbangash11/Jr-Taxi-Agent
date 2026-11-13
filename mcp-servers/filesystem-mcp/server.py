#!/usr/bin/env python3
"""filesystem-mcp: read-only MCP server (stdio) for the client folders (Bank, Bokført,
Innboks, SAF-T, ...) under CLIENTS_ROOT.

Start: CLIENTS_ROOT=D:\\Klienter python mcp-servers/filesystem-mcp/server.py
Optional: LEDGER_DB (default <project>/data/ledger.sqlite) for find_unbooked.
"""

import os
import sys

from mcp.server.fastmcp import FastMCP, Image
from mcp.server.fastmcp.exceptions import ToolError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fs_store import FsError, FsStore  # noqa: E402

mcp = FastMCP(
    "filesystem-mcp",
    instructions=(
        "Read-only access to accounting client folders under CLIENTS_ROOT. Start with "
        "list_clients. Paths are relative to the client folder. Use find_unbooked to see which "
        "inbox documents are not booked yet, and locate_inputs to get the SAF-T and bank files "
        "for the saft/bank/reconcile servers. This server never writes or moves files."
    ),
)
_store = None


def store():
    global _store
    if _store is None:
        _store = FsStore()
    return _store


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FsError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def list_clients() -> dict:
    """Client folders under CLIENTS_ROOT with their subfolders and recognised roles
    (bank, booked, inbox, saft)."""
    return _call(lambda: store().list_clients())


@mcp.tool()
def list_folders(client: str) -> dict:
    """A client's folders with role and file count."""
    return _call(lambda: store().list_folders(client))


@mcp.tool()
def list_files(client: str, folder: str | None = None, pattern: str = "*",
               recursive: bool = True, modified_after: str | None = None,
               limit: int | None = None) -> dict:
    """Files in a client folder (e.g. folder="Bank", pattern="*.csv"), with size, modified
    time, role and absolute_path (for document-mcp / bank-mcp). Default limit 500."""
    return _call(lambda: store().list_files(client, folder, pattern, recursive,
                                            modified_after, limit))


@mcp.tool()
def find_files(query: str, client: str | None = None, ext: str | None = None,
               limit: int | None = None) -> dict:
    """Search file names (and folder names) for text, in one client or all clients."""
    return _call(lambda: store().find_files(query, client, ext, limit))


@mcp.tool()
def read_file(client: str, path: str, max_chars: int = 100_000, allow_ocr: bool = False):
    """Read a document: text files (csv, xml, json, txt) as text; PDFs as extracted text
    (use document-mcp for invoice fields); images returned as image content to view.
    path is relative to the client folder, e.g. "Innboks/faktura.pdf"."""
    info, image = _call(lambda: store().read_file(client, path, max_chars, allow_ocr))
    if image is None:
        return info
    fmt = info["ext"].lstrip(".").replace("jpg", "jpeg")
    return [info, Image(data=image, format=fmt)]


@mcp.tool()
def find_unbooked(client: str) -> dict:
    """Inbox documents not yet booked: compared by file content (sha256) against the
    booked folder (Bokført) and against ledger-mcp's database. Read-only."""
    return _call(lambda: store().find_unbooked(client))


@mcp.tool()
def locate_inputs(client: str) -> dict:
    """Absolute paths of the client's newest SAF-T file and bank statements, ready for
    saft-mcp / bank-mcp / reconcile-mcp."""
    return _call(lambda: store().locate_inputs(client))


def main():
    try:
        store()
    except FsError as exc:
        # Keep serving: every tool call will report the configuration problem.
        print(f"filesystem-mcp: {exc}", file=sys.stderr)
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
