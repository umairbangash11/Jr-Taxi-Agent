# Implementation Plan: Phase 1 — SAF-T Reader

**Branch**: `001-phase1-saft-reader` | **Date**: 2026-11-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-phase1-saft-reader/spec.md`

## Summary

Read a Norwegian SAF-T Financial (v1.30) XML export and write one human-reviewable reference file,
`phase-1/saft_data.json`, with four sections — `accounts`, `vat_codes`, `suppliers`,
`supplier_account_map` — plus a `summary`. The file is the agent's only source of valid codes
(constitution II). Approach: a deterministic, streaming stdlib parser in `/phase-1` with
namespace-agnostic element matching; the supplier→account map is learned only from supplier
**invoices** (supplier payable net-credited) and only from P&L accounts (classes 3–8), choosing an
account only when it is on **≥ 80 %** of the supplier's invoices; everything undeterminable is the
literal `"unknown"` with a reason. Shared frozen dataclasses go to `/shared/models.py`. A fake
sample SAF-T in `/samples` covers every rule; pytest suites in `/tests/phase-1/` prove the map.

## User Technical Direction — confirmed 2026-11-12

The user re-issued `/sp.plan` with explicit technical direction. Every directive was already in this
plan; nothing was changed in the design. Traceability:

| User directive | Where it is designed |
|---|---|
| Python 3.13, stdlib only (ElementTree, json, decimal, dataclasses, argparse); no LLM; no new deps | Technical Context; research R1, R11 |
| Streaming `iterparse`, flat memory | research R1; Key Design Point 2 |
| Namespace-agnostic matching, SAF-T 1.30 namespace | research R2; Key Design Point 1 |
| Learn only from supplier **invoices** | research R4 (one supplier, payable net-credited) |
| Count by invoice, not by line | research R6; data-model decision table |
| Map only when on **≥ 80 %** of invoices | research R6 (exactly 80 % maps); schema `share ≥ 0.8` |
| Only accounts starting 3–8; never 1930, 2400, 27xx | research R5; schema pattern `^[3-8]` |
| Below 80 % or split → `unknown` + reason, never guess | data-model: `ambiguous history`, `multiple accounts on the same invoices` |
| `phase-1/saft_data.json` with 5 sections | data-model "Output document"; contracts/saft_data.schema.json |
| Shared dataclasses in `/shared/models.py` | research R9; Project Structure |
| Deterministic + atomic write | research R8; Key Design Point 6 |
| pytest in `/tests/phase-1/` | research R10; Project Structure |
| Fake sample in `/samples` covering every rule | spec FR-013; Project Structure |
| Changes only in `/phase-1`, `/shared`, `/tests`, `/samples` | Constitution Check "Scope" |

Note: accounts starting with **3** are income (salgsinntekt), not expenses; they are kept mappable as
directed (and per spec "cost/income accounts"). In practice supplier invoices rarely touch class 3.

## Technical Context

**Language/Version**: Python 3.13 (3.13.2 verified)
**Primary Dependencies**: Python standard library only (`xml.etree.ElementTree`, `json`, `decimal`, `dataclasses`, `argparse`); no LLM in this phase
**Storage**: Files — input SAF-T XML; output `phase-1/saft_data.json` (UTF-8 JSON, atomic write)
**Testing**: pytest 8.3.3 (installed), tests in `tests/phase-1/`
**Target Platform**: Windows 10+ / Linux / macOS desktop, command line
**Project Type**: single (phase-folder layout per constitution)
**Performance Goals**: 50 000 booking lines in < 30 s (SC-005)
**Constraints**: streaming parse (flat memory); deterministic byte-identical output; no network; no guessed values; Norwegian characters preserved
**Scale/Scope**: one company's full-year SAF-T (≈ 10³ accounts/suppliers, ≈ 10⁵ lines)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*
*Source: `.specify/memory/constitution.md` v1.0.0.*

| Gate | Status | Evidence |
|---|---|---|
| **Phase gate**: one project phase; previous phase's exit criteria met | ✅ PASS | This is phase-1 (no predecessor) |
| **Scope**: changes only in `/phase-1`, `/shared`, `/tests`, `/samples` | ✅ PASS | See Project Structure; no runtime import from `.claude/skills` (research R3) |
| **I. Human-in-the-loop** | ✅ PASS (N/A) | Phase 1 suggests/posts nothing; output is reference data for review |
| **II. No invented codes** | ✅ PASS | Codes come only from the file; gaps → `"unknown"` + reason (FR-010, R7); map only ≥ 80 % (R6) |
| **III. Balance** | ✅ PASS (N/A) | No entries created; `Decimal` used for amounts when summing payable lines (R4) |
| **IV. Bank account 1930** | ✅ PASS | 1930 is read only and never mapped as a supplier account (R5); payments excluded (R4) |
| **V. Fake data only** | ✅ PASS | `samples/saft_sample.xml` is invented; output contains file name only, no local paths |
| **Stack** | ✅ PASS | Python 3.13 stdlib; Agents SDK/Groq not needed in Phase 1 (R11) — no new dependency |
| **Exit criteria planned** | ✅ PASS | pytest suite in `tests/phase-1/`; human-reviewable `phase-1/saft_data.json` + quickstart review list |

**Post-design re-check (after data-model/contracts)**: ✅ all gates still pass — the schema enforces
`"unknown"` instead of guessed values, mapped `account_id` must start with 3–8 (never 1930/2400/27xx),
and the blank VAT entry is the only implicit value (explicitly required by the user).

## Project Structure

### Documentation (this feature)

```text
specs/001-phase1-saft-reader/
├── plan.md              # This file
├── research.md          # Phase 0 decisions R1–R11
├── data-model.md        # Entities, mapping decision table
├── quickstart.md        # Run + human review checklist
├── contracts/
│   ├── saft_data.schema.json   # JSON Schema of the output file
│   └── cli.md                  # Command + Python API contract
├── checklists/
│   └── requirements.md  # Spec quality checklist (passed)
└── tasks.md             # Created by /sp.tasks (not by this command)
```

### Source Code (repository root)

```text
phase-1/
├── saft_reader.py       # CLI + read_saft() / write_saft_data(); streaming parse, mapping rules
└── saft_data.json       # Generated from samples/saft_sample.xml (human-reviewable output)

