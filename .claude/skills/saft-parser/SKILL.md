---
name: saft-parser
description: Parse Norwegian SAF-T Financial (Standard Audit File for Tax, v1.30, namespace urn:StandardAuditFile-Taxation-Financial:NO) XML files into structured JSON — GL accounts (kontoplan), MVA/VAT codes with percentages, suppliers (leverandører), and supplier→account mappings derived from GeneralLedgerEntries. Use whenever the user provides or mentions a SAF-T file, a Norwegian accounting export (.xml from Tripletex, Visma, PowerOffice, Fiken, etc.), or asks which accounts/VAT codes a supplier is usually booked to.
---

# SAF-T Parser (Norway, v1.30)

Turns a Norwegian SAF-T Financial XML export into JSON using
`scripts/parse_saft.py` (Python 3.8+, stdlib only; uses `defusedxml` if installed).
The file is streamed with `iterparse`, so large exports (GBs) are fine. Do **not**
read the XML into context yourself — run the script and work from its JSON.

## Usage

```bash
python .claude/skills/saft-parser/scripts/parse_saft.py <file.xml> -o <out.json>
```

Options:
- `-o, --output FILE` — write JSON to a file (recommended for big files; otherwise stdout)
- `--compact` — minified JSON
- `--allow-other-namespace` — parse even when the root namespace isn't the Norwegian one (adds a warning)

Exit codes: `0` success · `1` unreadable file / malformed XML · `2` not a Norwegian SAF-T file
(root isn't `<AuditFile>` or the namespace is wrong). On error, the script writes `{"error": "..."}` to stderr.

After running, check `meta.warnings` and `meta.counts` and tell the user about anything unusual,
such as a version other than 1.30, suppliers used in entries but missing from MasterFiles, or zero transactions.

## Namespace handling

SAF-T NO v1.30 uses the default or prefixed namespace `urn:StandardAuditFile-Taxation-Financial:NO`.
The parser reads the namespace from the root element and qualifies every lookup with it, so
any prefix (`n1:`, `ns0:`, or none) works. A different namespace is rejected unless
`--allow-other-namespace` is passed. `Header/AuditFileVersion` is checked, and a value other than `1.30`
produces a warning, but the file is still parsed.

## Output schema

```jsonc
{
  "meta": {
    "namespace": "urn:StandardAuditFile-Taxation-Financial:NO",
    "audit_file_version": "1.30",
    "company": {"name": "...", "registration_number": "..."},
    "selection_criteria": {"period_start": "1", "period_start_year": "2025", ...},
    "default_currency_code": "NOK",
    "software": {"company_name": "...", "id": "...", "version": "..."},
    "counts": {"gl_accounts": 0, "vat_codes": 0, "suppliers": 0, "transactions": 0, "suppliers_with_mappings": 0},
    "warnings": [],
    "source_file": "..."
  },
  "gl_accounts": [
    {"id": "7000", "description": "Drivstoff", "standard_account_id": "70",
     "grouping_category": null, "grouping_code": null, "account_type": "GL"}
  ],
  "vat_codes": [
    {"code": "1", "percentage": 25, "description": "Inngående mva, høy sats",
     "standard_tax_code": "1", "tax_type": "MVA", "effective_date": null, "expiration_date": null}
  ],
  "suppliers": [
    {"id": "50001", "name": "Circle K Norge AS", "registration_number": "911222333", "account_id": "2400"}
  ],
  "supplier_account_mappings": [
    {
      "supplier_id": "50001", "supplier_name": "Circle K Norge AS",
      "invoice_transactions": 1, "other_transactions": 1,
      "payable_accounts": [{"account_id": "2400", "account_description": "Leverandørgjeld", "count": 2}],
      "expense_accounts": [
        {"account_id": "7000", "account_description": "Drivstoff", "count": 1,
         "total_debit": 1000, "total_credit": 0, "tax_codes": ["1"]},
        {"account_id": "2710", "account_description": "Inngående merverdiavgift", "count": 1,
         "total_debit": 250, "total_credit": 0, "tax_codes": []}
      ],
      "primary_expense_account": "7000"
    }
  ]
}
```

`percentage` is `null` when a tax code has no `TaxPercentage`. For example, some exports describe
reverse-charge or exempt codes with only `BaseRate`. Amounts are JSON numbers rounded to 2 decimals.

## How supplier→account mappings are derived

For each `GeneralLedgerEntries/Journal/Transaction`:

1. Lines with a `SupplierID` are the supplier's **payable** (reskontro) lines. Their `AccountID` goes into
   `payable_accounts`. If only the transaction carries a `SupplierID`, it is used instead.
2. If the supplier lines are **net credit**, the transaction counts as a supplier **invoice**. Every
   other line's `AccountID` goes into `expense_accounts`, together with its count, debit and credit
   totals, and the `TaxInformation/TaxCode` values seen on those lines.
3. Net-debit transactions, such as payments or credit notes, are only counted in `other_transactions`.
   This keeps bank accounts (19xx) out of the expense mapping.
4. A transaction that names several different suppliers only updates their payable accounts.

`expense_accounts` is sorted by frequency first and then by total debit. Input-VAT accounts
(such as 2710) appear in this list because they are counter lines on invoices. Skip them when
you suggest a cost account. `primary_expense_account` is the first entry in the list.

## Tests

```bash
python .claude/skills/saft-parser/tests/test_parse_saft.py -v
```
The tests use `tests/fixtures/sample_v130.xml`, a minimal valid v1.30 file.
