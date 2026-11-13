---
id: 22
title: Gitignore client data before push
stage: general
date: 2026-11-13
surface: agent
model: claude-opus-5-5
feature: none
branch: 001-phase1-saft-reader
user: umairbangash11
command: (free-form request)
labels: ["git", "gitignore", "data-privacy", "client-data"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .gitignore
 - history/prompts/general/22-gitignore-client-data-before-push.general.prompt.md
tests:
 - git check-ignore against 14 hypothetical real-data paths (all BLOCKED)
 - git check-ignore against 4 synthetic fixtures (all included)
 - git add -A --dry-run (100 files, reviewed)
---

## Prompt

I want to push this project to GitHub, but it contains REAL client data 
that must NEVER be committed (real SAF-T files, real.json, client PDFs). 
Before I push:
1. Update .gitignore to exclude ALL real client data (real SAF-T xml 
   files, real output json, all PDFs, .env).
2. Run git status and show me exactly what WOULD be committed.
3. Confirm no real client data is in that list.
Do NOT commit or push yet — just prepare and show me, so I can check first.

## Response snapshot

Rewrote .gitignore as deny-by-default for data types (*.xml, *.csv, *.pdf, images,
*.xlsx, *.db, .env*, real/client JSON, jr_taxi_config.json, data/, clients/) with
explicit re-allows for samples/saft_sample.xml and **/tests/fixtures/*.{xml,csv}.
Verified with git check-ignore; listed 100 would-be-committed files via
`git add -A --dry-run`; scanned them for org numbers, bank accounts, plates and
løyve — all values synthetic (999999999, 911111119-style, 1234.56.78903, EL12345).
No commit or push performed.

## Outcome

- ✅ Impact: Real client data types are blocked from git; synthetic fixtures still tracked.
- 🧪 Tests: check-ignore probes passed (14/14 blocked, 4/4 fixtures included).
- 📁 Files: .gitignore
- 🔁 Next prompts: user reviews list, then commit + push.
- 🧠 Reflection: Deny-by-default + allowlist is safer than enumerating real filenames.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): manual scan PASS
- Prompt variant (if applicable): null
- Next experiment (smallest change to try): add a pre-commit hook rejecting *.xml/*.pdf outside fixtures.