shared/
├── __init__.py
└── models.py            # UNKNOWN constant; Account, VatCode, Supplier, SupplierAccountMapping

tests/
├── conftest.py          # adds repo root and phase-1/ to sys.path; sample paths fixture
└── phase-1/
    ├── test_supplier_account_map.py   # exit criterion: exact map for the sample + rules
    ├── test_sections.py               # four sections populated, values match sample, unknowns
    ├── test_namespace_and_errors.py   # prefix invariance, wrong namespace/XML → error, no output
    └── test_performance.py            # 50 000 generated lines < 30 s, determinism

samples/
└── saft_sample.xml      # Fake JR Taxi-like SAF-T 1.30 (invented names, org numbers, amounts)
```

**Structure Decision**: Constitution phase layout. All Phase 1 logic in a single module
`phase-1/saft_reader.py` (≈ 300 lines; splitting adds nothing at this size). Types that later phases
consume live in `shared/models.py`. Tests reach `phase-1/` through `tests/conftest.py` because a folder
named `phase-1` is not an importable package. The pre-constitution `.claude/skills/saft-parser` is
used as reference only, not imported (R3).

## Key Design Points

1. **Validation first** (FR-001): read the root `start` event; reject non-`AuditFile` or namespace ≠
   `urn:StandardAuditFile-Taxation-Financial:NO` with exit code 2 before any output.
2. **One streaming pass**: handle `Header`, `Account`, `TaxTableEntry`, `Supplier`, `Transaction` on
   their `end` events, then `clear()` them; track the parent via a tag stack.
3. **Invoice detection** (R4) with `Decimal` sums of the supplier lines' credit − debit.
4. **Mapping** per data-model decision table; per-invoice counting (R6); boundary: share exactly 0.80
   maps.
5. **Unknown handling**: one helper `text_or_unknown()`; `summary.unknown_values` counts every
   `"unknown"` written per section (SC-003).
6. **Output**: numeric-aware stable sorting; `json.dumps(ensure_ascii=False, indent=2,
   sort_keys=False)`; temp file + `os.replace` (R8).

## Risks

- **Exporter variance** (some systems put `SupplierID` only on the transaction, or omit it on lines):
  handled by the transaction-level fallback (R4); suppliers named only in free text are not mapped
  (spec assumption) — they appear as `no booking history`, never as guesses.
- **Client-specific VAT codes** (JR Taxi's `2` = 25 % is not the standard code `1`): codes are
  reported verbatim with `standard_tax_code` alongside, so Phase 2 can reason about direction.
- **Script tooling on Windows PowerShell 5.1** (`create-new-feature.ps1` nested `Join-Path`): outside
  Phase 1 scope; noted for a separate fix.

## Complexity Tracking

No constitution violations — table intentionally empty.
