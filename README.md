# JR Taxi AI Bookkeeping Agent

An AI assistant for a Norwegian bookkeeper. It reads a client's accounting data and documents
(invoices, receipts, bank statements) and **suggests** journal entries (*bilag*) for a taxi
business. The agent suggests and a human approves: **it never posts anything to the accounting
system on its own.**

Every suggestion is checked in plain Python before a person sees it. The checks are:

- Account and VAT codes must exist in the client's SAF-T file. No invented codes.
- Debet must equal kredit, using exact decimal arithmetic.
- Uncertain values are left empty and flagged **"needs review"**, never guessed.

## Architecture

```
 ┌──────────────┐   ┌─────────────────┐   ┌───────────────┐   ┌─────────────┐   ┌────────────────┐
 │ SAF-T reader │──▶│ Document reader │──▶│ Entry builder │──▶│  Validator  │──▶│ Human approval │
 └──────────────┘   └─────────────────┘   └───────────────┘   └─────────────┘   └────────────────┘
  kontoplan, MVA     vendor, org nr,       balanced bilag:      codes exist in     a named person
  codes, suppliers,  date, total, MVA      Konto · MK · Debet   SAF-T, debet =     approves; output
  supplier→account   rate, invoice no.     · Kredit · Løyve ·   kredit, required   is exported as a
  map (≥ 80 % rule)  from PDF / scan       Bil                  fields present     file to import
```

| Stage | What it does | Status |
|---|---|---|
| **1. SAF-T reader** | Parses a Norwegian SAF-T Financial v1.30 export into a reference JSON: accounts, VAT codes, suppliers, and which account each supplier is normally booked to | ✅ Phase 1, done |
| **2. Document reader** | Extracts the key fields from invoices (*fakturaer*) and receipts (*kvitteringer*), including scanned files | Prototype skill |
| **3. Entry builder** | Turns those fields plus the SAF-T mappings into a balanced journal entry | Prototype skill |
| **4. Validator** | Quality gate: rejects unbalanced entries, unknown codes, VAT codes not valid on the entry date, and duplicates | Prototype skill |
| **5. Human approval** | The bookkeeper reviews each `ready` / `needs review` / `blocked` suggestion; only approved entries are exported | Planned (Phase 5) |

Bank matching and reconciliation (Phase 3) sit beside this pipeline. A bank-account line is
only suggested when the payment really appears on the bank statement.

**Roadmap.** The project is built one phase at a time, and each phase goes
spec → plan → tasks → implement, with tests, before the next one starts.

| Phase | Folder | Scope |
|---|---|---|
| 1 | `phase-1/` | SAF-T reader ✅ |
| 2 | `phase-2/` | Document reader + entry suggester |
| 3 | `phase-3/` | Bank matching + reconciliation |
| 4 | `phase-4/` | Complex entries + guardrails |
| 5 | `phase-5/` | Review interface + export |

The prototypes for later stages live in `.claude/skills/` (saft-parser, document-reader,
entry-builder, qa-validator, bank-matcher) and in `mcp-servers/`. Each will be ported into its
phase folder when that phase starts.

## Tech stack

- **Python 3.13.** All deterministic logic (parsing, validation, balancing, matching) is plain,
  testable Python.
- **OpenAI Agents SDK.** Agent orchestration for the LLM-driven stages (Phase 2 onward).
- **Groq (`llama-3.3-70b`).** The LLM provider. Its output is only ever a *proposal* and is
  re-checked in code.
- **Norwegian SAF-T Financial XML v1.30** is the source of truth for account and VAT codes.

Phase 1 doesn't use an LLM at all. It runs on the Python standard library only, with no network
calls and no API key. The Agents SDK and Groq come in from Phase 2.

## Phase 1: SAF-T reader

Phase 1 reads a SAF-T file and writes `phase-1/saft_data.json`, the reference data that the
later phases check against.

- **Supplier → account mapping.** It learns which account a supplier is booked to from the
  ledger history. A mapping is accepted only when one account appears on **at least 80 %** of
  that supplier's invoices. Anything below that, or split across several accounts, becomes
  `"unknown"`, with the reason and the candidate accounts listed.
- **Large files.** It streams the XML (`iterparse`), so memory use stays flat.
- **Repeatable output.** The same input always gives byte-identical output.
- **Robust to bad input.** Missing or broken records are counted and reported under
  `summary.warnings` and `summary.unknown_values`. They are never silently filled in.

### Run it

Requires Python 3.13. Phase 1 itself needs no extra packages; the tests need `pytest`.

```bash
# Parse the bundled fake SAF-T file → phase-1/saft_data.json
python phase-1/saft_reader.py samples/saft_sample.xml

# Or choose the output path
python phase-1/saft_reader.py samples/saft_sample.xml -o out.json
```

Example output:

```
saft_data.json: 10 accounts, 6 VAT codes, 8 suppliers, 4 mapped / 4 unknown
```

| Exit code | Meaning |
|---|---|
| `0` | Success (any warnings are inside the JSON) |
| `1` | File unreadable or not well-formed XML; output not written |
| `2` | Not a Norwegian SAF-T file; output not written |

### Run the tests

```bash
pip install pytest
python -m pytest tests/phase-1 -v     # 32 tests
```

### Use the output

```python
import json

data = json.load(open("phase-1/saft_data.json", encoding="utf-8"))
valid_accounts = {a["id"] for a in data["accounts"]}

nio = next(m for m in data["supplier_account_map"] if m["supplier_name"] == "NIO")
if nio["account_id"] == "unknown":
    ...  # flag "needs review" and never guess
```

More detail is in [`specs/001-phase1-saft-reader/`](specs/001-phase1-saft-reader/): the spec,
plan, data model, JSON schema and quickstart.

## Privacy: fake data only

**This repository contains only fake data.** The SAF-T file in `samples/`, the generated
`phase-1/saft_data.json` and all test fixtures are synthetic. Companies such as "Testtaxi Demo AS"
and org numbers such as `999999999` are made up.

Real client data is never committed. `.gitignore` blocks real SAF-T exports (`*.xml` outside the
fake samples and fixtures), real output JSON, PDFs and scanned images, bank exports (`*.csv`,
`*.xlsx`), local databases, client folders and `.env`. Secrets such as `GROQ_API_KEY` are read
from the environment or a local `.env` file.

## Project structure

```
phase-1/            SAF-T reader (saft_reader.py) + generated saft_data.json
shared/             Common data models
samples/            Fake SAF-T sample
tests/phase-1/      Phase 1 tests
specs/              Spec-driven development artifacts (spec, plan, tasks, contracts)
.claude/skills/     Prototype skills for the later pipeline stages
mcp-servers/        Prototype MCP servers (SAF-T, documents, bank, reconcile, ledger, filesystem)
.specify/           Project constitution and templates
history/            Prompt history and decision records
```
