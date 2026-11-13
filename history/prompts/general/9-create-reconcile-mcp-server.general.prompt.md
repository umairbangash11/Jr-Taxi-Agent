---
id: 9
title: Create reconcile-mcp server
stage: general
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: none
labels: ["mcp", "reconciliation", "bankavstemming", "saft", "camt053"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .mcp.json
 - .claude/skills/saft-parser/scripts/parse_saft.py
 - .claude/skills/saft-parser/tests/test_parse_saft.py
 - mcp-servers/reconcile-mcp/server.py
 - mcp-servers/reconcile-mcp/reconcile_store.py
 - mcp-servers/reconcile-mcp/requirements.txt
 - mcp-servers/reconcile-mcp/README.md
 - mcp-servers/reconcile-mcp/tests/test_reconcile_mcp.py
tests:
 - mcp-servers/reconcile-mcp/tests/test_reconcile_mcp.py (15 tests incl. stdio round trip, all pass)
 - .claude/skills/saft-parser/tests/test_parse_saft.py (+1 test for read_account_postings, 9 pass)
 - full regression: 130 tests across 5 skills + 4 MCP servers pass
---

## Prompt

reconcile-mcp — compares ledger vs bank, returns the difference and the exact bilag.

## Response snapshot

**saft-parser (additive change):** added an `_handle_other` hook to `parse_saft.py`, a `PostingParser` subclass, and `read_account_postings()`. The new function streams the postings on given accounts with their full vouchers, the JournalID, and the SAF-T opening and closing balances. The existing behaviour is unchanged.

**reconcile-mcp:** built a stdio FastMCP server with 4 tools: load_ledger, load_bank_statement, reconcile and get_bilag. It works as follows:
- **Ledger balances:** the SAF-T opening balance is rolled forward with the postings before the period, then the postings inside it.
- **Bank balances:** taken from the user, or from CAMT OPBD/CLBD rolled to the period boundaries. A CSV without balances is compared on movements only, with a warning.
- **Matching:** pairs need an exact signed amount and a date within the window, and are matched one-to-one by score. After that, combinations of 2–3 lines summing to one line are matched, but only when a single combination fits. Otherwise the options go to possible_combinations.
- **Output:** the difference (ledger minus bank) itemised as ledger_only bilag with counter-lines and bank_only lines, plus the unexplained remainder, ambiguous pairings and a status.

Paths are sandboxed with RECONCILE_ROOTS, the files are reloaded when they change, and the server is registered in `.mcp.json` as `reconcile`.

## Outcome

- ✅ Impact: The reconciliation answers "how big is the difference" and "which bilag cause it" exactly, with an explicit unexplained remainder.
- 🧪 Tests: 15 pass. The hand-checked scenario reconciles exactly: -1051 = -1500 - (-449), with 0 unexplained. The full regression of 130 tests passes.
- 📁 Files: 5 new files under mcp-servers/reconcile-mcp/; parse_saft.py extended; .mcp.json updated
- 🔁 Next prompts: Approve the 4 MCP servers; run on JR Taxi's real SAF-T and bank export; commit on a feature branch.
- 🧠 Reflection: Combination matching is refused when it is ambiguous, so a wrong pairing can never hide a real difference.

## Evaluation notes (flywheel)

- Failure modes observed: The draft used a CAMT opening balance unadjusted when the period started after the statement start. This was caught in review and fixed with roll-forward and roll-back logic, which a sub-period test now covers. A garbled warning condition was also fixed.
- Graders run and results (PASS/FAIL): unittest PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Reconcile a real month in which the user already knows the differences, and confirm they all appear in ledger_only or bank_only with 0 unexplained.
