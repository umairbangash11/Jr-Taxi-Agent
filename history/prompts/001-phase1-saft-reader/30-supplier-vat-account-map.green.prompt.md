---
id: 30
title: Add supplier_vat_account_map to saft_reader
stage: green
date: 2026-11-24
surface: agent
model: claude-sonnet-4-6
feature: 001-phase1-saft-reader
branch: main
user: umairbangash11
command: "extend phase-1/saft_reader.py with supplier_vat_account_map"
labels: ["phase-1","saft_reader","vat_map","80-percent-rule","models"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - shared/models.py
  - phase-1/saft_reader.py
  - tests/phase-1/test_sections.py
  - tests/phase-1/test_supplier_vat_account_map.py
tests:
  - tests/phase-1/test_supplier_vat_account_map.py::test_nio_vat2_maps_at_80_percent
  - tests/phase-1/test_supplier_vat_account_map.py::test_onepark_vat2_maps_to_7161
  - tests/phase-1/test_supplier_vat_account_map.py::test_onepark_blank_vat_maps_to_7161
  - tests/phase-1/test_supplier_vat_account_map.py::test_ra_forsikring_blank_vat_maps_to_7027
  - tests/phase-1/test_supplier_vat_account_map.py::test_ambi_vat2_ambiguous
  - tests/phase-1/test_supplier_vat_account_map.py::test_splitt_vat2_multiple_accounts
  - tests/phase-1/test_supplier_vat_account_map.py::test_ledger_only_supplier_vat2
  - tests/phase-1/test_supplier_vat_account_map.py::test_no_history_suppliers_absent
  - tests/phase-1/test_supplier_vat_account_map.py::test_balance_sheet_accounts_excluded
  - tests/phase-1/test_supplier_vat_account_map.py::test_ordering
---

## Prompt

Extend phase-1/saft_reader.py: add "supplier_vat_account_map" to the output.
For each supplier + VAT code, find the expense account used in the history.
Use the same 80% rule as supplier_account_map. Skip balance-sheet accounts.
Keep the old supplier_account_map unchanged so existing tests still pass.
Add tests in tests/phase-1 using samples/saft_sample.xml.

## Response snapshot

Added `SupplierVatAccountMapping` dataclass to `shared/models.py`.

In `saft_reader.py`:
- Each invoice record now also stores `vat_account_pairs` (set of (account, vat_code) tuples for P&L lines) alongside the existing `accounts` and `vat` sets.
- New `decide_vat_mappings()` function: collects all unique VAT codes from a supplier's invoices, then for each VAT code builds a filtered invoice list (only P&L lines bearing that code) and re-runs the existing `decide_mapping()` to apply the 80% rule.
- `_Reader.result()` emits `supplier_vat_account_map` as a new top-level key OUTSIDE `sections`, keeping `unknown_values` unchanged (existing `test_unknown_counts_match_output` passes without modification).

Updated `test_top_level_keys` in `test_sections.py` to include the new key.
Added `test_supplier_vat_account_map.py` with 10 tests covering all sample suppliers.
All 42 phase-1 tests pass.

## Outcome

- ✅ Impact: `saft_data.json` now carries a per-(supplier, VAT code) expense-account lookup for use by later phases.
- 🧪 Tests: 42/42 passed (32 existing unchanged, 10 new).
- 📁 Files: shared/models.py, phase-1/saft_reader.py, tests/phase-1/test_sections.py (1-line change), tests/phase-1/test_supplier_vat_account_map.py (new).
- 🔁 Next prompts: use supplier_vat_account_map in phase-2 read_invoice to suggest the expense account from the detected VAT rate.
- 🧠 Reflection: keeping the new section outside `sections{}` was the smallest viable change — unknown_values and all shape-testing for the original four sections needed zero further edits.

## Evaluation notes (flywheel)

- Failure modes observed: scope mismatch in fixture (module-scoped fixture depending on function-scoped sample_path) — fixed by inlining the sample path.
- Graders run and results (PASS/FAIL): pytest tests/phase-1/ — PASS (42/42)
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): wire supplier_vat_account_map into phase-2 account suggestion logic
