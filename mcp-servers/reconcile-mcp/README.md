# reconcile-mcp

A read-only MCP server (stdio) for **bank reconciliation** (bankavstemming). It compares the bank
account in the ledger (SAF-T, account 1920 by default) with the bank statement, and returns the
**difference** together with the **exact bilag and bank lines** that cause it.

```
difference (ledger − bank) = Σ ledger_only − Σ bank_only + unexplained
```

It reuses the existing code:
- the `saft-parser` skill's `read_account_postings`, which reads every posting on the account together with its full voucher and the account's SAF-T opening and closing balances
- the `bank-matcher` skill's `read_bank`, which reads netbank CSV or CAMT.053

## Setup

- It is registered in the project's `.mcp.json` as **`reconcile`**. Approve it the first time you start `claude`.
- `SAFT_FILE` and `BANK_FILE` can load both files when the server starts. `RECONCILE_ACCOUNT` sets the account and defaults to `1920`.
- `RECONCILE_ROOTS` (recommended) restricts which folders can be read. Accepted files are `.xml` for SAF-T, and `.csv`, `.txt` or `.xml` for the bank statement.

## Tools

| Tool | Purpose |
|---|---|
| `load_ledger(saft_path, account_id="1920")` | Reads the postings on the bank account, with each posting's voucher, plus the SAF-T opening and closing balance |
| `load_bank_statement(path, …col overrides)` | Reads a CSV or CAMT file. For CAMT, the OPBD and CLBD balances are read as well |
| `reconcile(date_from?, date_to?, bank_opening_balance?, bank_closing_balance?, date_window=5)` | Runs the reconciliation. The period defaults to the statement's date range |
| `get_bilag(transaction_id)` | Returns the full voucher for a bilag: every line, account, amount and supplier or customer |

## How it works

1. **Ledger balance:** the SAF-T opening balance plus every posting before `date_from` gives the balance at the start of the period. Adding the postings inside the period gives the closing balance.
2. **Bank balance:** taken from the user-supplied balances, otherwise from the CAMT balances moved forward or back to the period boundaries using the statement's own lines. A CSV statement without balances is compared on movements only, and a warning is given.
3. **One-to-one matching:** a ledger posting and a bank line match when the signed amount is exact and the dates are no more than `date_window` days apart. The best pair is taken first, judged by closest date and then by overlapping words or the bilag number in the bank text.
4. **Combinations:** among what's left, 2–3 lines on one side that add up exactly to one line on the other side are matched. This covers several invoices paid in one transfer, or one bilag split across several bank lines. **If more than one combination fits, nothing is matched**, and the options are listed in `possible_combinations`.
5. **What remains** is reported:
   - **`ledger_only`:** each bilag with its date, amount, text and counter-lines (account, supplier). These have been posted but aren't on the bank statement, for example because the payment is in transit, the amount or date is wrong, or the posting is on the wrong account.
   - **`bank_only`:** bank lines with no posting. These are probably **missing bilag**.
   - **`unexplained`:** the part of the closing difference that the listed items don't cover. Usually this means the opening balances differ, or a reconciling item falls outside the period.
6. **`ambiguous_pairings`:** two lines with the same amount and similar dates where the pairing could be swapped. This doesn't change the difference.

`status` is `reconciled` only when there are no leftover items and no balance difference. Otherwise it is `differences`.

## Tests

```bash
python mcp-servers/reconcile-mcp/tests/test_reconcile_mcp.py -v
```
The 14 store tests build their SAF-T and CAMT fixtures from one transaction table, so the totals are checked by hand in the test docstring. They cover:
- the itemised difference
- comparing movements only
- the reconciled case
- an opening difference
- CAMT balances moved to a sub-period, and inconsistent balances
- ambiguous pairings and combinations
- the date window
- `get_bilag`
- errors
- reloading when a file changes

There is also 1 stdio round trip.
