---
name: qa-validator
description: Quality gate for generated JR Taxi journal entries (entry-builder bilag) before they are shown to a human or exported. Verifies debet = kredit, account codes exist in SAF-T, MK/VAT codes exist, are valid on the bilag date and are input codes on cost lines, required fields (date, amount, løyve) are present, suppliers exist, løyve/bil match config, and no duplicate invoices. Blocks invalid entries. Use after entry-builder and before presenting or exporting any bilag.
---

# QA Validator

`scripts/validate_entries.py` is the final gate between **entry-builder** and the human.
Every bilag gets `qa_status: passed | blocked`. **Any error blocks the bilag. Warnings never block.**
Only a `passed` bilag may be presented as a postable entry or exported.

## Usage

```bash
python .claude/skills/qa-validator/scripts/validate_entries.py \
    --entries bilag.json --saft saft.json --config jr_taxi_config.json \
    -o qa.json --csv godkjent.csv
```
- `--config` is the **same file as entry-builder's**. QA uses its `loyver` and `payable_account` and ignores the other keys.
- `--csv` writes **only the bilag that passed**. The layout is the same as entry-builder's CSV.
- Exit `0` means every bilag passed, `2` means at least one is blocked, and `1` means an input error. The exit code can be used directly as a pipeline gate.

## Checks

| Code | Severity | Rule |
|---|---|---|
| `UNBALANCED` | error | Σ debet ≠ Σ kredit, checked in exact decimals |
| `TOTALS_INCONSISTENT` | error | The bilag says `balanced: true` but its lines don't balance |
| `AMOUNT_MISMATCH` | error | Σ debet ≠ header `total_amount` |
| `LINE_AMOUNT_INVALID` | error | A line has both debet and kredit, neither, or a value ≤ 0 or not a number |
| `NO_LINES` | error | The bilag has no lines |
| `MISSING_ACCOUNT` / `UNKNOWN_ACCOUNT` | error | The konto is empty, or not in SAF-T `gl_accounts` |
| `INVALID_MK` | error | The MK isn't in the SAF-T tax table, or isn't valid on the bilag date (effective or expiration date) |
| `OUTPUT_MK_ON_COST` | error | An output (sales) VAT code, such as standard code 3 or 33, sits on a debit cost line (4xxx–7xxx) |
| `MISSING_MK` | error | A P&L line (3xxx–8xxx) has no MK. Costs without VAT must use the "no VAT" code, such as 0. |
| `MISSING_DATE` / `INVALID_DATE` / `FUTURE_DATE` | error | The date is missing, not in YYYY-MM-DD format, or later than today |
| `MISSING_AMOUNT` / `INVALID_AMOUNT` | error | The header total is missing or not positive |
| `FOREIGN_CURRENCY` | error | The currency isn't NOK |
| `MISSING_LOYVE` | error | A P&L line has no løyve |
| `UNKNOWN_LOYVE` / `BIL_MISMATCH` | error | The løyve isn't in the config, or the bil doesn't belong to that løyve |
| `MISSING_SUPPLIER` / `UNKNOWN_SUPPLIER` | error | A credit to the payable account (2400) has no supplier ID, or the supplier isn't in SAF-T |
| `DUPLICATE_INVOICE` | error | The same supplier and invoice number appear earlier in the batch |
| `UPSTREAM_BLOCKED` | error | entry-builder already blocked the bilag, and its reasons are carried over |
| `UPSTREAM_REVIEW` | warning | entry-builder's review reasons are passed through for the human |
| `MISSING_BIL` | warning | A løyve is present without a bil |
| `LOYVE_UNCHECKED` | warning | No løyver are configured, so the løyve value can't be verified |
| `MK_ON_BALANCE_LINE` | warning | An MK sits on a balance account |
| `POSSIBLE_DUPLICATE` | warning | Same vendor, date and amount, with no invoice number to tell them apart |

Every error and warning has the shape `{"code", "message", "line"}`, where `line` is the 1-based line number or null for header-level problems.

## Output

`{"summary": {bilag, passed, blocked, error_codes: {CODE: n}}, "bilag": [<entry-builder bilag> + qa_status, qa_errors, qa_warnings]}`

## Presenting results

- **Passed:** show the lines (Konto, MK, Debet, Kredit, Løyve, Bil) together with any warnings.
- **Blocked:** never show these as entries ready to post. List the errors in plain language, and say how to fix each one with entry-builder overrides (`--expense-account`, `--mk`, `--loyve`, `--bil`, `--override …`, `--line …`). Re-run entry-builder and then QA.
- Never edit `qa.json` or the lines by hand to make a bilag pass.

## Tests

```bash
python .claude/skills/qa-validator/tests/test_validate_entries.py -v
```
The tests cover every error code, the CSV that holds only passed bilag, the exit codes, and a pipeline test on real entry-builder output.
