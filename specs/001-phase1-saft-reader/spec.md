# Feature Specification: Phase 1 — SAF-T Reader

**Feature Branch**: `001-phase1-saft-reader`
**Created**: 2026-11-12
**Status**: Draft
**Input**: User description: "Phase 1 — SAF-T Reader (the agent's 'brain'). Parse a Norwegian SAF-T XML
export and produce structured data the rest of the agent will use: accounts (ID + description),
VAT/MVA codes (code + percentage), suppliers (name + ID), and a supplier→account mapping learned from
past GeneralLedgerEntries. Output one clean JSON file in /phase-1 (saft_data.json). Handle the SAF-T
namespace correctly, use a fake sample SAF-T file in /samples, record missing or ambiguous fields as
'unknown' — do not guess. Exit: the reader produces correct JSON with all four sections populated from the
sample file, and a test confirms the supplier→account map is built correctly."

**Constitution**: v1.0.0 — Phase 1 of 5. Work limited to `/phase-1`, `/shared`, `/tests`, `/samples`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Turn a SAF-T export into the agent's reference data (Priority: P1)

The bookkeeper has a SAF-T export from JR Taxi's accounting system. They run the reader on it and
get one reference file containing the chart of accounts, the VAT codes, the suppliers, and which
account each supplier is normally booked to. Every later phase (entry suggestions, bank matching,
reconciliation) uses this file as its only source of valid codes.

**Why this priority**: Without this, the agent has no list of real account/VAT codes and would have
to invent them, which the constitution forbids (Principle II). Everything else depends on it.

**Independent Test**: Run the reader on the sample SAF-T file in `/samples` and open the produced
file: all four sections are present and contain exactly the accounts, codes, suppliers and mappings
that are in the sample.

**Acceptance Scenarios**:

1. **Given** the sample SAF-T file, **When** the reader runs, **Then** a reference file is saved in
   `/phase-1` with four populated sections: accounts, vat_codes, suppliers, supplier_account_map.
2. **Given** the sample contains account 7026 "Reparasjoner", **When** the reader runs, **Then** the
   accounts section contains ID `7026` with description `Reparasjoner`, unchanged.
3. **Given** the sample's tax table defines code `2` at 25 % and code `12` at 12 %, **When** the reader
   runs, **Then** vat_codes lists `2 → 25` and `12 → 12`.
4. **Given** the sample lists supplier "NIO" with an ID, **When** the reader runs, **Then** suppliers
   contains that ID and the name exactly as written in the file.

---

### User Story 2 - Learn which account each supplier is booked to (Priority: P1)

From the supplier invoices already booked in the SAF-T file, the reader learns the usual cost
account per supplier (e.g. NIO → 7033, ONEPARK → 7161, RA FORSIKRING → 7027), so Phase 2 can suggest
the right account for a new invoice from the same supplier.

**Why this priority**: This mapping is the main value the "brain" adds beyond copying master data,
and it is an explicit exit criterion.

**Independent Test**: A test runs the reader on the sample file and checks each supplier's mapped
account against the bookings written into the sample, including a supplier with mixed history
(must be `unknown`) and a supplier with no history (must be `unknown`).

**Acceptance Scenarios**:

1. **Given** NIO's invoices in the sample are all booked to 7033, **When** the reader runs, **Then**
   supplier_account_map maps NIO → `7033`.
2. **Given** a supplier's invoice is booked with lines on 7033, 2710 (input VAT) and 2400 (payable),
   and a later payment from 1930, **When** the map is built, **Then** only `7033` counts; VAT,
   payable and bank lines are never mapped as the supplier's account.
3. **Given** a supplier whose invoices are split across several cost accounts with no clear
   dominant one, **When** the map is built, **Then** the account is `unknown` and the candidate
   accounts with their counts are listed so a human can decide.
4. **Given** a supplier listed in the master data but never booked, **When** the map is built,
   **Then** the account is `unknown` with the reason "no booking history".

---

### User Story 3 - See clearly what the reader could not determine (Priority: P2)

When something in the file is missing or unclear (an account without a description, a VAT code
without a percentage, a supplier without a name, entries pointing at a supplier not in the master
data), the bookkeeper sees it marked `unknown` with a reason, plus a short summary of how many such
cases exist, instead of a silently guessed value.

