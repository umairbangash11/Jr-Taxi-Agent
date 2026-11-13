#!/usr/bin/env python3
"""saft-mcp: MCP server (stdio) serving a Norwegian SAF-T file's chart of accounts,
VAT codes and supplier→account history.

Start:  python mcp-servers/saft-mcp/server.py [path/to/saft.xml]
        (or set SAFT_FILE; or call the load_saft_file tool at runtime)
"""

import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saft_store import SaftStore, StoreError  # noqa: E402

mcp = FastMCP(
    "saft-mcp",
    instructions=(
        "Read-only access to a Norwegian SAF-T Financial (v1.30) export: chart of accounts, "
        "MVA/VAT codes and supplier→account booking history. Call get_saft_summary first; "
        "if no file is loaded, ask the user for the SAF-T path and call load_saft_file. "
        "History is evidence, not a decision: report ambiguous results rather than picking."
    ),
)
store = SaftStore()


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except StoreError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def load_saft_file(path: str) -> dict:
    """Load (or switch to) a SAF-T XML file. Returns company, period and counts."""
    return _call(store.load, path)


@mcp.tool()
def get_saft_summary() -> dict:
    """Company, SAF-T version, period, software, counts and parse warnings of the loaded file."""
    return _call(store.summary)


@mcp.tool()
def list_accounts(query: str | None = None, prefix: str | None = None,
                  limit: int | None = None) -> dict:
    """Chart of accounts (kontoplan). Filter by text in ID/description (query) and/or
    account-number prefix (e.g. "7" or "65"). Default limit 200."""
    return _call(store.list_accounts, query, prefix, limit)


@mcp.tool()
def get_account(account_id: str) -> dict:
    """One GL account plus the suppliers whose invoices are usually booked to it."""
    return _call(store.get_account, account_id)


@mcp.tool()
def list_vat_codes(direction: str | None = None) -> dict:
    """MVA codes from the tax table with percentage, standard code and direction
    (input | output | reverse_charge | none | unknown). Optional direction filter."""
    return _call(store.list_vat_codes, direction)


@mcp.tool()
def find_vat_code(rate: float, direction: str = "input", date: str | None = None) -> dict:
    """VAT code(s) for a percentage (e.g. 25, 15, 12, 0). direction defaults to input
    (deductible purchases). date (YYYY-MM-DD) filters on effective/expiration dates.
    status is unique | ambiguous | none — never pick from an ambiguous result silently."""
    return _call(store.find_vat_code, rate, direction, date)


@mcp.tool()
def search_suppliers(query: str | None = None, org_number: str | None = None,
                     limit: int | None = None) -> dict:
    """Find suppliers (leverandører) by name fragment, supplier ID or org number.
    No arguments lists all. has_history tells whether there are ledger transactions."""
    return _call(store.search_suppliers, query, org_number, limit)


@mcp.tool()
def get_supplier_history(supplier_id: str) -> dict:
    """How a supplier's invoices were booked: payable accounts, expense accounts with
    counts, debit/credit totals, MK codes and share of cost lines (VAT accounts 27xx marked
    and excluded from shares)."""
    return _call(store.get_supplier_history, supplier_id)


@mcp.tool()
def export_saft_json(output_path: str) -> dict:
    """Write the full parsed SAF-T as JSON (saft-parser format) for the entry-builder,
    qa-validator and bank-matcher scripts (--saft). Overwrites output_path."""
    return _call(store.export_json, output_path)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SAFT_FILE")
    if path:
        try:
            store.load(path)
        except StoreError as exc:
            # Keep serving; tools will report that no file is loaded.
            print(f"saft-mcp: {exc}", file=sys.stderr)
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
