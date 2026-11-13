---
name: entry-builder
description: Build a balanced JR Taxi journal entry (bilag) with columns Konto, MK (VAT code), Debet, Kredit, Løyve, Bil from document-reader output (invoice/receipt fields) and saft-parser output (supplier→account mapping, MVA codes). Enforces debet = kredit and marks mixed-VAT, unclear or complex documents for human review instead of guessing. Use when the user wants to book/postere a faktura or kvittering, or turn extracted document data into journal lines.
---

# Entry Builder (JR Taxi bilag)

`scripts/build_entry.py` combines:
- **document-reader** JSON. Run it with `--include-text` so that Løyve and Bil can be detected.
- **saft-parser** JSON, which supplies the chart of accounts, MVA codes, suppliers and booking history.
- An optional **config** file. Copy `config.example.json` to `jr_taxi_config.json` and fill in JR Taxi's real løyver and biler.

## Pipeline

```bash
S=.claude/skills
python $S/saft-parser/scripts/parse_saft.py export.xml -o saft.json
python $S/document-reader/scripts/read_document.py bilag.pdf --include-text -o doc.json
python $S/entry-builder/scripts/build_entry.py --document doc.json --saft saft.json \
       --config jr_taxi_config.json -o bilag.json --csv bilag.csv
```
Exit `0` means the documents were processed, so check each bilag's `status`. Exit `1` means an input or usage error.

## Posting convention

| Document | Debit line(s) | Credit line |
|---|---|---|
| faktura | Expense account, **gross** amount, **MK**, Løyve, Bil | `payable_account` (2400) + supplier ID, gross |
| kvittering (already paid) | same | `paid_receipt_credit_account` (default 1920), no supplier ID |

There is no separate 2710 line, because the accounting system splits out input VAT using the MK code.
Løyve and Bil go on the expense lines only. Balance-sheet lines leave them empty.

**Debet = kredit is always enforced** in exact decimal arithmetic. An unbalanced bilag is always
`blocked` and never comes out with lines.

## How values are chosen (nothing is guessed)

- **Supplier:** matched on the org number against `suppliers[].registration_number`, otherwise on an exact normalised name match. A name-only match is sent to review.
- **Expense account:** the supplier's most-used account in SAF-T history. VAT accounts (`27xx`) and the payable and bank accounts are ignored. It is only chosen when it accounts for at least `min_mapping_share` (60 %) of the supplier's invoices. Otherwise the account is left empty and the candidates are listed.
- **MK:** the document's VAT rate is mapped to the one **input** (deductible) code in SAF-T with that rate, using standard codes 1=25 %, 11=15 %, 12=11.11 %, 13=12 % and 0. Output codes such as 3 or 33 are never used. `vat_code_by_rate` in the config overrides this. If the MK differs from the supplier's usual MK on that account, the bilag goes to review.
- **Løyve/Bil:** the configured løyve IDs and registration numbers are searched for in the document text, ignoring spaces and hyphens. With no match, the fields stay empty and the bilag goes to review, unless `default_loyve` is set in the config.

## Statuses

| Status | Meaning | What you do |
|---|---|---|
| `ready` | Lines are built and balanced, and every check passed | Show the lines to the user |
| `needs_review` | Draft lines are built, but `review_reasons` lists items to confirm, some fields may be empty | Show the draft and the reasons, then ask the user |
| `blocked` | No lines are produced, and `blocked_reasons` explains why | Ask the user and re-run with overrides |

The following make a bilag **blocked**:
- a document with `needs_ocr` or `error` status
- no confirmed total
- a non-positive total, such as a credit note
- a document type that isn't clearly faktura or kvittering
- **mixed VAT rates** without a manual split
- split lines that don't add up to the total
- an imbalance

The following send a bilag to **review**:
- an unknown or ambiguous supplier or account, or a supplier matched by name only
- a missing date, invoice number, MK, Løyve or Bil
- a currency other than NOK
- an amount ≥ `review_above_amount` (30 000, the aktiveringsgrense, so the purchase may be a fixed asset)
- an MK that differs from the supplier's history

## Resolving review items (works only when the input has one document)

```bash
--override total_amount=59,80   # also: date, vat_rate, document_type, vendor_name,
                                #       vendor_org_number, invoice_number
--expense-account 6600  --mk 1  --loyve L-101  --bil EL12345
--line 6600:1:5000,00 --line 7140:11:1000,00   # manual split for mixed VAT (gross per line)
```
Use only values the **user** confirmed or that are visible on the document. Never pick a candidate yourself.

## Output

The JSON has the shape `{"bilag": [{status, header, lines[], totals, review_reasons, blocked_reasons, source_file}]}`.
Each line contains `konto, konto_navn, mk, debet, kredit, loyve, bil, tekst, supplier_id`.
`--csv` writes the bilag that aren't blocked as UTF-8 (with BOM) CSV, separated by semicolons with
decimal commas. The columns are `Bilag;Dato;Konto;MK;Debet;Kredit;Løyve;Bil;Tekst`.

Show the result to the user as a table with the columns Konto, MK, Debet, Kredit, Løyve and Bil, followed by any reasons.

## Tests

```bash
python .claude/skills/entry-builder/tests/test_build_entry.py -v
```
These tests include an end-to-end run that uses the document-reader faktura fixture.
