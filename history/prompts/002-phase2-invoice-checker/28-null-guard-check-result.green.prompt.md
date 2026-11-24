---
id: 28
title: Null Guard in check_result
stage: green
date: 2026-11-24
surface: agent
model: claude-sonnet-4-6
feature: 002-phase2-invoice-checker
branch: main
user: umairbangash11
command: "add null/missing guard to check_result.py"
labels: ["phase-2","check_result","null-guard","robustness"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - phase-2/check_result.py
  - phase-2/tests/test_check_result.py
tests:
  - phase-2/tests/test_check_result.py::test_null_total_amount
---

## Prompt

In phase-2/check_result.py, if total_amount, net_amount or vat_amount is null
or missing, check() must return NEEDS REVIEW with a clear reason instead of crashing.
Add a test in test_check_result.py where total_amount is null.
Don't change anything else. Explain the change simply.

## Response snapshot

Added two guards in `check_result.py`:
1. Before processing lines: if `total_amount` is `None` or absent, return NEEDS REVIEW immediately with reason "total_amount is null or missing".
2. Before the arithmetic loop: for each line, if `net_amount` or `vat_amount` is `None` or absent, return NEEDS REVIEW with the field name and line index.

Also replaced the `float(line.get(..., 0))` default-to-zero pattern with direct `float(line[field])` after the null check, so a genuinely missing field is caught rather than silently treated as zero.

Added `test_null_total_amount` to the test file. All 5 tests pass.

## Outcome

- ✅ Impact: check() no longer crashes or silently miscalculates when the LLM omits or nulls a required amount field.
- 🧪 Tests: 5/5 passed.
- 📁 Files: phase-2/check_result.py (modified), phase-2/tests/test_check_result.py (modified).
- 🔁 Next prompts: Wire check() into vision_read.py pipeline.
- 🧠 Reflection: Checking for None explicitly (not just falsiness) keeps 0.00 valid amounts working correctly.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): pytest phase-2/tests/test_check_result.py — PASS (5/5)
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): integrate check() after vision_read returns JSON
