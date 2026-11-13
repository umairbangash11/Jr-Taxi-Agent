---
name: bank-matcher
description: Match accounting documents (invoices/fakturaer, receipts/kvitteringer, or built bilag) to bank statement lines by amount, date and vendor, returning paid / uncertain / not_found per document and listing outgoing bank lines with no document. Reads Norwegian netbank CSV exports (DNB, SpareBank 1, Nordea… columns auto-detected) and ISO 20022 CAMT.053 XML. Use when the user asks whether documents are paid, wants bank reconciliation (bankavstemming), or wants to find payments missing a bilag.
---

# Bank Matcher

`scripts/match_bank.py` matches documents to **outgoing** bank lines. It flags weak or
ambiguous matches as `uncertain` and never reports them as paid.

## Usage

```bash
python .claude/skills/bank-matcher/scripts/match_bank.py \
    --documents doc.json [--documents bilag.json] --bank kontoutskrift.csv -o match.json
```
- `--documents` accepts **document-reader** output (`{"documents": [...]}`) or **entry-builder** output (`{"bilag": [...]}`). It can be repeated.
- `--bank` takes a CSV file, or an `.xml` file for CAMT.053/054.
- `--receipt-days 7`, `--invoice-days 60` and `--early-days 3` set the date window. A payment can fall up to *early* days before the document date and up to N days after it.
- `--tolerance 0` is the allowed amount difference in NOK. It defaults to exact to the øre. Raise it only when the user asks.
- The CSV columns can be overridden with `--date-col`, `--text-col` (repeatable), `--amount-col`, or `--out-col` with `--in-col`.

Exit `0` means the files were processed. Exit `1` means an input error, reported as `{"error": ...}` on stderr.

## Bank formats

- **CSV:** the delimiter is sniffed, and the file is read as UTF-8 or else cp1252. The header row is found by its date column. Date columns are recognised by names such as `Dato`/`Bokført dato`/`Transaksjonsdato`, with `Rentedato` used only as a fallback. Text comes from every column such as `Forklaring`/`Beskrivelse`/`Tekst`/`Mottaker`/`KID`, joined together. Amounts come either from separate `Uttak`/`Ut fra konto` and `Innskudd`/`Inn på konto` columns or from one signed `Beløp` column. If a single amount column has only positive values, a warning is given, because outgoing payments can't be told apart.
- **CAMT.053:** each `Ntry` becomes one line. `CdtDbtInd=DBIT` means outgoing. The date is `BookgDt`, falling back to `ValDt`. The text is built from the creditor names, `Ustrd`, the structured `Ref` (KID) and `AddtlNtryInf`.

## Matching rules

1. **Amount (required):** the bank line must be outgoing, and its absolute amount must equal the document total within the tolerance.
2. **Date window:** a kvittering is matched from 3 days before to 7 days after the document date, and a faktura from 3 days before to 60 days after.
3. **Vendor signal** in the bank text:
   - `reference`: the invoice number (4 characters or more) or the org number appears in the text
   - `strong`: the vendor name appears, ignoring AS, Norge and similar words, or at least 60 % of its words appear
   - `weak`: some words overlap. This often means only a shared place name, such as *Kiwi Majorstuen* compared with *REMA 1000 MAJORSTUEN*.
   - `none`
4. **Score and assignment:** the amount gives 50 points. The vendor signal adds 40, 30, 10 or 0 points. Date closeness adds up to 20 points. Each bank line pays **at most one** document, and pairs are assigned best first.

| Status | When |
|---|---|
| `paid` | The assigned line has a `reference` or `strong` signal, no near-equal rival line exists, no other document competes for the line, and the payment isn't before the document date. Confidence is `high` when the signal is a reference or the payment came within 7 days, otherwise `medium`. |
| `uncertain` | A candidate exists, but at least one listed reason applies: a weak or no vendor signal, several lines within 10 points, another document scoring within 5 points on the same line, the only candidate already taken, no document date, or payment before the document date |
| `not_found` | No outgoing line has that amount inside the window |
| `unmatchable` | The document has no confirmed total (unclear or missing in document-reader) |

## Output

```jsonc
{
  "meta": {"bank_lines": 6, "outgoing_bank_lines": 5, "documents": 6,
           "status_counts": {"paid": 2, "uncertain": 2, "not_found": 1, "unmatchable": 1},
           "settings": {...}, "warnings": []},
  "documents": [{
    "id": "verksted.pdf", "vendor": "Verksted Service AS", "date": "2025-03-10", "amount": 6000.0,
    "status": "paid", "confidence": "high",
    "match": {"bank_line": "row2", "date": "2025-03-24", "amount": -6000.0, "text": "...",
              "days_after_document": 14, "vendor_signal": "reference", "score": 85.3},
    "candidates": [],                // other lines that also fit
    "reasons": []                    // why uncertain / not found
  }],
  "unmatched_outgoing_bank_lines": [...]   // payments with no document: missing bilag?
}
```

## Presenting results

- Show a table with the columns Document, Amount, Status, Bank date and Bank text, and put the `uncertain` rows first, each with its reasons.
- For `uncertain` rows, show the candidates and ask the user to confirm. Never upgrade a row to paid yourself.
- List `unmatched_outgoing_bank_lines` as payments that may be **missing a bilag**.
- Mention that combined payments (one bank line paying several invoices) and partial payments are not detected. Those invoices show as `not_found` or `uncertain`.

## Tests

```bash
python .claude/skills/bank-matcher/tests/test_match_bank.py -v
```
