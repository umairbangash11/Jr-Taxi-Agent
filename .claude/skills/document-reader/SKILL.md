---
name: document-reader
description: Read accounting documents (PDF invoices/fakturaer and receipts/kvitteringer, including scanned PDFs and photos) and extract vendor name, org number, date, total amount, VAT/MVA rate, invoice number and document type (faktura vs kvittering) as JSON, flagging unclear or missing fields instead of guessing. Use whenever the user provides a bilag, invoice, receipt, or asks what a document says for bookkeeping.
---

# Document Reader (fakturaer og kvitteringer)

`scripts/read_document.py` turns a document into text and then applies deterministic Norwegian
and English rules to pick out the fields. **The core rule is not to guess.** When a field
conflicts, has weak evidence, or isn't there, it gets `"value": null` and status `unclear` or
`missing`, together with any `candidates` that were found and a `reason`.
Pass these flags on to the user. Never fill in a value the document doesn't support.

## Usage

```bash
python .claude/skills/document-reader/scripts/read_document.py <file.pdf> [more.pdf ...] -o out.json
```
| Option | Purpose |
|---|---|
| `-o FILE` | Write JSON to a file (otherwise stdout) |
| `--include-text` | Add the extracted raw text to each document (useful for checking evidence) |
| `--no-ocr` | Skip OCR even if it is available |
| `--max-pages N` | Maximum number of pages to OCR (default 10) |
| `--text-file T --source-name X` | Run the field rules on text you already have (see the vision fallback) |

Exit code `0` means the documents were processed. Check each document's `status`, which is
`ok`, `needs_ocr` or `error`. Accepted inputs are `.pdf`, `.png`, `.jpg`, `.tif` and `.webp`.
Images can only be read when OCR is available.

## Text extraction backends (all optional)

They are tried in order, and the first one that returns at least 20 characters is used:
1. `pdfplumber` → 2. `pypdf` → 3. the `pdftotext` CLI (poppler, which ships with Git for Windows)
4. OCR: `pytesseract` + `pypdfium2`, or the `tesseract` + `pdftoppm` CLIs. It uses `nor+eng` when those language packs are installed.

`extraction.method` shows which backend was used, and `extraction.tried` shows why the others
were skipped. When OCR is used, no field is rated above `medium` confidence.
Optional installs: `pip install pdfplumber pypdfium2 pytesseract` and Tesseract with the `nor` language pack.
Ask the user before installing anything.

## Vision fallback when `status` is `needs_ocr`

A scanned PDF without OCR software has no text layer. In that case:
1. Open the file with the **Read** tool (it renders PDF and image pages) and copy the text
   **exactly as printed**, line by line, keeping the labels next to their values. Don't correct or complete anything.
2. Save that text to a `.txt` file in the scratchpad directory.
3. Run `read_document.py --text-file <that.txt> --source-name <original.pdf>`.
4. Tell the user that the fields were read visually. Treat every value as `medium` confidence at best.

The field rules then decide from the transcription, so you never decide yourself which number is the total.

## Output (per document)

```jsonc
{
  "file": "bilag_0417.pdf",
  "status": "ok",                      // ok | needs_ocr | error
  "extraction": {"method": "pdftotext", "pages": 1, "ocr": false, "tried": [...]},
  "needs_review": false,               // true if any flag is present
  "flags": [],                         // e.g. "total_amount: unclear - Conflicting total amount values found"
  "fields": {
    "document_type":     {"value": "faktura", "status": "ok", "confidence": "medium", "evidence": "keyword scores: ...", "candidates": [], "reason": null},
    "vendor_name":       {"value": "Verksted Service AS", "status": "ok", "confidence": "high", ...},
    "vendor_org_number": {"value": "912345602", ...},          // mod-11 validated
    "date":              {"value": "2025-03-10", ...},         // ISO; invoice/purchase date, never due date
    "invoice_number":    {"value": "2025-0417", ...},
    "total_amount":      {"value": 6000, "currency": "NOK", ...},  // amount incl. VAT
    "vat_rate":          {"value": 25, ...}                    // percent
  }
}
```
Every field has the same shape: `value`, `status` (`ok`/`unclear`/`missing`), `confidence`
(`high`/`medium`/`low`/null), `evidence` (the source line), `candidates`, and `reason`.

## Extraction rules in brief

- **document_type:** Keywords are scored. Invoice signs include *Faktura*, *Fakturanr*, *Forfall*,
  *KID* and *kontonummer*. Receipt signs include *Kvittering*, *Bankkort*, *Kontant*, *Betalt*,
  *Terminal* and *Vipps*. A title near the top of the page adds weight. The winner needs a margin
  of at least 2, otherwise the field is `unclear`. A *kreditnota* is always `unclear`.
- **vendor_name:** The candidate is a name with a legal suffix (AS, ASA, ENK, NUF, Ltd...). Names
  near the top of the page and near a valid org number rank higher. Anything in a buyer block
  (*Faktura til*, *Kunde*, *Bill to*...) is ignored. A tie is `unclear`. If no name has a suffix,
  the first line is offered as a candidate only, never as the value.
- **date:** Dates labelled *Fakturadato*, *Kjøpsdato* or *Invoice date* rank highest, then *Dato* or *Date*.
  Dates labelled *Forfall*, *Due*, *Levering* or *Periode* are excluded. This works for both
  `Fakturadato: x  Forfallsdato: y` on one line and labels in a header row above the dates.
  Several unlabelled dates are `unclear`. `DD/MM` versus `MM/DD` ambiguity lowers confidence.
- **total_amount:** Label tiers are tried in order: *Å betale / Til betaling / Sum inkl. mva /
  Totalbeløp*, then *Total(t) / Betalt / Bankkort*, then *Sum / Beløp*. The last tier on its own
  is `unclear`. Lines with *eks. mva*, *herav mva*, *grunnlag* or *rabatt* are excluded, as are
  percentages, dates and org numbers. Different values under the same label tier make the field `unclear`.
  Amounts in `1 234,50`, `1.234,50`, `1,234.50` and `845,-` formats are understood. Any currency
  other than NOK is flagged.
- **vat_rate:** Only percentages on lines that mention MVA, moms or VAT count. Several rates are
  `unclear` and listed as candidates, because mixed-rate documents need splitting. A rate outside
  0/6/8/10/11.11/12/15/25 is `unclear` because it is probably an OCR error. An explicit *fritatt for mva* gives 0.
- **invoice_number:** Labels used are *Fakturanr*, *Fakturanummer*, *Invoice no*, *Kvitteringsnr*
  and *Bongnr*. Conflicting numbers are `unclear`. A receipt without a number gets status
  `missing`, but it is not flagged.

## Working with the result

- Show the user a short table of the fields, and list every flag together with its candidates and evidence.
- Ask the user to settle the `unclear` fields. Don't pick a candidate yourself.
- If the **saft-parser** output is available, match `vendor_org_number` against
  `suppliers[].registration_number` to find the supplier ID and its usual accounts.

## Tests

```bash
python .claude/skills/document-reader/tests/test_read_document.py -v
```
The fixtures are an invoice, a taxi receipt at 12 % VAT, and a deliberately unclear receipt.
The PDF test builds a PDF with a text layer at run time and is skipped if no PDF backend is available.
