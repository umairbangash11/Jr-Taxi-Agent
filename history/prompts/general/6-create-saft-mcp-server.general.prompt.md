---
id: 6
title: Create saft-mcp server
stage: general
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: none
labels: ["mcp", "saft", "server", "chart-of-accounts", "mva"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .mcp.json
 - mcp-servers/saft-mcp/server.py
 - mcp-servers/saft-mcp/saft_store.py
 - mcp-servers/saft-mcp/requirements.txt
 - mcp-servers/saft-mcp/README.md
 - mcp-servers/saft-mcp/tests/test_saft_mcp.py
tests:
 - mcp-servers/saft-mcp/tests/test_saft_mcp.py (12 tests incl. stdio round trip, all pass)
---

## Prompt

saft-mcp — reads the SAF-T file and serves the chart of accounts, VAT codes, and supplier→account history.

## Response snapshot

Built a stdio MCP server with FastMCP from the already installed `mcp` 1.9.4 SDK. The query logic lives in `saft_store.py`, which has no MCP dependency and reuses the saft-parser skill's `parse_file`. Results are cached and re-parsed when the file's size or mtime changes. The server has 9 read-only tools:
- load_saft_file and get_saft_summary
- list_accounts and get_account (the account plus the suppliers that use it)
- list_vat_codes (with input, output or reverse-charge direction) and find_vat_code (by rate, direction and date, with a unique, ambiguous or none status)
- search_suppliers (by name, ID or org number) and get_supplier_history (shares of cost lines, with 27xx marked)
- export_saft_json, which writes the file the pipeline scripts expect

Errors are returned as ToolError. The server is registered in the project `.mcp.json` as `saft`, with SAFT_FILE expanded from the environment. Claude Code lists it as pending approval.

## Outcome

- ✅ Impact: Claude can query SAF-T data on demand without re-parsing or loading large JSON into context.
- 🧪 Tests: 12 pass, including a real stdio MCP client round trip.
- 📁 Files: .mcp.json plus 5 files under mcp-servers/saft-mcp/
- 🔁 Next prompts: Approve the server in Claude Code; point SAFT_FILE at JR Taxi's real export; optionally let entry-builder use the MCP tools instead of saft.json.
- 🧠 Reflection: Reusing the parser keeps one SAF-T implementation. The export tool connects the MCP server to the existing file-based scripts.

## Evaluation notes (flywheel)

- Failure modes observed: none; all tests passed on the first run.
- Graders run and results (PASS/FAIL): unittest PASS; `claude mcp list` shows the server (pending approval)
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Load a real multi-year SAF-T file and measure the time of the first call and memory use.