**Why this priority**: Makes the output trustworthy and reviewable (constitution: human-reviewable
output, no guessing), but the reader is usable without the summary.

**Independent Test**: Run the reader on a sample containing deliberately incomplete records and
check every gap appears as `unknown` with a reason and is counted in the summary.

**Acceptance Scenarios**:

1. **Given** an account without a description, **When** the reader runs, **Then** its description is
   `unknown` and the summary counts it.
2. **Given** a tax code without a percentage, **When** the reader runs, **Then** its percentage is
   `unknown` (not 0).
3. **Given** the file is not a Norwegian SAF-T file (wrong root element or namespace), **When** the
   reader runs, **Then** it stops with a clear error and writes no reference file.

---

### Edge Cases

- **Namespace variants**: the SAF-T namespace may be the default namespace or bound to any prefix
  (`n1:`, `ns0:`); results MUST be identical.
- **Wrong file**: a different XML (other country's SAF-T, other namespace, not XML) → clear error,
  no output file, previous output not overwritten with partial data.
- **Version**: a SAF-T version other than 1.30 → processed, with a warning in the summary.
- **"Blank" VAT**: booking lines with no VAT code mean 0 % (no VAT) → represented as one explicit
  "no VAT code" entry at 0 %, distinct from a defined code whose percentage is missing (`unknown`).
- **Same code, several periods**: a tax code with different percentages over time → all variants
  kept with their validity dates; never collapsed to one guessed value.
- **Supplier IDs in entries but not in master data** → mapping still built under that ID, name
  `unknown`, counted in the summary.
- **Payments and credit notes**: transactions where the supplier's payable is debited (payments,
  credit notes) MUST NOT teach the map (they would map the supplier to the bank account).
- **Large files**: a full-year export with tens of thousands of entries MUST be readable.
- **Norwegian characters** (æ, ø, å) in names and descriptions MUST be preserved exactly.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The reader MUST accept a SAF-T Financial XML file and verify it is a Norwegian SAF-T
  file (root element and Norwegian SAF-T namespace); otherwise it MUST stop with a clear error and
  produce no output.
- **FR-002**: The reader MUST resolve the SAF-T namespace regardless of prefix, so that the same file
  written with a default namespace or any prefix yields identical output.
- **FR-003**: The reader MUST extract every general-ledger account with its ID and description,
  exactly as written in the file.
- **FR-004**: The reader MUST extract every VAT/MVA code in the tax table with its code and
  percentage, plus its description and validity dates when present; a code without a percentage
  MUST have percentage `unknown`.
- **FR-005**: The reader MUST include one explicit entry for "no VAT code" (blank) with 0 %, used for
  booking lines that carry no VAT code.
- **FR-006**: The reader MUST extract every supplier with its ID and name, exactly as written; a
  missing name MUST be `unknown`.
- **FR-007**: The reader MUST build the supplier→account map from past general-ledger entries, using
  only supplier **invoices** (transactions where the supplier's payable is credited) and only the
  **cost/income accounts** on those invoices. Balance-sheet lines — bank (e.g. 1930), payable
  (e.g. 2400), VAT (e.g. 27xx) — MUST NOT be mapped.
- **FR-008**: For each supplier, the map MUST record the chosen account, how many invoices support it,
  and all candidate accounts with their counts. The chosen account MUST be the supplier's account
  only when it is used on at least 80 % of that supplier's invoices (clarified 2026-11-12, see
  Clarifications); otherwise it MUST be `unknown` with reason "ambiguous history" and the
  candidates listed.
- **FR-009**: A supplier with no booked invoices MUST be in the map with account `unknown` and reason
  "no booking history".
- **FR-010**: Any value the reader cannot determine MUST be recorded as the literal `unknown`, with a
  reason where one applies. The reader MUST NOT fill gaps with guessed or default values (except the
  explicit 0 % "no VAT code" entry in FR-005).
- **FR-011**: The reader MUST save one reference file `saft_data.json` in `/phase-1` with the four
  sections `accounts`, `vat_codes`, `suppliers`, `supplier_account_map`, plus a `summary` (source
  file name, SAF-T version, company, period, counts, number of `unknown` values per section,
  warnings).
