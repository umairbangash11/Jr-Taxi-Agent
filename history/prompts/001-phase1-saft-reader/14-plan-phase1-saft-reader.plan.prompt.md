---
id: 14
title: Plan Phase 1 SAF-T reader
stage: plan
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: 001-phase1-saft-reader
branch: 001-phase1-saft-reader
user: umairbangash11
command: /sp.plan
labels: ["plan", "phase-1", "saft", "research", "data-model", "contracts"]
links:
  spec: specs/001-phase1-saft-reader/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - specs/001-phase1-saft-reader/plan.md
 - specs/001-phase1-saft-reader/research.md
 - specs/001-phase1-saft-reader/data-model.md
 - specs/001-phase1-saft-reader/contracts/saft_data.schema.json
 - specs/001-phase1-saft-reader/contracts/cli.md
 - specs/001-phase1-saft-reader/quickstart.md
tests:
 - none (planning stage); schema JSON validated as parseable
---

## Prompt

/sp.plan

(no additional user input)

## Response snapshot

Ran setup-plan.ps1, which created plan.md for 001-phase1-saft-reader.

**Technical Context:** Python 3.13.2 using only the standard library (iterparse streaming), pytest 8.3.3, expat 2.6.4 (which protects against entity expansion), and no LLM in this phase. The Agents SDK is not installed and isn't needed until Phase 2.

**Constitution Check:** every gate passes, both before and after design, and the Complexity Tracking table is empty.

**research.md, decisions R1–R11:**
- stdlib streaming parser
- namespace validated from the root and matched in Clark notation
- the saft-parser skill ported into /phase-1 rather than imported, to respect the phase boundary
- invoice = one supplier whose lines are net credit
- only P&L classes 3–8 mappable
- the ≥ 80 % rule counted per invoice, with "multiple accounts on the same invoices" as an extra unknown reason
- the literal "unknown" and a blank VAT entry `""` = 0 % from source "implicit"
- atomic, deterministic output
- frozen dataclasses in /shared
- pytest with a conftest path shim

**Other artifacts:**
- data-model.md: entities and the mapping decision table
- contracts: a JSON Schema of saft_data.json that enforces "unknown" unions and mapped accounts starting with 3–8, plus a CLI and Python API contract
- quickstart.md: a run guide and a human-review list

update-agent-context.ps1 found no markers in CLAUDE.md and only added a BOM, so that change was reverted.

## Outcome

- ✅ Impact: Phase 1 has a gated, implementable design and is ready for /sp.tasks.
- 🧪 Tests: none yet; the planned suites are listed in plan.md and research R10.
- 📁 Files: 6 plan artifacts under specs/001-phase1-saft-reader/
- 🔁 Next prompts: /sp.tasks
- 🧠 Reflection: Splitting invoices revealed a third "unknown" reason that the spec hadn't named. It was added in the data model as a refinement of FR-008 rather than a new rule.

## Evaluation notes (flywheel)

- Failure modes observed: update-agent-context.ps1 made a BOM-only change to CLAUDE.md, which was reverted.
- Graders run and results (PASS/FAIL): Constitution Check PASS (pre- and post-design); schema parses PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Have /sp.tasks generate tests first (red) for the supplier map, as the exit criterion.
