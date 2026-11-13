---
id: 3
title: Create entry builder skill
stage: general
date: 2026-11-10
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: none
labels: ["skill", "bookkeeping", "journal-entry", "mva", "jr-taxi"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .claude/skills/entry-builder/SKILL.md
 - .claude/skills/entry-builder/config.example.json
 - .claude/skills/entry-builder/scripts/build_entry.py
 - .claude/skills/entry-builder/tests/test_build_entry.py
 - .claude/skills/entry-builder/tests/fixtures/saft.json
 - .claude/skills/entry-builder/tests/fixtures/config.json
tests:
 - .claude/skills/entry-builder/tests/test_build_entry.py (17 tests, all pass)
---

## Prompt

Create a skill named "entry-builder".
Purpose: Build a balanced JR Taxi journal entry (bilag) from extracted document data
and the supplier→account mapping. Outputs lines with Konto, MK (VAT code), Debet,
Kredit, Løyve, Bil. Enforces debit = credit. Marks mixed/complex documents for human review.

## Response snapshot

Asked 3 clarifying questions. The user chose gross amount + MK with no separate 2710 line, a kvittering credit account set in config with default 1920, and Løyve/Bil taken from a config map matched against the document text, otherwise left empty and flagged. Built `build_entry.py`. It matches the supplier by org number, then name. It takes the expense account from SAF-T history, ignoring 27xx, with a 60 % share threshold. It maps the rate to an input-VAT MK through SAF-T standard codes and cross-checks it against supplier history. It enforces debet = kredit in exact decimals. Each bilag gets status ready, needs_review or blocked. Mixed VAT, an unclear total or type, a credit note, a split that doesn't match the total, and an imbalance all block. Review covers missing data, currency other than NOK, amounts ≥ 30 000 (possible fixed asset) and MK deviation. CLI overrides and `--line` splits support human resolution. Output is JSON plus semicolon CSV.

## Outcome

- ✅ Impact: The pipeline now goes from SAF-T and document to balanced bilag lines.
- 🧪 Tests: 17 pass, including an end-to-end run from the document-reader fixture.
- 📁 Files: 6 new files under .claude/skills/entry-builder/
- 🔁 Next prompts: Fill jr_taxi_config.json with real løyver/biler; confirm CSV import format for JR Taxi's accounting system.
- 🧠 Reflection: The posting convention and the credit account for receipts were real business decisions, so asking first was justified.

## Evaluation notes (flywheel)

- Failure modes observed: In the draft, the kvittering path cleared the header supplier ID and the description builder could throw an IndexError. Both were fixed before the tests ran.
- Graders run and results (PASS/FAIL): unittest PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Run on real JR Taxi bilag with the real SAF-T export and compare against what was actually posted.
