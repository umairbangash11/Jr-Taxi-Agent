#!/usr/bin/env python3
"""reconcile-mcp: MCP server (stdio) that reconciles the bank GL account in SAF-T against a
bank statement and returns the difference itemised by bilag and bank line.

Start: python mcp-servers/reconcile-mcp/server.py
Optional: SAFT_FILE + BANK_FILE preload; RECONCILE_ACCOUNT (default 1920);
RECONCILE_ROOTS=dir1;dir2 restricts readable paths.
"""

import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reconcile_store import ReconcileError, ReconcileStore  # noqa: E402

mcp = FastMCP(
    "reconcile-mcp",
    instructions=(
        "Bank reconciliation (bankavstemming): ledger bank account (SAF-T, default 1920) vs bank "
        "statement. Load both, then call reconcile. The difference is 'ledger minus bank' and "
        "is itemised: ledger_only = bilag posted but not on the bank; bank_only = bank lines "
        "with no posting (missing bilag). Report 'unexplained' and 'possible_combinations' "
        "explicitly; never net them away. Use get_bilag to show a voucher's full lines."
    ),
)
store = ReconcileStore()


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ReconcileError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def load_ledger(saft_path: str, account_id: str = "1920") -> dict:
    """Read postings on a bank GL account (default 1920) from a SAF-T XML file, with each
    posting's full voucher and the account's SAF-T opening/closing balance."""
    return _call(store.load_ledger, saft_path, account_id)


@mcp.tool()
def load_bank_statement(path: str, date_col: str | None = None,
                        text_cols: list[str] | None = None, amount_col: str | None = None,
                        out_col: str | None = None, in_col: str | None = None) -> dict:
    """Read a bank statement: netbank CSV (columns auto-detected, overridable by header name)
    or CAMT.053 XML (opening/closing balances are read too)."""
    return _call(store.load_bank, path, date_col, text_cols, amount_col, out_col, in_col)


@mcp.tool()
def reconcile(date_from: str | None = None, date_to: str | None = None,
              bank_opening_balance: float | None = None,
              bank_closing_balance: float | None = None, date_window: int = 5) -> dict:
    """Reconcile ledger vs bank for a period (default: the statement's date range).
    Returns balances on both sides, the difference (ledger minus bank), and the exact items
    behind it: ledger_only bilag (with counter-lines) and bank_only lines. Exact-amount
    pairs within date_window days are matched one-to-one; 2-3 lines summing exactly to one
    line on the other side are matched as combinations. For CSV statements pass the bank
    balance(s) to get a balance comparison, otherwise only movements are compared."""
    return _call(store.reconcile, date_from, date_to, bank_opening_balance,
                 bank_closing_balance, date_window)


@mcp.tool()
def get_bilag(transaction_id: str) -> dict:
    """Full voucher (all lines, accounts, amounts, supplier/customer IDs) for a bilag that
    touches the loaded bank account."""
    return _call(store.get_bilag, transaction_id)


def main():
    saft, bank = os.environ.get("SAFT_FILE"), os.environ.get("BANK_FILE")
    account = os.environ.get("RECONCILE_ACCOUNT") or "1920"
    for label, fn, args in (("SAFT_FILE", store.load_ledger, (saft, account)),
                            ("BANK_FILE", store.load_bank, (bank,))):
        if args[0]:
            try:
                fn(*args)
            except ReconcileError as exc:
                print(f"reconcile-mcp: {label}: {exc}", file=sys.stderr)
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
