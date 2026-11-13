---
id: 18
title: Tasks for Phase 1 SAF-T reader
stage: tasks
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: 001-phase1-saft-reader
branch: 001-phase1-saft-reader
user: umairbangash11
command: /sp.tasks
labels: ["tasks", "phase-1", "tdd", "saft"]
links:
  spec: specs/001-phase1-saft-reader/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - specs/001-phase1-saft-reader/tasks.md
tests:
 - none (task generation); format validation 23/23 PASS
---

## Prompt

/sp.tasks

(no additional user input)

## Response snapshot

Generated specs/001-phase1-saft-reader/tasks.md with 23 tasks.

**Phases:** Setup (T001–T002), Foundational (T003 models, T004 fake sample), US1 (T005–T013), US2 (T014–T017, the exit criterion), US3 (T018–T019) and Polish/Exit (T020–T023).

**Tests:** included and written first in every story, because spec FR-014 and the constitution make them mandatory.

**Sample:** T004 specifies the fake sample exactly:
- accounts, including one without a description and one without an ID
- VAT codes 2/11/12 (12 in two periods) and 99 with no percentage
- 7 suppliers, one without a name
- NIO with 5 invoices, 4 of them on 7033, so exactly 80 %
- a payment, ONEPARK with a blank-VAT invoice, RA FORSIKRING, AMBI at 67 %, SPLITT with split invoices
- supplier 50099 present only in the ledger, plus a netting transaction and a sales transaction

**Exact expectations:** T014 states the expected map for each supplier, which makes the exit-criterion test fully specified.

**Validation:** all tasks are in checkbox format with IDs, and story labels where required. All paths are inside /phase-1, /shared, /tests and /samples. One inconsistency (the T018 skipped count) was corrected.

## Outcome

- ✅ Impact: Phase 1 is ready for /sp.implement with no ambiguity about scope or expected results.
- 🧪 Tests: 6 test files planned (sections, namespace/errors, supplier map, unknowns, performance, conftest)
- 📁 Files: tasks.md
- 🔁 Next prompts: /sp.implement
- 🧠 Reflection: Writing the sample's contents and the expected map into the tasks means the test can't be quietly bent to fit the code.

## Evaluation notes (flywheel)

- Failure modes observed: The first draft of T018 expected 2 skipped records where the sample defines 1. Fixed before reporting.
- Graders run and results (PASS/FAIL): checklist format 23/23 PASS; path scope PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
