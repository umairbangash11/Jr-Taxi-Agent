# Quickstart: Phase 1 — SAF-T Reader

## Run on the sample

```bash
python phase-1/saft_reader.py samples/saft_sample.xml
# saft_data.json: … accounts, … VAT codes, … suppliers, … mapped / … unknown
```

Open `phase-1/saft_data.json` and check (this is the human-review step of the exit criteria):

1. `accounts` contains e.g. `7026 Reparasjoner`, `7155 Bespisning/Mat`, `1930 Bedriftskonto`.
2. `vat_codes` starts with the blank entry (`""` = 0 %), then e.g. `2` = 25, `12` = 12.
3. `suppliers` contains NIO, ONEPARK, RA FORSIKRING with their IDs.
4. `supplier_account_map`: NIO → 7033, ONEPARK → 7161, RA FORSIKRING → 7027; the ambiguous and
   never-booked suppliers show `"account_id": "unknown"` with a `reason` and `candidates`.
5. `summary.unknown_values` counts the deliberately incomplete records; `summary.warnings` is
   understandable.

## Run the tests

```bash
python -m pytest tests/phase-1 -v
```

## Use from later phases

```python
import json
data = json.load(open("phase-1/saft_data.json", encoding="utf-8"))
valid_accounts = {a["id"] for a in data["accounts"]}          # constitution II: only these codes
nio = next(m for m in data["supplier_account_map"] if m["supplier_name"] == "NIO")
if nio["account_id"] == "unknown":
    ...  # flag "needs review" — never guess
```
