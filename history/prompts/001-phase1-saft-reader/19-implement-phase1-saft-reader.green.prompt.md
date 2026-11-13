---
id: 19
title: Implement Phase 1 SAF-T reader
stage: green
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: 001-phase1-saft-reader
branch: 001-phase1-saft-reader
user: umairbangash11
command: /sp.implement
labels: ["implement", "phase-1", "saft", "tdd", "supplier-account-map"]
links:
  spec: specs/001-phase1-saft-reader/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - phase-1/saft_reader.py
 - phase-1/saft_data.json
 - shared/__init__.py
 - shared/models.py
 - samples/saft_sample.xml
 - tests/conftest.py
 - tests/phase-1/test_sections.py
 - tests/phase-1/test_namespace_and_errors.py
 - tests/phase-1/test_supplier_account_map.py
 - tests/phase-1/test_unknowns.py
 - tests/phase-1/test_performance.py
 - specs/001-phase1-saft-reader/tasks.md
tests:
 - tests/phase-1 (32 tests, all pass; 50 000-line run 1.5 s)
---

## Prompt

/sp.implement

(no additional user input)

## Response snapshot

The checklist gate passed (16/16). T001–T022 were implemented TDD-style, with each story's tests written and seen failing before its code:
- **Setup:** the phase folders and a tests/conftest.py path shim.
- **shared/models.py:** frozen dataclasses with `UNKNOWN`.
- **samples/saft_sample.xml:** a fake sample generated from a scratchpad script, 19 transactions, all verified balanced.
- **phase-1/saft_reader.py:** a stdlib iterparse reader with strict root and namespace validation, matching in Clark notation, invoice detection (one supplier, net credit), the ≥ 80 % rule counted per invoice over P&L accounts 3–8 using Decimal, the four unknown reasons, unknown counting, numeric-aware sorting, an atomic and deterministic write, and a CLI returning exit codes 0, 1 and 2.

**Results:** all 32 tests pass. The generated phase-1/saft_data.json gives NIO → 7033 (0.8, with the payment and netting excluded), ONEPARK → 7161, RA FORSIKRING → 7027 and 50099 → 7026 (with a warning). AMBI, SPLITT, 50006 and 50007 are unknown with the correct reasons. An ad-hoc contract check found no problems.

T023 (human review) is left open for the user. Phase 2 was not started.

## Outcome

- ✅ Impact: Phase 1's automated exit criteria are met: the four sections are populated and the supplier→account map is proven by tests.
- 🧪 Tests: 32/32 pass (sections 5, namespace and errors 9, supplier map 12, unknowns 4, performance and determinism 2)
- 📁 Files: 11 new files in /phase-1, /shared, /tests and /samples, plus tasks.md checkboxes
- 🔁 Next prompts: The user reviews phase-1/saft_data.json against quickstart.md (T023), then commits. Phase 2 needs its own /sp.specify.
- 🧠 Reflection: Fixing the sample's contents and the expected map in tasks.md before coding meant the implementation had to satisfy the spec as written, not the other way round.

## Evaluation notes (flywheel)

- Failure modes observed:
  - T005's "all four sections non-empty" check depends on US2, so the US1 checkpoint couldn't be fully green. This was predicted and resolved by US2.
  - A dead no-op block in read_saft was removed.
- Graders run and results (PASS/FAIL): pytest tests/phase-1 32/32 PASS; contract conformance PASS; scope check PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): In future task plans, put "all sections populated" in the polish phase instead of US1.
