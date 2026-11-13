# Data Model: Phase 1 — SAF-T Reader

**Feature**: `001-phase1-saft-reader` · **Date**: 2026-11-12
Models live in `shared/models.py` (consumed by later phases). `UNKNOWN = "unknown"`.
Wherever a field says *or `unknown`*, the literal string `"unknown"` is used — never `null` or `0`.

## Account

| Field | Type | Source (SAF-T 1.30) | Rules |
|---|---|---|---|
| `id` | string | `MasterFiles/GeneralLedgerAccounts/Account/AccountID` | Required; an account without ID is skipped and counted in `summary.skipped` |
| `description` | string or `unknown` | `.../Account/AccountDescription` | Exactly as written (æøå preserved); missing/blank → `unknown` |
| `standard_account_id` | string or `unknown` | `.../Account/StandardAccountID` | Informational |

Uniqueness: `id`. Duplicate IDs → first kept, warning in summary.

## VatCode

| Field | Type | Source | Rules |
|---|---|---|---|
| `code` | string | `TaxTable/TaxTableEntry/TaxCodeDetails/TaxCode` | `""` only for the implicit blank entry |
| `percentage` | number or `unknown` | `.../TaxCodeDetails/TaxPercentage` | Missing → `unknown` (never 0); blank entry = `0` |
| `description` | string or `unknown` | `.../TaxCodeDetails/Description` | |
| `standard_tax_code` | string or `unknown` | `.../TaxCodeDetails/StandardTaxCode` | |
| `effective_date` | ISO date or `null` | `.../TaxCodeDetails/EffectiveDate` | `null` = not limited (not a missing value) |
| `expiration_date` | ISO date or `null` | `.../TaxCodeDetails/ExpirationDate` | |
| `source` | `"tax_table"` \| `"implicit"` | — | `implicit` only for the blank entry |

The same `code` may appear several times with different validity dates (edge case "several periods");
all variants are kept, ordered by `effective_date`.

## Supplier

| Field | Type | Source | Rules |
|---|---|---|---|
| `id` | string | `MasterFiles/Suppliers/Supplier/SupplierID` | Required; missing → skipped + counted |
| `name` | string or `unknown` | `.../Supplier/Name` | Exactly as written |
| `registration_number` | string or `unknown` | `.../Supplier/RegistrationNumber` | Org.nr — used by Phase 2 matching |
| `in_master_data` | boolean | — | `false` for IDs seen only in ledger entries (then `name` = `unknown`) |

## SupplierAccountMapping

One per supplier that appears in master data **or** in ledger entries.

| Field | Type | Rules |
|---|---|---|
| `supplier_id` | string | |
| `supplier_name` | string or `unknown` | From Supplier |
| `account_id` | string or `unknown` | The single P&L account with share ≥ 0.80, else `unknown` |
| `account_description` | string or `unknown` | From Account when mapped |
| `share` | number (0–1) or `null` | Share of the chosen account; `null` when `unknown` |
| `invoice_count` | integer ≥ 0 | Supplier invoices seen (R4) |
| `candidates` | list of `{account_id, account_description, invoice_count, share}` | All P&L accounts seen, sorted by `invoice_count` desc, then ID |
| `reason` | string or `null` | `null` when mapped; else one of: `no booking history`, `ambiguous history`, `multiple accounts on the same invoices`, `no cost account on invoices` |
| `vat_codes_seen` | list of string | MK codes on the supplier's P&L lines (blank → `""`), for Phase 2 cross-checks |

### Mapping decision (state per supplier)

```
invoice_count == 0                         → unknown, "no booking history"
no P&L line on any invoice                 → unknown, "no cost account on invoices"
exactly one account with share ≥ 0.80      → mapped (account_id, share)
two or more accounts with share ≥ 0.80     → unknown, "multiple accounts on the same invoices"
no account with share ≥ 0.80               → unknown, "ambiguous history"
```

Invoice (R4): transaction with exactly one distinct SupplierID whose lines are net credit.
P&L account (R5): account ID whose first character is `3`–`8`.

## Summary

| Field | Type | Notes |
|---|---|---|
| `source_file` | string | File name only (no path → no local paths leak into output) |
| `saft_version` | string or `unknown` | `Header/AuditFileVersion` |
| `company_name`, `company_registration_number` | string or `unknown` | `Header/Company` |
| `period` | `{start, start_year, end, end_year}` (strings or `unknown`) | `Header/SelectionCriteria` |
| `counts` | `{accounts, vat_codes, suppliers, mapped_suppliers, unknown_mappings, transactions, supplier_invoices}` | |
| `unknown_values` | `{accounts, vat_codes, suppliers, supplier_account_map}` | Number of `unknown` fields per section (SC-003) |
| `skipped` | list of strings | Records dropped for missing IDs |
| `warnings` | list of strings | e.g. version ≠ 1.30, duplicate IDs, supplier IDs not in master data |

## Output document: `phase-1/saft_data.json`

```
{ "summary": Summary,
  "accounts": [Account …]               (sorted by id, numeric-aware),
  "vat_codes": [VatCode …]              (blank entry first, then by code, numeric-aware),
  "suppliers": [Supplier …]             (sorted by id),
  "supplier_account_map": [SupplierAccountMapping …] (sorted by supplier_id) }
```

Formal schema: [contracts/saft_data.schema.json](contracts/saft_data.schema.json).
