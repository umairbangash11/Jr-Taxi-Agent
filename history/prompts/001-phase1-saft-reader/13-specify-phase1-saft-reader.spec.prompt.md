---
id: 13
title: Specify Phase 1 SAF-T reader
stage: spec
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: 001-phase1-saft-reader
branch: 001-phase1-saft-reader
user: umairbangash11
command: /sp.specify
labels: ["spec", "phase-1", "saft", "supplier-account-map", "constitution"]
links:
  spec: specs/001-phase1-saft-reader/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - specs/001-phase1-saft-reader/spec.md
 - specs/001-phase1-saft-reader/checklists/requirements.md
tests:
 - none (specification stage)
---

## Prompt

/sp.specify

Phase: 1 — SAF-T Reader (the agent's "brain")
Folder: limit all work to /phase-1 (plus /shared models, /tests, /samples)

GOAL
Parse a Norwegian SAF-T XML export and produce structured data the rest 
of the agent will use.

MUST EXTRACT
1. Accounts — account ID + description (e.g. 7026 Reparasjoner, 7155 
   Bespisning/Mat, 1930 Bedriftskonto).
2. VAT/MVA codes — code + percentage (e.g. 2 = 25%, 12 = 12%, blank = 0%).
3. Suppliers — name + ID.
4. Supplier→account mapping — learned from past GeneralLedgerEntries 
   (e.g. NIO → 7033, ONEPARK → 7161, RA FORSIKRING → 7027).

OUTPUT
- A clean JSON file saved in /phase-1 (e.g. saft_data.json) containing 
  accounts, vat_codes, suppliers, and supplier_account_map.

CONSTRAINTS
- Handle the SAF-T XML namespace correctly.
- Use a fake/sample SAF-T file in /samples (no real client data).
- If a field is missing or ambiguous, record it as "unknown" — do not guess.

EXIT CRITERIA
- Running the reader on the sample SAF-T file produces correct JSON with 
  all four sections populated.
- A test in /tests confirms the supplier→account map is built correctly.

## Response snapshot

Created branch `001-phase1-saft-reader` and `specs/001-phase1-saft-reader/spec.md`.

**Stories:** 3 user stories:
- P1: reference data from SAF-T
- P1: the supplier→account map
- P2: unknowns visible with reasons

**Requirements:** 15 functional requirements:
- namespace-agnostic, with strict Norwegian SAF-T validation
- an explicit "no VAT code" entry at 0 %, distinct from a code whose percentage is `unknown`
- the map built only from supplier invoices (payable credited) and P&L accounts, so 1930, 2400 and 27xx are never mapped
- the literal `unknown` plus a reason, with no defaults
- `saft_data.json` in /phase-1 with the 4 sections and a summary
- a fake sample covering every case
- tests in /tests/phase-1
- deterministic, no LLM

**Also:** 6 measurable success criteria, edge cases, assumptions and out-of-scope items.

**Clarification:** one question was asked and answered. A supplier is mapped when one account covers ≥ 80 % of its invoices; otherwise it is `unknown` with candidates. The quality checklist passes on the first iteration.

## Outcome

- ✅ Impact: Phase 1 has a testable, constitution-aligned spec that is ready for /sp.plan.
- 🧪 Tests: none (spec); FR-014 defines the required tests.
- 📁 Files: spec.md and checklists/requirements.md
- 🔁 Next prompts: /sp.plan for Phase 1, which decides whether to reuse the pre-constitution saft-parser code by porting it into /phase-1.
- 🧠 Reflection: The first draft wrote the 80 % threshold as already clarified before the user had answered. It was caught, turned into a real question, and the user's answer was then recorded.

## Evaluation notes (flywheel)

- Failure modes observed:
  - create-new-feature.ps1 failed at its last step, because `Join-Path` with 3 arguments is unsupported in Windows PowerShell 5.1. The branch and spec were created, and the prompts directory was created manually.
  - The spec draft recorded an unconfirmed clarification as decided. It was corrected.
- Graders run and results (PASS/FAIL): spec quality checklist PASS; placeholder scan PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Fix create-new-feature.ps1 (nested Join-Path) in a separate tooling change.
