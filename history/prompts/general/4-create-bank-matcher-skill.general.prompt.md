---
id: 4
title: Create bank matcher skill
stage: general
date: 2026-11-10
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: none
labels: ["skill", "bank-reconciliation", "camt053", "csv", "matching"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .claude/skills/bank-matcher/SKILL.md
 - .claude/skills/bank-matcher/scripts/match_bank.py
 - .claude/skills/bank-matcher/tests/test_match_bank.py
 - .claude/skills/bank-matcher/tests/fixtures/bank_dnb.csv
 - .claude/skills/bank-matcher/tests/fixtures/bank_camt053.xml
tests:
 - .claude/skills/bank-matcher/tests/test_match_bank.py (15 tests, all pass)
---

## Prompt

Create a skill named "bank-matcher".
Purpose: Match documents to bank statement lines by amount, date, and vendor.
Returns paid/not-found status for each document. Flags uncertain matches.

## Response snapshot

Created `.claude/skills/bank-matcher/`. It reads Norwegian netbank CSV, with the delimiter sniffed, UTF-8 or cp1252, columns auto-detected (split Uttak/Innskudd or signed Beløp) and CLI overrides. It also reads CAMT.053/054 XML. Documents come from document-reader or entry-builder JSON. The amount must match an outgoing line exactly. The date window is -3 to +7 days for a kvittering and -3 to +60 days for a faktura. The vendor signal is reference (invoice or org number in the text), strong, weak or none. Lines are assigned one-to-one, greedy by score. Each document gets status paid, uncertain (with reasons), not_found or unmatchable. Outgoing lines with no document are listed as possible missing bilag.

## Outcome

- ✅ Impact: The bank reconciliation step is in place, so the pipeline now covers SAF-T, documents, bilag and bank.
- 🧪 Tests: 15 pass. They cover CSV and CAMT parsing, cp1252, the paid, uncertain, not_found and unmatchable statuses, conflicts and entry-builder input. The other 3 skill suites still pass.
- 📁 Files: 5 new files under .claude/skills/bank-matcher/
- 🔁 Next prompts: Test with JR Taxi's real bank export; consider combined/partial payment support.
- 🧠 Reflection: The first test expectation for the Kiwi case was wrong. A shared place name produced a weak signal, and the code correctly kept the match uncertain.

## Evaluation notes (flywheel)

- Failure modes observed: In the draft, the CSV fallback mutated the global csv.excel dialect. Fixed before the tests ran.
- Graders run and results (PASS/FAIL): unittest PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Run on one month of real bank data and count the false `paid` results (target: 0).
