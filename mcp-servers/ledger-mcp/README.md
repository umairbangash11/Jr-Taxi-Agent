# ledger-mcp

An MCP server (stdio) that **stores booked JR Taxi entries (bilag)** and **checks for duplicates**.
Data is stored in SQLite from the Python standard library, and every amount is stored in whole øre.

## Setup

- It is registered in the project's `.mcp.json` as **`ledger`**. Approve it the first time you start `claude`.
- The database is at `LEDGER_DB`, which defaults to `data/ledger.sqlite` in the project. `data/` is listed in **`.gitignore`**, so the database is never committed. **Back up this file.** It is the booking record.

## Bookkeeping rules enforced by the database itself

| Rule | How it's enforced |
|---|---|
| Booked entries can't be deleted or edited | SQLite triggers refuse `DELETE`, refuse `UPDATE` on booked content, and refuse every change to lines |
| Corrections are reversals | `reverse_entry` books a mirror entry, and the original's status can change only once, from `booked` to `reversed` |
| Gapless bilag numbering | `YYYY-NNNNN` per year of the entry date, allocated inside the write transaction |
| A complete trail | The append-only `audit_log` records every booking, refusal, override and reversal, together with who did it |
| Only approved bilag | `book_entry` requires `qa_status == "passed"` (the qa-validator output), a `booked_by` name, balanced lines, a date that isn't in the future, and NOK |

## Duplicate detection

| Level | When | Effect on booking |
|---|---|---|
| `duplicate` | Same **source file** (sha256, so renamed copies are caught), or same **supplier and invoice number** (normalised, so `2025-0417` = `2025-417`), or **identical date and lines** with no invoice number that tells them apart | **Always refused** |
| `possible_duplicate` | Same supplier and amount within 7 days, or identical lines with different invoice numbers, or the same amount and date when the supplier can't be compared | Refused unless `allow_possible_duplicate=true` **and** an `override_reason` are given. The override is stored in the entry's note and in the audit log |
| `previously_reversed` | The match is an entry that was reversed | Reported for information only. Re-booking a corrected entry is allowed |

The same invoice number from a **different** supplier is not a duplicate.

## Tools

| Tool | Writes? | Purpose |
|---|---|---|
| `check_duplicate(bilag)` | no | Checks a bilag, or loose fields `{supplier_id, vendor_name, org_number, invoice_number, date, amount, source_file}` |
| `book_entry(bilag, booked_by, allow_possible_duplicate?, override_reason?)` | **yes** | Books one bilag that passed QA |
| `book_qa_file(path, booked_by)` | **yes** | Books every passed bilag in a qa-validator JSON file, with no overrides |
| `reverse_entry(bilag_no, reason, booked_by, date?)` | **yes** | Books a reversal entry |
| `get_entry(bilag_no)` / `list_entries(...)` | no | Look up booked entries |
| `get_audit_log(bilag_no?)` / `get_ledger_summary()` | no | Show the trail and the totals |

The server's instructions tell Claude to call the **write** tools only after the user has explicitly approved that specific booking or reversal.

## Where it sits in the pipeline

```
document-mcp → entry-builder → qa-validator → check_duplicate → (human approves) → book_entry
                                                                                  ↘ reverse_entry for corrections
```

## Tests

```bash
python mcp-servers/ledger-mcp/tests/test_ledger_mcp.py -v
```
There are 16 store tests and 1 stdio round trip. They cover:
- numbering and the QA gate
- validation
- every duplicate level and the override flow
- the invoice-number normalisation
- the source-hash check
- reversing and re-booking
- the database triggers rejecting deletes and edits
- data surviving a restart
- booking from a file
