---
description: "Task list for Phase 1 — SAF-T Reader"
---

# Tasks: Phase 1 — SAF-T Reader

**Input**: Design documents from `/specs/001-phase1-saft-reader/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: MANDATORY — spec FR-014 and constitution v1.0.0 (phase exit criteria). Tests are written
first in each story and MUST fail before the implementation tasks of that story.

**Organization**: by user story (spec.md): US1 reference data (P1), US2 supplier→account map (P1),
US3 visible unknowns (P2).

**Scope rule**: every file path below is inside `/phase-1`, `/shared`, `/tests` or `/samples`.
Standard library only (pytest is the already-installed test runner). No LLM. Do NOT start project
Phase 2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3

## Path Conventions

`phase-1/saft_reader.py` (all reader logic), `shared/models.py` (dataclasses), `tests/conftest.py`,
`tests/phase-1/test_*.py`, `samples/saft_sample.xml`, output `phase-1/saft_data.json`.

---

## Phase 1: Setup

**Purpose**: folders and test wiring

- [X] T001 Create folders `phase-1/`, `shared/`, `tests/phase-1/`, `samples/` and an empty `shared/__init__.py` (no `__init__.py` in `tests/phase-1/`; folder names with `-` are not packages)
- [X] T002 [P] Create `tests/conftest.py` that inserts the repo root and `<repo>/phase-1` at the front of `sys.path`, and defines fixtures `sample_path` (→ `samples/saft_sample.xml`) and `out_path` (→ `tmp_path / "saft_data.json"`)

---

## Phase 2: Foundational (blocks all user stories)

- [X] T003 [P] Create `shared/models.py`: constant `UNKNOWN = "unknown"`; frozen dataclasses `Account(id, description, standard_account_id)`, `VatCode(code, percentage, description, standard_tax_code, effective_date, expiration_date, source)`, `Supplier(id, name, registration_number, in_master_data)`, `Candidate(account_id, account_description, invoice_count, share)`, `SupplierAccountMapping(supplier_id, supplier_name, account_id, account_description, share, invoice_count, candidates, reason, vat_codes_seen)`; each with `to_dict()` returning the exact keys of `contracts/saft_data.schema.json` (percentage/share as `int` when whole, else `float`; `candidates` as list of dicts). Fields typed `str | <type>` where `"unknown"` is allowed
- [X] T004 [P] Create the fake sample `samples/saft_sample.xml` — Norwegian SAF-T 1.30, namespace `urn:StandardAuditFile-Taxation-Financial:NO` bound to prefix `n1:`, invented company "Testtaxi Demo AS" (org 999999999), period 2025-01..2025-12. It MUST contain exactly:
  - **Accounts**: 1930 Bedriftskonto · 2400 Leverandørgjeld · 2710 Inngående merverdiavgift · 3000 Salgsinntekt · 7026 Reparasjoner · 7027 Forsikring · 7033 Drivstoff · 7155 Bespisning/Mat · 7161 Parkering · 7770 **with no AccountDescription** · one `Account` **without AccountID** (to be skipped)
  - **Tax table (TaxType MVA)**: code `2` = 25 (StandardTaxCode 1) · code `11` = 15 (StandardTaxCode 11) · code `12` = 10 with EffectiveDate 2020-04-01 / ExpirationDate 2021-09-30 · code `12` = 12 with EffectiveDate 2021-10-01 (StandardTaxCode 13) · code `99` **without TaxPercentage**
  - **Suppliers**: 50001 NIO · 50002 ONEPARK · 50003 RA FORSIKRING · 50004 AMBI SERVICE · 50005 SPLITT AS · 50006 NEVER BOOKED AS · 50007 **without Name** (all with fake org numbers except 50007)
  - **Transactions** (supplier lines carry `SupplierID`; amounts are invented; each balanced):
    - NIO: 5 invoices — 4× debit 7033 (MK 2) + debit 2710 / credit 2400; 1× debit 7026 (MK 2) + 2710 / credit 2400 → **7033 at exactly 80 %**
    - NIO: 1 payment — debit 2400 (SupplierID 50001) / credit 1930
    - ONEPARK: 3 invoices — debit 7161 / credit 2400; one of them has **no TaxInformation** (blank VAT), the others MK 2
    - RA FORSIKRING: 2 invoices — debit 7027, no TaxInformation / credit 2400
    - AMBI SERVICE: 3 invoices — 7026, 7026, 7155 → 67 % → ambiguous
    - SPLITT AS: 2 invoices, each with lines on both 7026 and 7155 → multiple accounts
    - Supplier 50099 (**not in master data**): 1 invoice — debit 7026 / credit 2400
    - One netting transaction naming both 50001 and 50002 (must not count for either)
    - One sales transaction — debit 1930 / credit 3000, no supplier

**Checkpoint**: models and sample exist; stories can start.

---

## Phase 3: User Story 1 — Reference data from SAF-T (Priority: P1) 🎯 MVP

**Goal**: accounts, VAT codes, suppliers and the summary header are extracted correctly and written as
`saft_data.json` via the command line.

**Independent Test**: run `python phase-1/saft_reader.py samples/saft_sample.xml -o <tmp>` and check
`accounts`, `vat_codes`, `suppliers` against the sample.

### Tests for User Story 1 (write first, must fail)

- [X] T005 [P] [US1] Create `tests/phase-1/test_sections.py`: `read_saft(sample)` returns all five top-level keys; `accounts` contains `7026 → Reparasjoner`, `7155 → Bespisning/Mat`, `1930 → Bedriftskonto` exactly (æøå intact), sorted numeric-aware; the ID-less account is absent and listed in `summary.skipped`; `vat_codes[0]` is the implicit blank entry (`code ""`, `percentage 0`, `source "implicit"`); code `2` → 25 and both code-`12` variants (10 until 2021-09-30, 12 from 2021-10-01) present, ordered by effective date; `suppliers` contains `50001 → NIO`, `50002 → ONEPARK`, `50003 → RA FORSIKRING`; `summary.saft_version == "1.30"` and company name "Testtaxi Demo AS"
- [X] T006 [P] [US1] Create `tests/phase-1/test_namespace_and_errors.py`: (a) the sample rewritten in `tmp_path` with a default namespace (no prefix) and with prefix `ns0:` gives output equal to the original except `summary.source_file`; (b) a file with namespace `urn:OECD:StandardAuditFile-Tax:PT_1.04_01` raises `SaftReaderError` with `exit_code == 2`; (c) non-XML text raises `exit_code == 1`; (d) via `main([...])`: wrong namespace returns 2 and an **existing** output file is left byte-identical; (e) a sample with `AuditFileVersion 1.10` still parses and adds a warning; (f) `write_saft_data` twice on the same data gives byte-identical files and no `.tmp` leftovers

### Implementation for User Story 1

- [X] T007 [US1] In `phase-1/saft_reader.py` create `SaftReaderError(message, exit_code)`, `NS = "urn:StandardAuditFile-Taxation-Financial:NO"`, helper `text_or_unknown(el, path)` (namespace-qualified `find`, stripped text, `UNKNOWN` when missing/blank), and `read_saft(path)` with an `iterparse(("start","end"))` loop and tag stack: on the first `start` validate root `AuditFile` + `NS` (else exit_code 2); dispatch `end` events for `Header` (parent AuditFile), `Account` (parent GeneralLedgerAccounts), `TaxTableEntry` (parent TaxTable), `Supplier` (parent Suppliers), `Transaction` (parent Journal), calling `el.clear()` afterwards; wrap `OSError`/`ParseError` as exit_code 1
- [X] T008 [US1] In `phase-1/saft_reader.py` implement the Header handler: `saft_version`, `company_name`, `company_registration_number`, `period {start, start_year, end, end_year}` (each `text_or_unknown`); warning when version ≠ "1.30"
- [X] T009 [US1] In `phase-1/saft_reader.py` implement the Account handler → `shared.models.Account`; missing AccountID → append to `summary.skipped`; duplicate ID → keep first + warning
- [X] T010 [US1] In `phase-1/saft_reader.py` implement the TaxTableEntry handler → one `VatCode` per `TaxCodeDetails` (`source "tax_table"`, percentage via `Decimal`, `UNKNOWN` when absent, dates or `None`); prepend the implicit blank `VatCode("", 0, "Ingen mva-kode (blank)", UNKNOWN, None, None, "implicit")`
- [X] T011 [US1] In `phase-1/saft_reader.py` implement the Supplier handler → `Supplier(..., in_master_data=True)`; missing SupplierID → `summary.skipped`
- [X] T012 [US1] In `phase-1/saft_reader.py` implement result assembly + `write_saft_data(data, path)`: numeric-aware sort key (digits by int value, non-numeric after), vat_codes = blank first then by (code, effective_date), `json.dumps(ensure_ascii=False, indent=2)` + trailing newline, write to `<path>.tmp` in the same folder then `os.replace`; `summary.source_file` = file name only
- [X] T013 [US1] In `phase-1/saft_reader.py` implement `main(argv=None)` per `contracts/cli.md`: positional `saft`, `-o/--output` default `<phase-1>/saft_data.json`; on success print `saft_data.json: N accounts, N VAT codes, N suppliers, N mapped / N unknown` and return 0; on `SaftReaderError` print `error: …` to stderr and return its exit code without writing; `if __name__ == "__main__": sys.exit(main())`

**Checkpoint**: T005 and T006 pass.

---

## Phase 4: User Story 2 — Supplier→account map (Priority: P1) — EXIT CRITERION

**Goal**: map each supplier to the cost account used on ≥ 80 % of its invoices, otherwise `unknown`
with a reason.

**Independent Test**: `pytest tests/phase-1/test_supplier_account_map.py` against the sample.

### Tests for User Story 2 (write first, must fail)

- [X] T014 [P] [US2] Create `tests/phase-1/test_supplier_account_map.py` asserting the exact map from `read_saft(sample)`:
  - 50001 NIO → `7033`, `share 0.8`, `invoice_count 5`, candidates `[7033×4, 7026×1]`, `reason None`, `vat_codes_seen ["2"]` (payment and netting transaction NOT counted)
  - 50002 ONEPARK → `7161`, `share 1`, `invoice_count 3`, `vat_codes_seen ["", "2"]`
  - 50003 RA FORSIKRING → `7027`, `invoice_count 2`, `vat_codes_seen [""]`
  - 50004 AMBI SERVICE → `unknown`, `reason "ambiguous history"`, `share None`, candidates `[7026×2 (0.667), 7155×1 (0.333)]` (share rounded to 3 decimals)
  - 50005 SPLITT AS → `unknown`, `reason "multiple accounts on the same invoices"`
  - 50006 NEVER BOOKED AS and 50007 → `unknown`, `reason "no booking history"`, `invoice_count 0`, `candidates []`
  - 50099 → `7026`, `supplier_name "unknown"`; and `suppliers` contains `50099` with `in_master_data False`; a warning mentions 50099
  - for every mapping: `account_id` is `"unknown"` or starts with 3–8; no candidate is `1930`, `2400` or starts with `27`
  - unit tests of the rule on hand-built data: 4 of 5 invoices → mapped (0.80 boundary); 3 of 4 → `unknown`; an invoice with only balance-sheet lines → counted, reason `no cost account on invoices` when no P&L line at all

### Implementation for User Story 2

- [X] T015 [US2] In `phase-1/saft_reader.py` implement the Transaction handler (research R4): collect lines (`AccountID`, `SupplierID`, debit/credit `Decimal`, `TaxInformation/TaxCode` or `""`); distinct SupplierIDs from lines, else the transaction-level `SupplierID`; ignore unless exactly one; invoice only if Σ(credit − debit) over that supplier's lines > 0 (for transaction-level fallback: Σ credit on 2xxx lines > 0); record per supplier: invoice count, and per invoice the **set** of P&L accounts (first char `3`–`8`) and their MK codes
- [X] T016 [US2] In `phase-1/saft_reader.py` implement the mapping decision exactly per data-model table: share = invoices containing account / invoice_count; `≥ Decimal("0.80")`; one qualifying → mapped; ≥ 2 → `multiple accounts on the same invoices`; none → `ambiguous history`; zero invoices → `no booking history`; invoices but no P&L account → `no cost account on invoices`; candidates sorted by count desc then numeric-aware ID, share rounded to 3 decimals; `account_description` from accounts (`UNKNOWN` if absent); produce one mapping per supplier in master data **and** per SupplierID seen in invoices
- [X] T017 [US2] In `phase-1/saft_reader.py` add suppliers seen only in ledger entries to `suppliers` as `Supplier(id, UNKNOWN, UNKNOWN, in_master_data=False)` with a warning `"SupplierID <id> used in GeneralLedgerEntries but not in MasterFiles"`; add `counts.transactions`, `counts.supplier_invoices`, `counts.mapped_suppliers`, `counts.unknown_mappings`

**Checkpoint**: T014 passes — Phase 1 exit criterion "test confirms the supplier→account map" met.

---

## Phase 5: User Story 3 — Visible unknowns (Priority: P2)

**Goal**: every gap is `"unknown"` with a reason and counted in the summary; nothing is guessed.

**Independent Test**: `pytest tests/phase-1/test_unknowns.py`.

### Tests for User Story 3 (write first, must fail)

- [X] T018 [P] [US3] Create `tests/phase-1/test_unknowns.py`: account `7770` has `description "unknown"`; VAT code `99` has `percentage "unknown"` (not 0, not null); supplier `50007` has `name "unknown"`; `summary.unknown_values` equals the number of `"unknown"` field values actually present in each section (count by walking the output); no section value is `None` except the schema-allowed `share`, `reason`, `effective_date`, `expiration_date`; `summary.skipped` has exactly 1 entry (the `Account` without AccountID from T004)

### Implementation for User Story 3

- [X] T019 [US3] In `phase-1/saft_reader.py` compute `summary.unknown_values` per section by counting `"unknown"` values in the serialized dicts (accounts, vat_codes, suppliers, supplier_account_map), and make sure `summary.skipped` and `summary.warnings` are sorted lists for deterministic output

**Checkpoint**: T018 passes.

---

## Phase 6: Polish & Exit Criteria

- [X] T020 [P] Create `tests/phase-1/test_performance.py`: generate in `tmp_path` a SAF-T with 50 000 booking lines (25 000 two-line invoices over 200 suppliers) using the sample's header/master data, assert `read_saft` finishes in < 30 s (SC-005); run `read_saft` + `write_saft_data` twice on the sample and assert byte-identical files (SC-004 determinism)
- [X] T021 Run `python -m pytest tests/phase-1 -v`; fix failures in `phase-1/saft_reader.py` / `shared/models.py` only until all tests pass
- [X] T022 Generate the human-reviewable output: `python phase-1/saft_reader.py samples/saft_sample.xml` → `phase-1/saft_data.json` (exit 0; all four sections non-empty)
- [ ] T023 Human review (user): open `phase-1/saft_data.json` and walk the checklist in `specs/001-phase1-saft-reader/quickstart.md`; Phase 1 is complete only after this review

---

## Dependencies & Execution Order

```
T001 → T002, T003, T004 (parallel)
          └─▶ US1: T005, T006 (parallel, tests) → T007 → T008 → T009 → T010 → T011 → T012 → T013
                    └─▶ US2: T014 (test) → T015 → T016 → T017
                    └─▶ US3: T018 (test) → T019            (needs US1 output; independent of US2)
          US1+US2+US3 ─▶ T020 → T021 → T022 → T023
```

- US1 is the MVP and a prerequisite for US2/US3 (same module, shared parse loop).
- US2 and US3 touch different parts of `saft_reader.py`; they can be done in either order but not
  simultaneously (same file).
- Test-file tasks marked [P] can be written in parallel (different files).

## Parallel Example

```text
# After T001:
T002 tests/conftest.py   |  T003 shared/models.py   |  T004 samples/saft_sample.xml
# Before any implementation:
T005 test_sections.py    |  T006 test_namespace_and_errors.py  |  T014 test_supplier_account_map.py  |  T018 test_unknowns.py
```

## Implementation Strategy

1. **MVP**: Setup + Foundational + US1 → reference data written (accounts, VAT, suppliers).
2. **Exit-criterion story**: US2 → supplier→account map proven by T014.
3. **Trust**: US3 → unknowns counted.
4. **Close Phase 1**: T020–T023 (performance, full green suite, generated output, human review).
   Then STOP — project Phase 2 needs its own `/sp.specify`.
