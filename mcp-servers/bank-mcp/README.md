# bank-mcp

A read-only MCP server (stdio) that reads a **bank statement** and matches transactions to
documents by **amount, date and vendor**.

Parsing and matching are done by the `bank-matcher` skill
(`.claude/skills/bank-matcher/scripts/match_bank.py`), so the server and the script give the same
answers. The loaded statement is cached and read again when the file changes.

## Setup

- Requires Python ≥ 3.10 and `mcp>=1.9,<2`, which is already installed.
- It is registered in the project's `.mcp.json` as **`bank`**. Approve it the first time you start `claude`.
- `BANK_FILE` optionally loads a statement when the server starts.
- **`BANK_ROOTS` (recommended):** bank data is sensitive. Set this to the folder(s) that hold the statements, separated with `;` on Windows, and every other path is refused.
- Accepted files are `.csv`, `.txt` and `.xml` for statements, and `.json` for `match_documents_file`.

## Tools

| Tool | Purpose |
|---|---|
| `load_bank_statement(path, date_col?, text_cols?, amount_col?, out_col?, in_col?)` | Loads a CSV (columns found automatically, with overrides using the header names) or a CAMT.053/054 XML file |
| `get_statement_summary()` | Line counts, total out and total in, date range and warnings |
| `list_transactions(direction, date_from, date_to, query, min_amount, max_amount, limit)` | Bank lines matching the filters. Outgoing amounts are negative |
| `find_payment(amount, date?, vendor?, invoice_number?, org_number?, document_type?)` | Quick lookup: the candidate lines for **one** document, best first |
| `match_documents(documents, …)` | Matches up to 500 documents one-to-one and returns `paid`, `uncertain`, `not_found` or `unmatchable`, plus the outgoing lines that matched no document |
| `match_documents_file(json_path, …)` | The same, reading document-reader or entry-builder JSON from a file |

The matching options are `receipt_days=7`, `invoice_days=60`, `early_days=3` and `tolerance=0` (NOK).

### Documents for `match_documents`

The **`summary` objects from document-mcp can be passed as they are**, with an `id` added. Other key names are accepted too:
`{id|file, vendor|supplier, date, amount|total_amount, invoice_number?, org|org_number?, type|document_type, currency?}`

### Status rules (same as the bank-matcher skill)

- **paid:** the amount is exact, the date is inside the window, the vendor or reference is recognised, and the bank line has no competitor.
- **uncertain:** a candidate exists, but the reasons explain why it's weak. Examples: the vendor isn't recognised or only partly, two lines fit almost equally, two documents compete for the same line, or the payment came before the document date.
- **not_found:** no outgoing line with that amount inside the window.
- **unmatchable:** the document has no amount.

Combined and partial payments are not detected.

## Tests

```bash
python mcp-servers/bank-mcp/tests/test_bank_mcp.py -v
```
There are 9 store tests (summary, filters, find_payment, matching, validation, CAMT, reloading when the file changes, sandbox) and 1 stdio round trip.
