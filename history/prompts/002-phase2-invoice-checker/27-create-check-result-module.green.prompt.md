---
id: 27
title: Create check_result Module and Tests
stage: green
date: 2026-11-24
surface: agent
model: claude-sonnet-4-6
feature: 002-phase2-invoice-checker
branch: main
user: umairbangash11
command: "create phase-2/check_result.py with a function check(answer_text)"
labels: ["phase-2","check_result","validation","vat","json","tests"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - phase-2/check_result.py
  - phase-2/tests/test_check_result.py
tests:
  - phase-2/tests/test_check_result.py::test_autosync_ok
  - phase-2/tests/test_check_result.py::test_autosync_wrong_total
  - phase-2/tests/test_check_result.py::test_invalid_vat_rate
  - phase-2/tests/test_check_result.py::test_broken_json
---

## Prompt

Task: create phase-2/check_result.py with a function check(answer_text).
It should:
1. Remove the ```json marks and turn the text into a Python dictionary.
2. Check that the sum of all lines (net_amount + vat_amount) equals total_amount
   (allow a difference of 0.05 for rounding).
3. Check that every vat_rate in the lines is 0, 12, 15 or 25.
4. Return the dictionary with "check_status": "OK", or "NEEDS REVIEW" plus a
   "check_reason". If the text is not valid JSON, return NEEDS REVIEW instead of crashing.

Tests in phase-2/tests/test_check_result.py:
- AutoSync: total 2179.80, lines 0% 2120.80+0.00 and 25% 47.20+11.80 -> OK
- Same, but total 2100.00 -> NEEDS REVIEW
- A line with vat_rate 11.8 -> NEEDS REVIEW
- Broken text "{ not json" -> NEEDS REVIEW

Rules: don't touch private_samples/, .env or any other file. Don't commit.
Explain each part in one simple sentence.

## Response snapshot

Created `phase-2/check_result.py` with a `check()` function that:
- Strips ```json fences with a regex so raw LLM output is accepted without crashing.
- Validates each line's `vat_rate` against the allowed set {0, 12, 15, 25}.
- Compares the computed line sum against `total_amount` within a 0.05 tolerance.
- Returns the parsed dict with `check_status: "OK"` or `check_status: "NEEDS REVIEW"` plus `check_reason`.
- Catches `json.JSONDecodeError` and returns NEEDS REVIEW instead of raising.

Created `phase-2/tests/test_check_result.py` with four tests covering all specified scenarios.
All 4 tests pass: `4 passed in 0.12s`.

## Outcome

- ✅ Impact: Phase-2 now has a post-processing validation step that catches bad totals, illegal VAT rates, and malformed LLM output.
- 🧪 Tests: 4/4 passed (test_autosync_ok, test_autosync_wrong_total, test_invalid_vat_rate, test_broken_json).
- 📁 Files: phase-2/check_result.py (created), phase-2/tests/test_check_result.py (created).
- 🔁 Next prompts: Wire check() into vision_read.py pipeline; add check_result call in run_agent.py.
- 🧠 Reflection: Keeping VALID_VAT_RATES as a module-level set makes future rate additions a one-line change.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): pytest phase-2/tests/test_check_result.py — PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): integrate check() after vision_read returns JSON
