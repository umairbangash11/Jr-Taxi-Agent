#!/usr/bin/env python3
"""bank-mcp: MCP server (stdio) that reads bank statements (Norwegian netbank CSV or
CAMT.053 XML) and matches transactions to documents by amount, date and vendor.

Start: python mcp-servers/bank-mcp/server.py [statement.csv|.xml]
Optional: BANK_FILE preloads a statement; BANK_ROOTS=dir1;dir2 restricts readable paths.
"""

import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bank_store import BankError, BankStore  # noqa: E402

mcp = FastMCP(
    "bank-mcp",
    instructions=(
        "Read-only access to a bank statement and matching of documents to outgoing payments. "
        "Load a statement first (load_bank_statement). Statuses: paid | uncertain | not_found "
        "| unmatchable. Never report an 'uncertain' match as paid: show its reasons and "
        "candidates and ask the user. List unmatched outgoing lines as possible missing bilag."
    ),
)
store = BankStore()


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except BankError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def load_bank_statement(path: str, date_col: str | None = None,
                        text_cols: list[str] | None = None, amount_col: str | None = None,
                        out_col: str | None = None, in_col: str | None = None) -> dict:
    """Load a bank statement: netbank CSV (columns auto-detected; override with *_col
    arguments using the CSV header names) or CAMT.053/054 XML. Returns line counts,
    totals, date range and parse warnings."""
    return _call(store.load, path, date_col, text_cols, amount_col, out_col, in_col)


@mcp.tool()
def get_statement_summary() -> dict:
    """Summary of the loaded statement (lines, outgoing/incoming, totals, date range)."""
    return _call(store.summary)


@mcp.tool()
def list_transactions(direction: str = "all", date_from: str | None = None,
                      date_to: str | None = None, query: str | None = None,
                      min_amount: float | None = None, max_amount: float | None = None,
                      limit: int | None = None) -> dict:
    """Bank lines filtered by direction (all | outgoing | incoming), date range, text and
    absolute amount range. Outgoing amounts are negative. Default limit 200."""
    return _call(store.list_transactions, direction, date_from, date_to, query,
                 min_amount, max_amount, limit)


@mcp.tool()
def find_payment(amount: float, date: str | None = None, vendor: str | None = None,
                 invoice_number: str | None = None, org_number: str | None = None,
                 document_type: str | None = None, tolerance: float = 0) -> dict:
    """Quick lookup: outgoing bank lines that could pay ONE document, best first, with
    vendor_signal (reference | strong | weak | none) and days after the document date.
    document_type faktura (60-day window) or kvittering (7-day window). Candidates only."""
    return _call(store.find_payment, amount, date, vendor, invoice_number, org_number,
                 document_type, tolerance=tolerance)


@mcp.tool()
def match_documents(documents: list[dict], receipt_days: int = 7, invoice_days: int = 60,
                    early_days: int = 3, tolerance: float = 0) -> dict:
    """Match documents to outgoing bank lines one-to-one and return paid / uncertain /
    not_found / unmatchable per document plus unmatched outgoing lines.
    Each document: {id, vendor|supplier, date, amount, invoice_number?, org_number?,
    type: faktura|kvittering, currency?} — document-mcp 'summary' objects work as-is
    (add id). Max 500."""
    return _call(store.match_documents, documents, receipt_days=receipt_days,
                 invoice_days=invoice_days, early_days=early_days, tolerance=tolerance)


@mcp.tool()
def match_documents_file(json_path: str, receipt_days: int = 7, invoice_days: int = 60,
                         early_days: int = 3, tolerance: float = 0) -> dict:
    """Same as match_documents, reading document-reader or entry-builder JSON from a file."""
    return _call(store.match_documents_file, json_path, receipt_days=receipt_days,
                 invoice_days=invoice_days, early_days=early_days, tolerance=tolerance)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("BANK_FILE")
    if path:
        try:
            store.load(path)
        except BankError as exc:
            print(f"bank-mcp: {exc}", file=sys.stderr)
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
