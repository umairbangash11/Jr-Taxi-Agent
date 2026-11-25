---
id: 27
title: SAFT Lookup and Suggest Entry After Check OK
stage: green
date: 2026-11-25
surface: agent
model: claude-sonnet-4-6
feature: none
branch: main
user: umairbangash11
command: pasted instruction
labels: ["phase-2","saft","suggest-entry","accounting","tests"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - phase-2/suggest_entry.py
  - phase-2/run_agent.py
  - phase-2/tests/test_suggest_entry.py
tests:
  - phase-2/tests/test_suggest_entry.py (8 tests, all PASSED)
---

## Prompt

In phase-2/run_agent.py, after the check step says OK:
1. Load a saft_data JSON file (path given with --saft, default phase-1/saft_data.json).
2. Find the supplier by matching the vendor name to supplier_name (case-insensitive, partial match).
3. For each invoice line, look up supplier_vat_account_map by supplier_id + VAT code
   (VAT rate 25 -> MK "2", 0 -> MK "" ).
4. Show the suggested entry: Konto (with account name), MK, Debet, and Kredit = supplier_id.
5. If the supplier or any account is unknown, show NEEDS REVIEW for that line.
Add tests in phase-2/tests using demo data only.

## Response snapshot

Created `phase-2/suggest_entry.py` with:
- `load_saft(path)` — loads SAFT JSON (defaults to phase-1/saft_data.json)
- `suggest(result, saft_data)` — returns list of journal entry rows; marks unknown supplier/account/VAT as needs_review
- `print_suggested_entries(rows)` — tabular display with NEEDS REVIEW annotation

Updated `phase-2/run_agent.py`:
- Switched from raw `sys.argv` to `argparse` with positional `images` and optional `--saft`
- After check OK: loads SAFT, calls `suggest`, prints entries, exits 1 if any line needs review

Added `phase-2/tests/test_suggest_entry.py` with 8 tests covering: VAT 25/0, unknown supplier, ambiguous account, unknown VAT rate, partial name match, multiple lines, empty vendor.

## Outcome

- ✅ Impact: run_agent.py now shows suggested journal entries sourced from SAFT history after every clean check
- 🧪 Tests: 8/8 new tests PASSED; 5/5 existing check_result tests still PASSED
- 📁 Files: phase-2/suggest_entry.py (new), phase-2/run_agent.py (updated), phase-2/tests/test_suggest_entry.py (new)
- 🔁 Next prompts: wire Kredit to 2400 account line; handle VAT debet line (2710); prompt user to approve or edit before booking
- 🧠 Reflection: keeping suggest logic in its own module makes it independently testable with zero I/O

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): pytest phase-2/tests/test_suggest_entry.py — PASS (8/8)
- Prompt variant (if applicable): none
- Next experiment: add VAT debet row (2710) to the suggested entry display
