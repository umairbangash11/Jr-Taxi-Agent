---
id: 17
title: How to run Phase 1
stage: explainer
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: 001-phase1-saft-reader
branch: 001-phase1-saft-reader
user: umairbangash11
command: none
labels: ["explainer", "phase-1", "how-to"]
links:
  spec: specs/001-phase1-saft-reader/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - none
tests:
 - none
---

## Prompt

how can i run phase 1?

## Response snapshot

I explained that Phase 1 is not implemented yet: no tasks.md exists, and /phase-1, /samples and /tests/phase-1 don't exist. The steps are to run /sp.tasks, review the list, then run /sp.implement. Once it is built, these commands run it (from quickstart.md and contracts/cli.md):
- `python phase-1/saft_reader.py samples/saft_sample.xml`, which writes phase-1/saft_data.json
- `python -m pytest tests/phase-1 -v`

I also mentioned that the pre-constitution saft-parser skill can be run today, but it follows different rules and is not Phase 1.

## Outcome

- ✅ Impact: The user knows where the work stands and the exact commands to use once it is built.
- 🧪 Tests: none
- 📁 Files: none
- 🔁 Next prompts: /sp.tasks
- 🧠 Reflection: none

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): n/a
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
