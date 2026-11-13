---
id: 10
title: Create ledger-mcp server
stage: general
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: none
labels: ["mcp", "ledger", "sqlite", "duplicates", "bokforingsloven", "audit"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .mcp.json
 - .gitignore
 - mcp-servers/ledger-mcp/server.py
 - mcp-servers/ledger-mcp/ledger_store.py
 - mcp-servers/ledger-mcp/requirements.txt
 - mcp-servers/ledger-mcp/README.md
 - mcp-servers/ledger-mcp/tests/test_ledger_mcp.py
tests:
 - mcp-servers/ledger-mcp/tests/test_ledger_mcp.py (17 tests incl. stdio round trip, all pass)
 - full regression: 147 tests across 5 skills + 5 MCP servers pass
---

## Prompt

ledger-mcp — stores booked entries and checks for duplicates.

## Response snapshot

**Storage:** SQLite with amounts stored as integer øre. Database triggers make entries and lines append-only. Booked content is immutable, and an entry's status can change only from booked to reversed, so corrections are made with reverse_entry, which books a mirror entry. Bilag numbers are gapless per year (YYYY-NNNNN) and allocated inside a BEGIN IMMEDIATE transaction. There is an append-only audit log.

**Booking gate:** book_entry requires qa_status == passed, booked_by, balanced lines, a date that isn't in the future, and NOK.

**Duplicate levels:**
- **duplicate**, always refused: the same source file sha256, the same supplier and normalised invoice number, or identical date and lines with no conflicting invoice number.
- **possible_duplicate**: the same supplier and amount within 7 days, identical lines with different invoice numbers, or the same amount and date when the supplier is unknown. It is booked only with allow_possible_duplicate plus an override_reason, which are recorded.
- **previously_reversed**: reported for information only.

**Server:** 8 tools. The write tools are described as needing the user's explicit approval. The server is registered in `.mcp.json` as `ledger`, and `.gitignore` was added for data/ and __pycache__.

## Outcome

- ✅ Impact: Booked entries are stored durably under bookkeeping rules, and duplicates are caught before booking.
- 🧪 Tests: 17 pass. They include the triggers rejecting raw SQL deletes and updates, data surviving a restart, and a stdio round trip. The full regression of 147 tests passes.
- 📁 Files: 5 new files under mcp-servers/ledger-mcp/, .mcp.json updated, .gitignore created
- 🔁 Next prompts: Approve the servers; decide on a backup policy for data/ledger.sqlite; optionally import historical SAF-T invoices (SourceDocumentID) for duplicate checks against bookings made before this system; commit.
- 🧠 Reflection: Enforcing immutability in the database, rather than only in Python, protects the record even from direct SQL access.

## Evaluation notes (flywheel)

- Failure modes observed:
  - Invoice-number normalisation stripped separators before leading zeros, so `2025-0417` ≠ `2025-417`. Fixed by normalising per group.
  - Identical lines with different invoice numbers were a hard duplicate. This was too strict and is now possible_duplicate.
  - Two test expectations were wrong: the per-year number of a reversal dated today, and the order of match reasons.
- Graders run and results (PASS/FAIL): unittest PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Replay a real month of bilag twice through book_qa_file; the second run should refuse 100 %.
