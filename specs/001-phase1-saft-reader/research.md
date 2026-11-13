# Research: Phase 1 — SAF-T Reader

**Feature**: `001-phase1-saft-reader` · **Date**: 2026-11-12 · **Spec**: [spec.md](spec.md)

All Technical Context items were resolvable from the spec, the constitution and the local
environment; no `NEEDS CLARIFICATION` remained. Decisions below.

## R1. XML parsing approach

- **Decision**: Python standard library `xml.etree.ElementTree.iterparse` (streaming, `start`/`end`
  events), clearing each processed element.
- **Rationale**: SC-005 requires 50 000 booking lines in < 30 s; streaming keeps memory flat for
  full-year exports. Stdlib = no new runtime dependency (constitution: dependencies must be
  justified). Bundled expat is 2.6.4 (verified), which has built-in protection against entity
  expansion ("billion laughs"); ElementTree does not resolve external entities.
- **Alternatives**: `lxml` (faster, but a compiled dependency not needed at this scale);
  `xml.dom.minidom` / full `ElementTree.parse` (loads the whole file — fails the memory goal);
  `defusedxml` (not installed; stdlib + modern expat already covers the risks for local files).

## R2. Namespace handling (FR-001, FR-002, SC-004)

- **Decision**: Read the namespace from the root element's tag (`{ns}AuditFile`), require it to equal
  `urn:StandardAuditFile-Taxation-Financial:NO`, and match all elements by `{ns}LocalName`.
  Prefixes are irrelevant because ElementTree expands them to Clark notation (`{uri}local`).
- **Rationale**: Identical output for default-namespace and any-prefix files by construction;
  wrong country/namespace → clear error before any output (FR-001).
- **Alternatives**: Ignoring namespaces (match local names only) — would silently accept other
  countries' SAF-T, violating FR-001; hard-coded `n1:` prefix — breaks on other exporters.

## R3. Reuse of the pre-constitution `saft-parser` skill

- **Decision**: **Port** the proven parsing patterns (streaming loop, namespace detection,
  decimal amounts) into `/phase-1`, re-written to this spec. Do **not** import from
  `.claude/skills/saft-parser` at runtime.
- **Rationale**: Constitution limits Phase 1 to `/phase-1`, `/shared`, `/tests`, `/samples`; a runtime
  import from `.claude/` would make the phase depend on code outside its boundary. The spec also
  differs materially: P&L-only mapping (classes 3–8 vs. "ignore 27xx"), the ≥ 80 % rule per invoice,
  the literal `unknown`, the explicit blank-VAT entry and a different output schema.
- **Alternatives**: Import the skill (boundary violation); copy verbatim (wrong semantics);
  write from scratch without reference (loses tested namespace/streaming handling).

## R4. What counts as a supplier invoice (FR-007, edge case "payments")

- **Decision**: A transaction is a supplier invoice when it has exactly one distinct `SupplierID`
  (on lines, or on the transaction if no line carries one) **and** the lines carrying that
  `SupplierID` are **net credit** (payable increased). Transactions that are net debit on the
  supplier (payments, credit notes), or that name several suppliers, do not teach the map.
- **Rationale**: Payments (debit 2400 / credit 1930) would otherwise map suppliers to the bank.
  Multi-supplier transactions (netting) can't be attributed without guessing.
- **Alternatives**: Use all transactions with a SupplierID (pollutes the map with 1930);
  use the journal type (exporter-specific, not standardised).

## R5. Which accounts can be mapped (FR-007)

- **Decision**: Only profit-and-loss accounts, i.e. account IDs whose first digit is 3–8 (Norwegian
  standard chart NS 4102). Classes 1–2 (bank 1930, payable 2400, VAT 27xx, etc.) are never mapped.
- **Rationale**: Matches the spec assumption and is robust across charts that use different VAT or
  payable account numbers.
- **Alternatives**: Exclude a fixed list (1930, 2400, 2710 …) — brittle per client chart.

## R6. The ≥ 80 % rule (FR-008, clarified)

