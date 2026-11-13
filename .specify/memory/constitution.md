<!--
Sync Impact Report
==================
Version change: (unversioned template) → 1.0.0
Bump rationale: First ratified constitution; all placeholders replaced (MAJOR baseline 1.0.0).

Principles (template slot → adopted):
  [PRINCIPLE_1] → I. Human-in-the-Loop: Suggest, Never Post
  [PRINCIPLE_2] → II. No Invented Codes (SAF-T Is the Source of Truth)
  [PRINCIPLE_3] → III. Every Entry Balances (Enforced in Code)
  [PRINCIPLE_4] → IV. Bank Account Only Against the Bank Statement
  [PRINCIPLE_5] → V. Fake Data Only
  [PRINCIPLE_6] → removed (user specified exactly five core principles)

Added sections:
  - Technology Stack, Project Structure & Data Handling
  - Development Workflow & Phase Gates (incl. phase exit criteria)
  - Governance

Removed sections: none (template slot 6 dropped as noted above)

Templates:
  ✅ .specify/templates/plan-template.md   — Constitution Check gates filled in; /phase-X structure
  ✅ .specify/templates/tasks-template.md  — tests mandatory per phase; /phase-X path conventions
  ✅ .specify/templates/spec-template.md   — reviewed, no change needed (no conflicting mandates)
  ⚠ .specify/templates/commands/*.md       — directory does not exist; commands live in
                                             .claude/commands/ (no principle references; no change)
  ⚠ CLAUDE.md                              — generic SDD guidance; consistent, no change needed

Follow-up TODOs / conflicts requiring a decision (NOT auto-resolved):
  1. Pre-constitution code exists outside the phase structure:
     .claude/skills/{saft-parser,document-reader,entry-builder,bank-matcher,qa-validator}
     and mcp-servers/{saft,document,bank,reconcile,ledger,filesystem}-mcp. It does not use the
     OpenAI Agents SDK/Groq. Decide: treat as reference prototypes to port phase by phase
     (each through spec → plan → tasks), or archive. Nothing was moved or deleted.
  2. Bank account mismatch: existing code defaults the bank GL account to 1920
     (entry-builder paid_receipt_credit_account, reconcile-mcp RECONCILE_ACCOUNT); Principle IV
     names 1930. Resolve in the Phase 1 spec (account must exist in the SAF-T file).
  3. ledger-mcp "book_entry" stores entries locally after human approval; it does not post to
     JR Taxi. Confirm this matches Principle I's "human approves before saving".
-->

# JR Taxi AI Bookkeeping Agent Constitution

An agent that reads accounting documents and bank statements, suggests JR Taxi journal entries
(bilag), and reconciles ledger against bank. **The agent suggests; a human approves. It never
auto-posts to JR Taxi.**

## Core Principles

### I. Human-in-the-Loop: Suggest, Never Post

- The agent MUST only produce *suggested* entries. A named human MUST explicitly approve each
  entry before it is saved anywhere as booked.
- The system MUST NOT post, push, upload or write entries to JR Taxi's accounting system or any
  external system. Export (Phase 5) produces files for a human to import.
- Approval MUST be recorded with who approved and when; an unapproved suggestion MUST never be
  indistinguishable from an approved entry.
- Every suggestion MUST carry its status: `ready`, `needs review`, or `blocked`, with reasons.

*Rationale:* the bookkeeper is legally responsible for the accounts (bokføringsloven); the agent
is an assistant, and an LLM can be wrong with confidence.

### II. No Invented Codes (SAF-T Is the Source of Truth)

- Account numbers (Konto) and VAT codes (MK) in a suggestion MUST exist in the loaded SAF-T file
  (chart of accounts / tax table), and VAT codes MUST be valid on the entry date.
- This MUST be checked in deterministic code after any LLM step; the LLM's output is a proposal,
  never the authority. A code that fails the check MUST NOT be "corrected" by guessing.
- When a value is uncertain, ambiguous or missing (supplier, account, VAT rate, amount, date),
  the field MUST be left empty and the entry flagged **"needs review"** with candidates and the
  reason. Guessing is a defect.

*Rationale:* an invented or wrong code silently corrupts the ledger and the VAT return.

### III. Every Entry Balances (Enforced in Code)

- For every entry, Σ debet MUST equal Σ kredit, checked in code with exact decimal arithmetic
  (`Decimal` or integer øre — never binary floats for money).
- An unbalanced entry MUST be rejected as `blocked`; it MUST never be shown as ready, approved,
  saved or exported. The check MUST run again at every boundary (suggestion, approval, export).
- Each line MUST have exactly one positive side (debet or kredit), and line totals MUST equal the
  document total.

*Rationale:* balance is the minimum correctness invariant of double-entry bookkeeping.

### IV. Bank Account Only Against the Bank Statement

- A line on the bank account (**1930** for JR Taxi; it MUST exist in the SAF-T file per
  Principle II) MUST only be suggested when the corresponding transaction is present on the
  bank statement.
- The bank line MUST use the bank statement's booking date (posting-date timing). An item paid
  but not yet on the statement MUST NOT be booked to the bank account; it stays on its
  payable/clearing account and is flagged.
- Reconciliation MUST itemise every difference between ledger and bank by bilag and bank line;
  unexplained differences MUST be reported, never netted away.

*Rationale:* the bank account must mirror the bank, or reconciliation becomes meaningless.

### V. Fake Data Only

- The repository MUST contain only fake/sample data: SAF-T files, documents, bank statements,
  fixtures and test data live in `/samples` (or test fixtures) and MUST be synthetic.
- Real client data (JR Taxi or any other client), real org numbers tied to real clients, real
  bank exports and runtime databases MUST NOT be committed; their locations MUST be gitignored.
- Secrets (e.g. `GROQ_API_KEY`) MUST come from environment / `.env` and MUST NOT be committed.
- Real data MUST NOT be sent to an LLM provider unless the user has explicitly approved that for
  the run.

*Rationale:* client accounting data is confidential and personal-data adjacent (GDPR).

## Technology Stack, Project Structure & Data Handling

**Stack (binding):** Python 3.13 · OpenAI Agents SDK · Groq (`llama-3.3-70b`) as the LLM ·
Norwegian SAF-T Financial XML (v1.30) as the data source. Adding a runtime dependency MUST be
justified in the phase plan. Deterministic logic (parsing, validation, balancing, matching) MUST
be plain, testable Python, not prompt behaviour.

**Structure (binding):**

| Path | Contents |
|---|---|
| `/phase-1` | SAF-T reader: accounts, VAT codes, supplier→account map |
| `/phase-2` | Document reader + entry suggester |
| `/phase-3` | Bank matching + reconciliation |
| `/phase-4` | Complex entries (Sentral, Skatteetaten) + guardrails |
| `/phase-5` | Review interface + export |
| `/shared` | Common code, models, config |
| `/tests` | Tests, organised per phase (`/tests/phase-N/`) |
| `/samples` | Fake sample documents and SAF-T |

A phase MUST limit its file changes to its own `/phase-N` folder plus `/shared` and `/tests`
(and `/samples` for new fake data). Specs, plans and tasks live under `specs/` as usual.

## Development Workflow & Phase Gates

- **One phase at a time.** Work MUST NOT start on phase N+1 until phase N's exit criteria are met.
- **No skipped steps.** Each phase MUST go spec → plan → tasks → implement
  (`/sp.specify` → `/sp.plan` → `/sp.tasks` → `/sp.implement`), in that order.
- **Phase exit criteria** (all required):
  1. All tasks in the phase's `tasks.md` are complete.
  2. The phase's tests in `/tests/phase-N/` pass, including tests for Principles II–IV where the
     phase touches them (invented-code rejection, balance enforcement, bank-statement gating).
  3. A human-reviewable output exists (e.g. JSON/CSV/report the user can open and check) and
     the user has reviewed it.
  4. No real data was added to the repository.
- Tests are mandatory for every phase; a phase with failing or missing tests is not complete.
- Changes SHOULD be small and reviewable; unrelated refactors are out of scope for a phase.

## Governance

- This constitution supersedes other practices in this repository. It MUST NOT be re-created;
  changes are made only as amendments via `/sp.constitution`, with the user's approval.
- **Versioning:** MAJOR for removing or redefining a principle or gate; MINOR for a new principle,
  section or materially expanded rule; PATCH for clarifications and wording.
- Each amendment MUST update the Sync Impact Report, bump the version, set Last Amended, and
  propagate to dependent templates.
- **Compliance:** every plan MUST pass the Constitution Check gates in `plan-template.md`; every
  phase completion MUST be checked against the phase exit criteria. A justified exception MUST be
  recorded in the plan's Complexity Tracking table and approved by the user.
- Runtime development guidance for the agent is in `CLAUDE.md`.

**Version**: 1.0.0 | **Ratified**: 2026-11-12 | **Last Amended**: 2026-11-12
