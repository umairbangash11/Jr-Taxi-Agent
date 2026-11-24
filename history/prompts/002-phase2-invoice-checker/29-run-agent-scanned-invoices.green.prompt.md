---
id: 29
title: run_agent Handles Scanned Invoices
stage: green
date: 2026-11-24
surface: agent
model: claude-sonnet-4-6
feature: 002-phase2-invoice-checker
branch: main
user: umairbangash11
command: "change run_agent.py for scanned invoices with vision + check"
labels: ["phase-2","run_agent","vision","check_result","cli"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - phase-2/run_agent.py
tests: []
---

## Prompt

Task: change phase-2/run_agent.py so it works on scanned invoices:
1. Take picture file names from the command line.
2. Read them with read_images() from vision_read.py.
3. Check the answer with check() from check_result.py.
4. Print a clear summary (supplier, invoice, total, lines, check status).
5. If NEEDS REVIEW, print reason and stop.
6. If OK, ask "Approve? (y/n)" and save to booked_entries.json.
Don't change other files. Don't commit. Explain simply.

## Response snapshot

Rewrote `run_agent.py` to:
- Accept image paths from `sys.argv[1:]` and pass them to `read_images()`.
- Pass the returned text to `check()` for validation.
- Print a formatted summary table (supplier, invoice number, date, due date, total, VAT, lines per rate, check status).
- Exit with status 1 and print the reason when `check_status == "NEEDS REVIEW"`.
- Ask for approval and append to `booked_entries.json` when `check_status == "OK"`.

## Outcome

- ✅ Impact: `run_agent.py` is now the end-to-end entry point for the scanned-invoice workflow.
- 🧪 Tests: no automated tests (requires live Groq API + image files); logic covered by existing check_result tests.
- 📁 Files: phase-2/run_agent.py (rewritten).
- 🔁 Next prompts: add error handling for missing GROQ_API_KEY; write integration test with a mock read_images.
- 🧠 Reflection: keeping print_summary() separate from main() makes it easy to test the display logic independently later.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): manual review only
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): mock read_images in a test to exercise the approval flow
