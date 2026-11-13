---
id: 12
title: Ratify JR Taxi agent constitution
stage: constitution
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: /sp.constitution
labels: ["constitution", "governance", "phases", "human-in-the-loop", "saft"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .specify/memory/constitution.md
 - .specify/templates/plan-template.md
 - .specify/templates/tasks-template.md
tests:
 - none (governance document; placeholder validation passed)
---

## Prompt

/sp.constitution

Project: AI Bookkeeping Agent for Norwegian Taxi Accounting (JR Taxi)

PURPOSE
Build an agent that reads accounting documents and bank statements, 
suggests JR Taxi journal entries, and reconciles ledger vs bank. 
The agent SUGGESTS; a human approves. It never auto-posts to JR Taxi.

TECH STACK
- Python 3.13, OpenAI Agents SDK, Groq (llama-3.3-70b)
- Data source: Norwegian SAF-T XML export

CORE PRINCIPLES (non-negotiable)
1. Human-in-the-loop: agent only suggests; human approves before saving.
2. No invented codes: only account/VAT codes present in the SAF-T file. 
   If unsure, flag "needs review".
3. Every entry must balance: debit = credit, enforced in code.
4. Book to 1930 only when the item is on the bank statement (respect 
   posting-date timing).
5. Fake/sample data only. No real client data in the repo.

PROJECT STRUCTURE
/phase-1  SAF-T reader (parse SAF-T → accounts, VAT codes, supplier→account map)
/phase-2  Document reader + entry suggester
/phase-3  Bank matching + reconciliation
/phase-4  Complex entries (Sentral, Skatteetaten) + guardrails
/phase-5  Review interface + export
/shared   common code, models, config
/tests    tests per phase
/samples  fake sample documents and SAF-T

PHASES: 5 total. Each phase has its own folder.

ENFORCEMENT RULES
- Work on ONE phase at a time. Do not start a phase before the previous 
  phase's exit criteria are met.
- Do not skip steps (spec → plan → tasks → implement per phase).
- Do not re-create this constitution.
- Every phase ends with tests passing and a human-reviewable output.
- Each phase must limit its file changes to its own /phase-X folder 
  (plus /shared and /tests).

Generate the constitution following these rules.

## Response snapshot

Wrote `.specify/memory/constitution.md` v1.0.0 (ratified 2026-11-12) with the 5 principles as stated. The template's sixth principle slot was dropped because the user specified five. Each principle has MUST rules and a rationale. II and III are explicitly enforced in deterministic code after any LLM step, and III uses exact decimal or øre arithmetic. IV uses 1930 with bank booking-date timing and itemised, never netted, reconciliation.

New sections: Stack/Structure/Data Handling (binding stack and folder table), Workflow and Phase Gates (four explicit exit criteria) and Governance (amend only, never re-create; semver; compliance gates).

Template propagation:
- **plan-template:** concrete Constitution Check gates and the /phase-N layout.
- **tasks-template:** tests made mandatory, replacing "Tests are OPTIONAL"; /phase-N path conventions.
- **spec-template:** reviewed, unchanged.

The Sync Impact Report flags three unresolved conflicts with the pre-existing code: the skills and MCP servers sit outside the phase folders and don't use the Agents SDK or Groq; they default the bank account to 1920 while the constitution says 1930; and ledger-mcp's booking semantics need confirming against Principle I. Nothing was moved or deleted.

## Outcome

- ✅ Impact: The project now has binding governance. Every /sp.plan is gated on the five principles and the phase rules.
- 🧪 Tests: none (document); validation found no unresolved placeholders, ISO dates and a matching version line.
- 📁 Files: constitution.md written; plan-template.md and tasks-template.md updated
- 🔁 Next prompts: Decide what happens to the pre-constitution code (port or archive); `/sp.specify` for Phase 1 (SAF-T reader), resolving 1920 vs 1930.
- 🧠 Reflection: The user's rules conflict with code built earlier in this session. Surfacing that conflict, instead of moving code, respects both "one phase at a time" and "spec before implement".

## Evaluation notes (flywheel)

- Failure modes observed: The create-phr.sh script is absent (only .specify/scripts/powershell exists), so the PHR was written with agent-native tools.
- Graders run and results (PASS/FAIL): placeholder scan PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Run /sp.specify for Phase 1 and check that the Constitution Check gates are usable as written.
