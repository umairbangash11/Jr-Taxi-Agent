---
id: 8
title: Create bank-mcp server
stage: general
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: none
labels: ["mcp", "bank", "reconciliation", "camt053", "matching"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .mcp.json
 - mcp-servers/bank-mcp/server.py
 - mcp-servers/bank-mcp/bank_store.py
 - mcp-servers/bank-mcp/requirements.txt
 - mcp-servers/bank-mcp/README.md
 - mcp-servers/bank-mcp/tests/test_bank_mcp.py
tests:
 - mcp-servers/bank-mcp/tests/test_bank_mcp.py (10 tests incl. stdio round trip, all pass)
---

## Prompt

bank-mcp — reads bank statements and matches transactions by amount, date, vendor.

## Response snapshot

Built a stdio FastMCP server that reuses the bank-matcher skill's read_bank, score_pair, window_for, match and load_documents, so there is one set of matching rules. It has 6 tools: load_bank_statement (CSV auto-detection with column overrides, or CAMT), get_statement_summary, list_transactions (filters for direction, dates, text and amount), find_payment (ad-hoc candidates for one document), match_documents (one-to-one matching, up to 500 documents, with paid, uncertain, not_found or unmatchable status and the unmatched outgoing lines) and match_documents_file. Document summaries from document-mcp are accepted directly. Inputs are validated and the matching settings are checked. The statement is cached and reloaded when its size or mtime changes. The BANK_ROOTS sandbox and an allowlist of extensions limit which files can be read, and BANK_FILE preloads a statement. The server is registered in `.mcp.json` as `bank`.

## Outcome

- ✅ Impact: The three MCP servers (saft, documents, bank) now cover the data side of the pipeline, and document-mcp output feeds bank-mcp directly.
- 🧪 Tests: 10 pass, including a stdio round trip with a preloaded statement and sandbox rejection.
- 📁 Files: .mcp.json updated plus 5 new files under mcp-servers/bank-mcp/
- 🔁 Next prompts: Approve the servers; set BANK_ROOTS; test on a real JR Taxi statement; commit on a feature branch.
- 🧠 Reflection: find_payment, the ad-hoc lookup, is explicitly labelled as candidates only, so it can't be mistaken for a paid verdict.

## Evaluation notes (flywheel)

- Failure modes observed: none in the tests; unused imports were cleaned up before the run.
- Graders run and results (PASS/FAIL): unittest PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Match a real month of documents against the real statement and count false `paid` results (target: 0).