- **FR-012**: The reference file MUST be human-reviewable: readable text, Norwegian characters intact,
  stable ordering (accounts and codes by ID, suppliers by ID) so two runs on the same file produce
  identical output.
- **FR-013**: A fake sample SAF-T file MUST be provided in `/samples`, containing only invented data,
  and covering at least: the example accounts (1930, 2400, 27xx VAT, 7026, 7027, 7033, 7155, 7161),
  the example VAT codes (2 = 25 %, 12 = 12 %), the example suppliers (NIO, ONEPARK, RA FORSIKRING),
  one supplier with ambiguous history, one supplier with no history, a payment transaction, and at
  least one deliberately incomplete record.
- **FR-014**: Automated tests in `/tests/phase-1/` MUST confirm the supplier→account map for the sample
  (including the ambiguous and no-history cases and that bank/VAT/payable accounts are never mapped),
  and MUST confirm all four sections are populated.
- **FR-015**: The reader MUST NOT call any external service or LLM; it is deterministic.

### Key Entities

- **Account**: a general-ledger account — ID (e.g. `7026`), description (e.g. `Reparasjoner`).
- **VAT code**: a code from the tax table — code (e.g. `2`), percentage (e.g. `25`) or `unknown`,
  description, validity period; plus the explicit "no VAT code" entry at 0 %.
- **Supplier**: ID and name (or `unknown`), as in the master data.
- **Supplier→account mapping**: per supplier — chosen account or `unknown`, support count, candidate
  accounts with counts, reason when `unknown`.
- **Summary**: source file, SAF-T version, company, period, counts per section, `unknown` counts,
  warnings.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Running the reader on the sample file produces a reference file in which all four
  sections are non-empty and 100 % of the accounts, VAT codes and suppliers in the sample appear,
  with values identical to the sample.
- **SC-002**: For the sample, 100 % of supplier→account mappings match the expected mapping written
  in the test (e.g. NIO → 7033, ONEPARK → 7161, RA FORSIKRING → 7027; ambiguous and no-history
  suppliers → `unknown`), and 0 bank, payable or VAT accounts appear as mapped accounts.
- **SC-003**: 0 guessed values: every deliberately incomplete record in the sample appears as
  `unknown` and is counted in the summary.
- **SC-004**: The same sample written with a different namespace prefix yields byte-identical
  reference content (apart from the source file name).
- **SC-005**: A full-year export with 50 000 booking lines is processed in under 30 seconds on a
  normal office laptop.
- **SC-006**: A bookkeeper can open the reference file and verify any supplier's mapping against
  its candidate counts in under 1 minute, without other tools.

## Assumptions

- The SAF-T files are Norwegian SAF-T Financial, version 1.30 (the current mandatory version);
  other versions are processed with a warning.
- Suppliers are identified in booking lines by their supplier ID (standard in SAF-T 1.30). Bookings
  that name a supplier only in free text are not used for the map (guessing from text is out of
  scope).
- "Cost/income accounts" means profit-and-loss accounts (Norwegian standard chart classes 3–8);
  classes 1–2 (assets, liabilities incl. bank, payable and VAT) are never mapped.
- The VAT codes in the examples (2 = 25 %, 12 = 12 %) are JR Taxi's own codes as written in its
  SAF-T tax table; the reader reports codes exactly as found, without translating them.
- JR Taxi's bank account is 1930 (consistent with constitution Principle IV); Phase 1 only reads it.
- The output file is regenerated in full on each run; it is a derived artefact of the sample.

## Out of Scope

- Reading invoices/receipts, suggesting entries (Phase 2), bank matching and reconciliation
  (Phase 3), complex entries (Phase 4), review interface and export (Phase 5).
- Any LLM or agent behaviour; Phase 1 is deterministic parsing.
- Reading real client SAF-T files into the repository (constitution Principle V).

## Clarifications

### Session 2026-11-12

- Q: When is a supplier's history clear enough to choose an account? → A: When one cost account is
  used on **at least 80 %** of the supplier's invoices (user choice). Below that → `unknown`,
  reason "ambiguous history", candidates with counts listed. Applied in FR-008.
