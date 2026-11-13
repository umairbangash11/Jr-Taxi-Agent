---
id: 1
title: Create SAF-T parser skill
stage: general
date: 2026-11-10
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: none
labels: ["skill", "saft", "xml-parsing", "norway", "mva"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .claude/skills/saft-parser/SKILL.md
 - .claude/skills/saft-parser/scripts/parse_saft.py
 - .claude/skills/saft-parser/tests/test_parse_saft.py
 - .claude/skills/saft-parser/tests/fixtures/sample_v130.xml
tests:
 - .claude/skills/saft-parser/tests/test_parse_saft.py (8 tests, all pass)
---

## Prompt

Create a skill named "saft-parser".
Purpose: Parse Norwegian SAF-T (Standard Audit File for Tax) XML files.
It must extract GL accounts (ID + description), MVA/VAT codes (code + percentage),
suppliers (name + ID), and supplier→account mappings derived from GeneralLedgerEntries.
Output structured JSON. Must handle the SAF-T v1.30 namespace correctly.

## Response snapshot

Created the Claude Code skill `.claude/skills/saft-parser/`. SKILL.md documents usage, the JSON schema, namespace handling and the mapping heuristic. `scripts/parse_saft.py` is a streaming iterparse parser that uses only the stdlib. It detects the namespace from the root, rejects anything other than `urn:StandardAuditFile-Taxation-Financial:NO` (exit 2), and warns when AuditFileVersion is not 1.30. It extracts GL accounts, VAT codes with percentages, and suppliers. It derives supplier→account mappings from transactions where the supplier lines are net credit (invoices), so bank accounts from payments stay out. The tests use a minimal v1.30 fixture.

## Outcome

- ✅ Impact: The new saft-parser skill turns Norwegian SAF-T v1.30 exports into structured JSON.
- 🧪 Tests: 8 unittest cases pass. They cover meta, accounts, VAT codes, suppliers, the mapping (payment excluded), wrong namespace, the override flag and invalid XML.
- 📁 Files: 4 new files under .claude/skills/saft-parser/
- 🔁 Next prompts: Validate against a real SAF-T export from the user's accounting system; optionally exclude VAT accounts from primary_expense_account.
- 🧠 Reflection: The first ranking let a tie in counts pick the input-VAT account 2710 as primary. Breaking ties by total debit fixed it.

## Evaluation notes (flywheel)

- Failure modes observed: When counts tied, the primary expense account was chosen by account ID. Fixed.
- Graders run and results (PASS/FAIL): unittest PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Run on a real multi-GB export to confirm memory use stays flat.
