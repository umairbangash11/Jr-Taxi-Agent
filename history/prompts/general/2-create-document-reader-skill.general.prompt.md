---
id: 2
title: Create document reader skill
stage: general
date: 2026-11-10
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: none
labels: ["skill", "ocr", "pdf", "invoice", "receipt", "mva"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .claude/skills/document-reader/SKILL.md
 - .claude/skills/document-reader/scripts/read_document.py
 - .claude/skills/document-reader/tests/test_read_document.py
 - .claude/skills/document-reader/tests/fixtures/faktura.txt
 - .claude/skills/document-reader/tests/fixtures/kvittering.txt
 - .claude/skills/document-reader/tests/fixtures/uklar.txt
tests:
 - .claude/skills/document-reader/tests/test_read_document.py (16 tests, all pass)
---

## Prompt

Create a skill named "document-reader".
Purpose: Read accounting documents (PDF invoices and receipts) and extract
key fields: vendor name, date, total amount, VAT rate, invoice number, document type
(faktura vs kvittering). Uses OCR/text extraction. Flags unclear or missing fields
instead of guessing.

## Response snapshot

Created `.claude/skills/document-reader/`. The extractor tries optional backends in order: pdfplumber → pypdf → pdftotext → Tesseract OCR. If none produces text, it returns status `needs_ocr`, and SKILL.md tells Claude to transcribe the page visually and re-run the script with `--text-file`. Field rules are deterministic and cover Norwegian and English labels. Every field has a value, a status of ok/unclear/missing, a confidence, the evidence line, candidates and a reason. Conflicts produce `unclear` with candidates and are never guessed. The vendor org number is checked with mod-11, buyer address blocks are excluded, due dates are excluded from the date, VAT and discount lines are excluded from the total, and an OCR source caps confidence at medium. Nothing was installed. The only backend present in this environment is the pdftotext CLI.

## Outcome

- ✅ Impact: The new document-reader skill extracts invoice and receipt fields and flags them explicitly when unsure.
- 🧪 Tests: 16 unittest cases pass. They include an end-to-end run on a generated PDF through pdftotext, the needs_ocr path, and the no-guessing cases.
- 📁 Files: 6 new files under .claude/skills/document-reader/
- 🔁 Next prompts: Test on real bilag from the user's taxi business; decide whether to install pdfplumber/pytesseract (+ nor traineddata).
- 🧠 Reflection: Vendor detection is the weakest heuristic. Layouts without a legal suffix or org number always come back unclear, which is the intended behaviour.

## Evaluation notes (flywheel)

- Failure modes observed: none in tests; real-world layouts not yet tested.
- Graders run and results (PASS/FAIL): unittest PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Run on 10–20 real invoices and receipts and measure the share of `ok` fields compared with manual reading.
