---
id: 5
title: Create QA validator skill
stage: general
date: 2026-11-10
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: none
labels: ["skill", "qa", "validation", "bookkeeping", "jr-taxi"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .claude/skills/qa-validator/SKILL.md
 - .claude/skills/qa-validator/scripts/validate_entries.py
 - .claude/skills/qa-validator/tests/test_validate_entries.py
tests:
 - .claude/skills/qa-validator/tests/test_validate_entries.py (26 tests, all pass)
---

## Prompt

Create a skill named "qa-validator".
Purpose: Quality-check generated entries before they reach the human.
Verify debit=credit, valid account codes (exist in SAF-T), valid VAT codes,
no missing required fields (date, amount, løyve). Block invalid entries.

## Response snapshot

Created `.claude/skills/qa-validator/`. The gate takes entry-builder JSON, the SAF-T JSON and the entry-builder config. Each bilag gets passed or blocked. Errors block and warnings don't. The checks cover:
- **Balance:** exact decimal comparison, the header total compared with the debit sum, and well-formed line amounts.
- **Accounts:** each konto must exist in SAF-T.
- **MK:** the code must exist, be valid on the bilag date, not be an output code on a cost line, and be present on every P&L line.
- **Required fields:** date (valid and not in the future), total amount, and løyve on P&L lines.
- **Løyve/bil:** consistent with the config.
- **Supplier:** a credit to the payable account needs a supplier that exists in SAF-T.
- **Other:** NOK only, duplicate invoices in the batch, and upstream blocked or review status carried over.

The CSV export contains only passed bilag. Exit codes are 0 (all passed), 2 (some blocked) and 1 (input error).

## Outcome

- ✅ Impact: Invalid bilag can no longer reach the human or the export, so the five-skill pipeline is complete.
- 🧪 Tests: 26 pass, including a pipeline test on real entry-builder output. All 82 tests across the 5 skills pass.
- 📁 Files: 3 new files under .claude/skills/qa-validator/
- 🔁 Next prompts: Commit the skills on a feature branch; run the full pipeline on real JR Taxi data.
- 🧠 Reflection: needs_review drafts with empty fields are blocked by design, so the human fixes them through entry-builder overrides rather than receiving incomplete entries.

## Evaluation notes (flywheel)

- Failure modes observed: none; all tests passed on the first run.
- Graders run and results (PASS/FAIL): unittest PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Check whether the "P&L = classes 3–8" rule matches JR Taxi's chart (for example, financial items in class 8 may not need a løyve).
