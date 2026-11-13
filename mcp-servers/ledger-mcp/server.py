#!/usr/bin/env python3
"""ledger-mcp: MCP server (stdio) that stores booked JR Taxi entries (bilag) in SQLite and
checks new documents/entries for duplicates.

Start: python mcp-servers/ledger-mcp/server.py
Database: LEDGER_DB (default <project>/data/ledger.sqlite).
"""

import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ledger_store import LedgerError, LedgerStore  # noqa: E402

mcp = FastMCP(
    "ledger-mcp",
    instructions=(
        "Store of booked bilag with duplicate detection. Entries are append-only: corrections "
        "are reversals. book_entry, book_qa_file and reverse_entry WRITE permanent accounting "
        "records: call them only after the user has explicitly approved that specific action, "
        "and pass the approving person's name as booked_by. Run check_duplicate before "
        "presenting a new bilag. Never set allow_possible_duplicate without the user's "
        "explicit confirmation and their reason."
    ),
)
_store = None


def store():
    global _store
    if _store is None:
        _store = LedgerStore()
    return _store


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LedgerError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def check_duplicate(bilag: dict) -> dict:
    """Check a bilag (entry-builder / qa-validator item) or loose fields {supplier_id?,
    vendor_name?, org_number?, invoice_number?, date?, amount?, source_file?} against booked
    entries. status: duplicate | possible_duplicate | unique, with matching bilag and reasons.
    Read-only."""
    return _call(store().check_duplicate, bilag)


@mcp.tool()
def book_entry(bilag: dict, booked_by: str, allow_possible_duplicate: bool = False,
               override_reason: str | None = None) -> dict:
    """WRITE: book one qa-validator-passed bilag permanently; assigns the next bilag number
    (YYYY-NNNNN). Refused if it duplicates a booked entry; a possible duplicate is refused
    unless allow_possible_duplicate=true with override_reason (user-confirmed). Only call
    after the user explicitly approved booking this bilag."""
    return _call(store().book, bilag, booked_by, allow_possible_duplicate, override_reason)


@mcp.tool()
def book_qa_file(path: str, booked_by: str) -> dict:
    """WRITE: book every passed bilag in a qa-validator JSON file (no duplicate overrides).
    Returns per-bilag booked/refused. Only call after the user approved booking the batch."""
    return _call(store().book_file, path, booked_by)


@mcp.tool()
def reverse_entry(bilag_no: str, reason: str, booked_by: str, date: str | None = None) -> dict:
    """WRITE: reverse a booked entry by booking a mirror entry (debet/kredit swapped), dated
    today unless date is given. The original is marked reversed. Only call after the user
    explicitly approved the reversal."""
    return _call(store().reverse, bilag_no, reason, booked_by, date)


@mcp.tool()
def get_entry(bilag_no: str) -> dict:
    """One booked entry with its lines (Konto, MK, Debet, Kredit, Løyve, Bil)."""
    return _call(store().get_entry, bilag_no)


@mcp.tool()
def list_entries(date_from: str | None = None, date_to: str | None = None,
                 supplier: str | None = None, status: str | None = None,
                 limit: int | None = None) -> dict:
    """Booked entries by date range, supplier (ID, org number or name) and status
    (booked | reversed | reversal). Default limit 200."""
    return _call(store().list_entries, date_from, date_to, supplier, status, limit)


@mcp.tool()
def get_audit_log(bilag_no: str | None = None, limit: int | None = None) -> list:
    """Append-only log of bookings, refusals, overrides and reversals (newest first)."""
    return _call(store().audit_log, bilag_no, limit)


@mcp.tool()
def get_ledger_summary() -> dict:
    """Database location, counts and totals per status, last bilag number per year."""
    return _call(store().summary)


def main():
    try:
        store()
    except (LedgerError, OSError) as exc:
        print(f"ledger-mcp: {exc}", file=sys.stderr)
        sys.exit(1)
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