- **Decision**: Count **per invoice**: each invoice contributes 1 to every *distinct* P&L account on
  it. `share(account) = invoices containing account / supplier's invoices`. If exactly one account has
  share ≥ 0.80 → mapped. If none → `unknown`, reason `ambiguous history`. If two or more reach 0.80
  (every invoice is split the same way) → `unknown`, reason `multiple accounts on the same invoices`.
  Invoices with no P&L line are counted in the total (they lower the share) and reported.
- **Rationale**: Counting lines would let one invoice with many lines dominate; per-invoice matches
  the user's mental model ("9 of 10 NIO invoices went to 7033"). The split-invoice case is genuinely
  ambiguous for a single "the account" answer.
- **Alternatives**: Count lines or amounts (amount-weighting lets one large invoice decide).

## R7. Representing `unknown` and blank VAT (FR-005, FR-010)

- **Decision**: The literal JSON string `"unknown"` replaces any undeterminable value (also where a
  number is otherwise expected, e.g. `percentage`), always with a `reason` field where one applies.
  The blank VAT entry is `{"code": "", "percentage": 0, "description": "Ingen mva-kode (blank)",
  "source": "implicit"}`; codes from the file have `"source": "tax_table"`.
- **Rationale**: Exactly what the user asked ("record it as unknown"); never confusable with 0 or
  null in review; schema makes the union explicit (see contracts).
- **Alternatives**: `null` (silently treated as 0 by consumers); omitting fields (invisible gaps).

## R8. Output writing & determinism (FR-011, FR-012, edge case "wrong file")

- **Decision**: Build the whole result in memory, then write `phase-1/saft_data.json` atomically
  (temp file in the same folder + `os.replace`). UTF-8, `ensure_ascii=False`, indent 2, stable sort
  (IDs numeric-aware: `"930" < "1930" < "7026"`, non-numeric after), no timestamps in the content.
- **Rationale**: A failed run never leaves a partial file or clobbers a good one; byte-identical
  re-runs (SC-004) need no timestamps and stable ordering; æøå readable for review.
- **Alternatives**: Streaming JSON output (no benefit at reference-data size); including a run
  timestamp (breaks determinism — the summary carries the source file name instead).

## R9. Models in `/shared`

- **Decision**: Plain `@dataclass(frozen=True)` models + the `UNKNOWN = "unknown"` constant in
  `shared/models.py`, with `to_dict()` for JSON. Amounts as `Decimal` (constitution III, used from
  Phase 2 on; Phase 1 only needs percentages).
- **Rationale**: Phases 2–3 consume these types; stdlib only; frozen = safe to share.
- **Alternatives**: Pydantic (new dependency; worth reconsidering in Phase 2 when the Agents SDK,
  which uses Pydantic, arrives).

## R10. Testing

- **Decision**: `pytest` (8.3.3 installed) in `tests/phase-1/`; a `tests/conftest.py` puts the repo
  root and `phase-1/` on `sys.path` (folder names with `-` are not importable packages).
  Tests: exact supplier→account map for the sample (exit criterion), all four sections populated,
  bank/VAT/payable never mapped, ambiguous & no-history → `unknown`, incomplete records → `unknown`,
  namespace-prefix invariance, wrong-namespace error with no output, ≥ 80 % boundary (exactly 80 %
  maps, 79 % does not), determinism, 50 000-line performance.
- **Rationale**: Covers every FR/SC with an automated check; constitution makes tests mandatory.
- **Alternatives**: `unittest` (works, but pytest is installed and gives clearer failure output).

## R11. Agents SDK / Groq in Phase 1

- **Decision**: Not used (FR-015). The OpenAI Agents SDK is not yet installed; it is introduced in
  Phase 2, where the entry suggester needs an LLM.
- **Rationale**: Parsing must be deterministic and verifiable (constitution II); an LLM adds risk and
  no value here. Not a constitution violation — the stack defines the agent's tools, not that every
  phase must call an LLM.
