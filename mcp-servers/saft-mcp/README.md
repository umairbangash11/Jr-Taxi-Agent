# saft-mcp

A read-only MCP server (stdio) for a Norwegian SAF-T Financial v1.30 file. It serves the
**chart of accounts**, the **MVA/VAT codes** and each supplier's **supplier → account booking history**.

The parsing is done by the `saft-parser` skill (`.claude/skills/saft-parser/scripts/parse_saft.py`),
so the project has only one SAF-T implementation. The parsed file is cached and parsed again
automatically when the file changes (size or mtime).

## Setup

- Requires Python ≥ 3.10 and `mcp>=1.9,<2`, which is already installed here (1.9.4). Install with `pip install -r requirements.txt`.
- It is registered for Claude Code in the project's `.mcp.json` as the server **`saft`**. The first time you run `claude` in this project, approve it. You can check it with `claude mcp list`.
- To choose which SAF-T file it uses, either:
  - set `SAFT_FILE=C:\path\to\SAF-T.xml` before starting Claude Code, or
  - leave it unset and call `load_saft_file` with the path at runtime.

To run it by hand: `python mcp-servers/saft-mcp/server.py [file.xml]`

## Tools

| Tool | Returns |
|---|---|
| `load_saft_file(path)` | Loads or switches the file, and returns a summary |
| `get_saft_summary()` | Company, version, period, software, counts and parse warnings |
| `list_accounts(query?, prefix?, limit?)` | Kontoplan, filtered by text and/or account-number prefix |
| `get_account(account_id)` | One account plus the suppliers usually booked to it |
| `list_vat_codes(direction?)` | MVA codes with `direction`: `input`, `output`, `reverse_charge`, `none` or `unknown` |
| `find_vat_code(rate, direction="input", date?)` | The code(s) for a rate that are valid on a date. `status` is `unique`, `ambiguous` or `none` |
| `search_suppliers(query?, org_number?, limit?)` | Suppliers matched by name fragment, ID or org number, with `has_history` |
| `get_supplier_history(supplier_id)` | Payable accounts, plus expense accounts with counts, totals, MK codes and `share_of_cost_lines`. VAT accounts (27xx) are marked |
| `export_saft_json(output_path)` | Writes the parsed SAF-T as JSON for the scripts' `--saft` argument (entry-builder, qa-validator) |

Lists default to a limit of 200 items, with a maximum of 1000. Each list response includes `total`, `returned` and `truncated`.
Errors such as no file loaded, an unknown account or a wrong namespace come back as MCP tool errors (`isError: true`).

`direction` uses the Norwegian SAF-T standard tax codes:
- **input:** 1, 11, 12, 13, 14 and 15
- **output:** 3, 31, 32, 33, 5, 51, 52 and 6
- **reverse_charge:** 81–92
- **none:** 0

## Tests

```bash
python mcp-servers/saft-mcp/tests/test_saft_mcp.py -v
```
There are 11 store tests and 1 full stdio round trip. The round trip starts `server.py`, lists the tools, calls them through the MCP client, and checks the error paths.
