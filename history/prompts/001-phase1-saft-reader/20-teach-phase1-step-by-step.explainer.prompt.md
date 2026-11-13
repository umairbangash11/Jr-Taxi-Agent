---
id: 20
title: Teach Phase 1 step by step
stage: explainer
date: 2026-11-13
surface: agent
model: claude-opus-5-5
feature: 001-phase1-saft-reader
branch: 001-phase1-saft-reader
user: umairbangash11
command: (free text)
labels: ["explainer", "phase-1", "learning", "interview-prep"]
links:
  spec: specs/001-phase1-saft-reader/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - (none modified; teaching only)
tests:
 - (none run)
---

## Prompt

I need to deeply understand Phase 1 (phase-1/saft_reader.py) because I 
have to explain this project in job interviews. I'm a beginner, so teach 
me step by step, in simple plain English, and wait for me to say "next" 
after each part.

Teach me in this order:

1. THE BIG PICTURE: What does phase-1/saft_reader.py do overall? What does 
   it read, what does it decide, and what does it output? No code yet — 
   just the idea in simple words.

2. ONE REAL EXAMPLE: Using samples/saft_sample.xml, walk me through exactly 
   how NIO gets mapped to account 7033. Show its invoices, the counting, 
   and why 80% matters. Explain why the payment line and the 2710 VAT line 
   are NOT counted.

3. THE MAIN FUNCTION: Explain read_saft() line by line in plain English. 
   Explain why it uses streaming (iterparse + clear()) and how it checks 
   the SAF-T namespace.

4. THE 80% LOGIC: Explain decide_mapping(). List the 4 reasons a supplier 
   becomes "unknown", with one simple example of each.

5. THE DATA SHAPES: Explain shared/models.py — the 5 data shapes and why 
   the code uses "unknown" instead of null/None.

Rules for teaching me:
- Use simple words, like explaining to a beginner.
- After each of the 5 parts, STOP and wait for me to say "next".
- If I say "I don't understand", explain that part again a different, 
  simpler way.
- At the very end, give me a 60-second "interview pitch" I can memorize 
  that summarizes the whole project.

Start with part 1 now.

## Response snapshot

Taught Part 1 (big picture) only, without code. The idea is a new bookkeeper reading a company's old books. INPUT is a SAF-T XML file. It READS 3 lists: accounts, VAT codes and suppliers. It DECIDES supplier → usual account from past invoices, using the ≥ 80 % rule, and writes "unknown" otherwise. OUTPUT is phase-1/saft_data.json (10 accounts, 6 VAT codes, 8 suppliers, 4 mapped / 4 unknown). Explained why this phase matters for later ones (Principle 2: no invented codes). Stopped and waited for "next".

## Outcome

- ✅ Impact: Part 1 of 5 delivered; the tutoring session is in progress.
- 🧪 Tests: none
- 📁 Files: this PHR only
- 🔁 Next prompts: the user says "next", then Part 2 (the NIO → 7033 walkthrough)
- 🧠 Reflection: An analogy first, then the real numbers from the output, keeps it concrete for a beginner.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): n/a
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): n/a
