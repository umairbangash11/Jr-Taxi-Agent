---
id: 15
title: Confirm Phase 1 plan direction
stage: plan
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: 001-phase1-saft-reader
branch: 001-phase1-saft-reader
user: umairbangash11
command: /sp.plan
labels: ["plan", "phase-1", "traceability", "saft"]
links:
  spec: specs/001-phase1-saft-reader/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - specs/001-phase1-saft-reader/plan.md
tests:
 - none (planning stage)
---

## Prompt

/sp.plan

Create the implementation plan for Phase 1 (SAF-T Reader), based on the 
approved spec. Use this technical direction:

TECH APPROACH
- Python 3.13, standard library only (xml.etree.ElementTree, json, decimal, 
  dataclasses, argparse). No LLM in this phase. No new dependencies.
- Streaming parse (iterparse) so large SAF-T files use flat memory.
- Namespace-agnostic element matching (handle SAF-T 1.30 namespace).

MAPPING RULES (supplier → account)
- Learn only from supplier INVOICES (not all lines).
- Count by invoice, not by line (one big invoice can't dominate).
- Map an account only when it is on ≥ 80% of the supplier's invoices.
- Only P&L expense accounts (account starts 3–8); never map to 1930, 2400, 
  or 27xx.
- Below 80%, or split across accounts → "unknown" with a reason. Never guess.

OUTPUT
- phase-1/saft_data.json with: accounts, vat_codes, suppliers, 
  supplier_account_map, summary.
- Shared dataclasses go in /shared/models.py.
- Deterministic output (same input → same file); write atomically.

TESTING
- pytest, tests in /tests/phase-1/.
- A fake sample SAF-T in /samples covering every rule.

Keep all changes inside /phase-1, /shared, /tests, /samples.

## Response snapshot

setup-plan.ps1 was deliberately not re-run, because it copies the template over plan.md with -Force and would have erased the existing approved plan. All 14 directives were traced with grep to the existing plan.md, research.md (R1–R11), data-model.md and the schema, and every one was already covered.

A "User Technical Direction — confirmed 2026-11-12" traceability table was added to plan.md. One nuance is noted: accounts starting with 3 are income, not expense, and are kept mappable as directed. No design changes were made.

## Outcome

- ✅ Impact: The plan is confirmed against the user's direction, with traceability, and no work was lost.
- 🧪 Tests: none (plan)
- 📁 Files: plan.md (traceability section added)
- 🔁 Next prompts: /sp.tasks
- 🧠 Reflection: Re-running a scaffold script on top of approved work would have destroyed it. Checking what the script does before running it prevented that.

## Evaluation notes (flywheel)

- Failure modes observed: setup-plan.ps1 overwrites an existing plan.md without warning (Copy-Item -Force). This is a tooling hazard.
- Graders run and results (PASS/FAIL): directive traceability 14/14 PASS
- Prompt variant (if applicable): re-issued /sp.plan with explicit direction
- Next experiment (smallest change to try): Make setup-plan.ps1 skip the copy when plan.md already exists (separate tooling fix).
