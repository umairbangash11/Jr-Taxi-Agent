#!/usr/bin/env python3
"""Build balanced JR Taxi journal entries (bilag) from document-reader + saft-parser output.

Posting convention: gross amount + MK (VAT code) on the expense line; the accounting
system splits out input VAT. Credit side: payable account (2400) + supplier for a
faktura, configurable account (default 1920) for an already-paid kvittering.

Every bilag gets a status:
  ready         lines built, balanced, nothing needs a human
  needs_review  draft lines built, but something must be confirmed (see review_reasons)
  blocked       no trustworthy lines can be built (mixed VAT, unknown total, unbalanced...)

Usage:
  python build_entry.py --document doc.json --saft saft.json [--config cfg.json] [-o out.json] [--csv out.csv]
  Human resolution (single document only):
    --override total_amount=1250,00 --override date=2025-03-10 ...
    --expense-account 7000 --mk 1 --loyve "EL 12345" --bil AB12345
    --line 7000:1:800,00 --line 7140:11:450,00     (manual split, gross amounts)

Exit codes: 0 processed (check each bilag "status"), 1 usage/input error.
"""

import argparse
import csv
import json
import re
import sys
from decimal import Decimal, InvalidOperation

DEFAULT_CONFIG = {
    "company": "JR Taxi",
    "payable_account": "2400",
    "paid_receipt_credit_account": "1920",
    "loyver": [],                       # [{"loyve": "EL 12345", "bil": "AB12345"}]
    "default_loyve": None,              # set only if every cost belongs to one løyve
    "vat_code_by_rate": {},             # {"25": "1"} overrides SAF-T derived MK codes
    "ignore_account_prefixes": ["27"],  # never pick VAT accounts as expense account
    "min_mapping_share": 0.6,           # top account must have >= 60% of supplier's invoices
    "review_above_amount": 30000,       # aktiveringsgrense: may be a fixed asset
}
# Norwegian standard tax codes for deductible domestic purchases -> rate.
INPUT_STANDARD_CODES = {"1": Decimal("25"), "11": Decimal("15"), "12": Decimal("11.11"),
                        "13": Decimal("12"), "0": Decimal("0")}
OVERRIDABLE = ("date", "total_amount", "vat_rate", "document_type", "vendor_name",
               "vendor_org_number", "invoice_number")
CENT = Decimal("0.01")


class InputError(Exception):
    pass


def dec(value):
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", ".")).quantize(CENT)
    except InvalidOperation:
        raise InputError(f"Not an amount: {value!r}")


def rate_key(value):
    d = Decimal(str(value).replace(",", "."))
    return str(d.quantize(Decimal(1)) if d == d.to_integral_value() else d.normalize())


def num(d):
    return None if d is None else float(d)


def _norm_name(s):
    s = re.sub(r"\b(AS|ASA|ANS|DA|ENK|NUF|SA)\b\.?", "", s or "", flags=re.I)
    return re.sub(r"[^0-9a-zæøå]", "", s.casefold())


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _compact(s):
    return re.sub(r"[\s\-]", "", s or "").upper()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

class Ledger:
    """Indexes over saft-parser output."""

    def __init__(self, saft):
        self.accounts = {a["id"]: a.get("description") for a in saft.get("gl_accounts", [])}
        self.vat_codes = saft.get("vat_codes", [])
        self.suppliers = saft.get("suppliers", [])
        self.mappings = {m["supplier_id"]: m for m in saft.get("supplier_account_mappings", [])}

    def find_supplier(self, name, org):
        """-> (supplier | None, how, reason)"""
        if org:
            hits = [s for s in self.suppliers if _digits(s.get("registration_number"))[-9:] == org]
            if len(hits) == 1:
                return hits[0], "org_number", None
            if len(hits) > 1:
                return None, None, f"Org number {org} matches several suppliers: " + \
                    ", ".join(s["id"] for s in hits)
        if name:
            key = _norm_name(name)
            hits = [s for s in self.suppliers if key and _norm_name(s.get("name")) == key]
            if len(hits) == 1:
                return hits[0], "name", None
            if len(hits) > 1:
                return None, None, f"Name '{name}' matches several suppliers"
        return None, None, f"Supplier not found in SAF-T (name={name!r}, org={org!r})"

    def expense_account(self, supplier_id, cfg):
        """-> (account | None, expected_mk_codes, reason | None)"""
        m = self.mappings.get(supplier_id)
        if not m:
            return None, [], f"No booking history for supplier {supplier_id}"
        ignored = tuple(cfg["ignore_account_prefixes"]) + (
            cfg["payable_account"], cfg["paid_receipt_credit_account"])
        cands = [e for e in m["expense_accounts"] if not e["account_id"].startswith(ignored)]
        if not cands:
            return None, [], f"Supplier {supplier_id} history has no expense accounts"
        total = sum(e["count"] for e in cands)
        top = cands[0]
        share = top["count"] / total
        if share < cfg["min_mapping_share"]:
            listing = ", ".join(f"{e['account_id']} ({e['count']}x)" for e in cands[:4])
            return None, [], (f"Supplier {supplier_id} is booked to several accounts "
                              f"({listing}); choose with --expense-account")
        return top["account_id"], top.get("tax_codes", []), None

    def mk_for_rate(self, rate, cfg):
        """-> (mk | None, reason | None)"""
        key = rate_key(rate)
        if key in cfg["vat_code_by_rate"]:
            return str(cfg["vat_code_by_rate"][key]), None
        target = Decimal(key)
        hits = []
        for c in self.vat_codes:
            std = c.get("standard_tax_code")
            if std not in INPUT_STANDARD_CODES or INPUT_STANDARD_CODES[std] != target:
                continue
            if c.get("percentage") is not None and Decimal(str(c["percentage"])) != target:
                continue
            if c.get("expiration_date"):
                continue
            if c["code"] not in hits:
                hits.append(c["code"])
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, f"No input-VAT MK code for {key}% in SAF-T or config"
        return None, f"Several MK codes for {key}%: {', '.join(hits)}; choose with --mk"


def find_loyve(text, cfg):
    """-> (loyve, bil, reason | None) using the configured løyve list."""
    entries = cfg["loyver"]
    if text:
        haystack = _compact(text)
        hits = [e for e in entries
                if (e.get("loyve") and _compact(e["loyve"]) in haystack)
                or (e.get("bil") and _compact(e["bil"]) in haystack)]
        uniq = {(e.get("loyve"), e.get("bil")) for e in hits}
        if len(uniq) == 1:
            loyve, bil = uniq.pop()
            return loyve, bil, None
        if len(uniq) > 1:
            return None, None, "Document mentions several løyver/biler: " + \
                ", ".join(sorted(f"{lo}/{b}" for lo, b in uniq))
    if cfg.get("default_loyve"):
        lo = cfg["default_loyve"]
        bil = next((e.get("bil") for e in entries if e.get("loyve") == lo), None)
        return lo, bil, None
    why = "no document text (run document-reader with --include-text)" if not text \
        else "no configured løyve or reg.nr found in document"
    return None, None, f"Løyve/Bil unknown: {why}"


# ---------------------------------------------------------------------------
# Bilag
# ---------------------------------------------------------------------------

def _apply_overrides(fields, overrides):
    fields = {k: dict(v) for k, v in fields.items()}
    for key, value in overrides.items():
        if key == "total_amount":
            value = num(dec(value))
        elif key == "vat_rate":
            value = num(Decimal(rate_key(value)))
        fields.setdefault(key, {}).update(value=value, status="ok", confidence="user",
                                          reason="Set by user", candidates=[])
    return fields


def _line(konto, ledger, mk=None, debet=None, kredit=None, loyve=None, bil=None,
          tekst=None, supplier_id=None):
    return {"konto": konto, "konto_navn": ledger.accounts.get(konto), "mk": mk,
            "debet": debet, "kredit": kredit, "loyve": loyve, "bil": bil,
            "tekst": tekst, "supplier_id": supplier_id}


def build_bilag(doc, ledger, cfg, overrides=None, expense_account=None, mk=None,
                loyve=None, bil=None, splits=None):
    overrides = overrides or {}
    review, blocked = [], []
    result = {"source_file": doc.get("file"), "status": None, "header": {}, "lines": [],
              "totals": None, "review_reasons": review, "blocked_reasons": blocked}

    if doc.get("status") != "ok" or not doc.get("fields"):
        blocked.append(f"Document status is {doc.get('status')!r}: "
                       + "; ".join(doc.get("flags") or [doc.get("error", "")]))
        result["status"] = "blocked"
        return result

    f = _apply_overrides(doc["fields"], overrides)
    val = lambda k: f.get(k, {}).get("value") if f.get(k, {}).get("status") == "ok" else None  # noqa: E731

    doc_type = val("document_type")
    total = dec(val("total_amount"))
    date = val("date")
    vendor = val("vendor_name")
    org = val("vendor_org_number")
    invoice_no = val("invoice_number")
    currency = f.get("total_amount", {}).get("currency")
    tekst = " ".join(str(p) for p in (vendor, invoice_no) if p) or None

    # -- hard blockers ------------------------------------------------------
    if total is None:
        blocked.append("Total amount not established: "
                       + (f.get("total_amount", {}).get("reason") or "missing")
                       + _cands(f, "total_amount") + "; set with --override total_amount=…")
    elif total <= 0:
        blocked.append(f"Total amount {total} is not positive (credit note?)")
    if doc_type not in ("faktura", "kvittering"):
        blocked.append("Document type unclear: "
                       + (f.get("document_type", {}).get("reason") or "missing")
                       + "; set with --override document_type=faktura|kvittering")
    vat = f.get("vat_rate", {})
    mixed = vat.get("status") == "unclear" and len(vat.get("candidates", [])) > 1
    if mixed and not splits:
        blocked.append(f"Mixed VAT rates {vat['candidates']}: split the document with "
                       "--line KONTO:MK:BRUTTO (one per rate)")

    # -- review items -------------------------------------------------------
    if date is None:
        review.append("Date missing/unclear" + _cands(f, "date"))
    if currency and currency != "NOK":
        review.append(f"Currency is {currency}; amounts must be converted to NOK")
    if total is not None and total >= Decimal(str(cfg["review_above_amount"])):
        review.append(f"Amount {total} ≥ {cfg['review_above_amount']}: check if this is a "
                      "fixed asset (driftsmiddel) rather than an expense")

    supplier, how, why = ledger.find_supplier(vendor, org)
    if not supplier:
        review.append(why)
    elif how == "name":
        review.append(f"Supplier matched by name only ({supplier['id']} {supplier['name']})")
    supplier_id = supplier["id"] if supplier else None
    if doc_type == "faktura" and not invoice_no:
        review.append("Invoice number missing/unclear" + _cands(f, "invoice_number"))

    lo, b, why = (loyve, bil, None) if (loyve or bil) else find_loyve(doc.get("text"), cfg)
    if why:
        review.append(why)

    # -- debit lines --------------------------------------------------------
    debit_lines = []
    if splits:
        for konto, line_mk, amount in splits:
            if konto not in ledger.accounts:
                review.append(f"Account {konto} not in chart of accounts")
            debit_lines.append(_line(konto, ledger, line_mk or None, amount, None, lo, b,
                                     tekst, None))
        if total is not None and sum(ln["debet"] for ln in debit_lines) != total:
            blocked.append(f"Split lines sum to {sum(ln['debet'] for ln in debit_lines)}, "
                           f"document total is {total}")
    elif not blocked:
        konto, expected_mk = expense_account, []
        if konto:
            if konto not in ledger.accounts:
                review.append(f"Account {konto} not in chart of accounts")
        elif supplier_id:
            konto, expected_mk, why = ledger.expense_account(supplier_id, cfg)
            if why:
                review.append(why)
        else:
            review.append("Expense account unknown (no supplier); set with --expense-account")

        line_mk = mk
        if not line_mk:
            rate = val("vat_rate")
            if rate is None:
                review.append("VAT rate missing/unclear" + _cands(f, "vat_rate")
                              + "; set with --mk or --override vat_rate=…")
            else:
                line_mk, why = ledger.mk_for_rate(rate, cfg)
                if why:
                    review.append(why)
        if line_mk and expected_mk and line_mk not in expected_mk:
            review.append(f"MK {line_mk} differs from supplier history on {konto} "
                          f"(usually MK {', '.join(expected_mk)})")
        debit_lines.append(_line(konto, ledger, line_mk, total, None, lo, b, tekst, None))

    # -- credit line --------------------------------------------------------
    if not blocked:
        if doc_type == "faktura":
            credit_konto, credit_supplier = cfg["payable_account"], supplier_id
            if not supplier_id:
                review.append(f"Faktura credited to {credit_konto} without supplier ID")
        else:
            # Paid receipt does not touch leverandørreskontro.
            credit_konto, credit_supplier = cfg["paid_receipt_credit_account"], None
        credit = _line(credit_konto, ledger, None, None, total, None, None, tekst,
                       credit_supplier)
        result["lines"] = debit_lines + [credit]
        for ln in result["lines"]:
            if not ln["konto"]:
                review.append("A line has no account")
                break

    # -- balance (always enforced) -----------------------------------------
    if result["lines"]:
        d = sum((ln["debet"] or Decimal(0)) for ln in result["lines"])
        k = sum((ln["kredit"] or Decimal(0)) for ln in result["lines"])
        result["totals"] = {"debet": num(d), "kredit": num(k), "balanced": d == k}
        if d != k:
            blocked.append(f"Unbalanced: debet {d} ≠ kredit {k}")
        for ln in result["lines"]:
            ln["debet"], ln["kredit"] = num(ln["debet"]), num(ln["kredit"])

    result["header"] = {"date": date, "document_type": doc_type, "vendor_name": vendor,
                        "supplier_id": supplier_id,
                        "invoice_number": invoice_no, "total_amount": num(total),
                        "currency": currency, "description": tekst}
    if blocked:
        result["status"], result["lines"], result["totals"] = "blocked", [], None
    else:
        result["status"] = "needs_review" if review else "ready"
    return result


def _cands(fields, key):
    c = fields.get(key, {}).get("candidates") or []
    return f" (candidates: {', '.join(str(x) for x in c)})" if c else ""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_split(raw):
    parts = raw.split(":")
    if len(parts) != 3 or not parts[0]:
        raise InputError(f"--line must be KONTO:MK:BRUTTO, got {raw!r}")
    return parts[0], parts[1], dec(parts[2])


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read {path}: {exc}")


def load_config(path):
    cfg = dict(DEFAULT_CONFIG)
    if path:
        user = load_json(path)
        unknown = set(user) - set(DEFAULT_CONFIG) - {"_comment"}
        if unknown:
            raise InputError(f"Unknown config keys: {', '.join(sorted(unknown))}")
        cfg.update(user)
    cfg["vat_code_by_rate"] = {rate_key(k): v for k, v in cfg["vat_code_by_rate"].items()}
    return cfg


def fmt_no(value):
    return "" if value is None else f"{value:.2f}".replace(".", ",")


def write_csv(path, bilag_list):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Bilag", "Dato", "Konto", "MK", "Debet", "Kredit", "Løyve", "Bil", "Tekst"])
        for n, b in enumerate(bilag_list, 1):
            for ln in b["lines"]:
                w.writerow([n, b["header"]["date"] or "", ln["konto"] or "", ln["mk"] or "",
                            fmt_no(ln["debet"]), fmt_no(ln["kredit"]), ln["loyve"] or "",
                            ln["bil"] or "", ln["tekst"] or ""])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build balanced JR Taxi bilag.")
    ap.add_argument("--document", required=True, help="document-reader JSON output")
    ap.add_argument("--saft", required=True, help="saft-parser JSON output")
    ap.add_argument("--config", help="JR Taxi config JSON (see config.example.json)")
    ap.add_argument("-o", "--output", help="Write JSON here instead of stdout")
    ap.add_argument("--csv", help="Also write lines as semicolon CSV (only non-blocked bilag)")
    ap.add_argument("--override", action="append", default=[], metavar="FIELD=VALUE")
    ap.add_argument("--expense-account")
    ap.add_argument("--mk")
    ap.add_argument("--loyve")
    ap.add_argument("--bil")
    ap.add_argument("--line", action="append", default=[], metavar="KONTO:MK:BRUTTO")
    args = ap.parse_args(argv)

    try:
        docs = load_json(args.document)
        docs = docs.get("documents", [docs]) if isinstance(docs, dict) else docs
        ledger = Ledger(load_json(args.saft))
        cfg = load_config(args.config)
        overrides = {}
        for item in args.override:
            key, sep, value = item.partition("=")
            if not sep or key not in OVERRIDABLE:
                raise InputError(f"--override must be FIELD=VALUE with FIELD in {OVERRIDABLE}")
            overrides[key] = value
        splits = [parse_split(s) for s in args.line]
        manual = overrides or splits or args.expense_account or args.mk or args.loyve or args.bil
        if manual and len(docs) != 1:
            raise InputError("Overrides/--line need a document file with exactly one document")
        out = [build_bilag(d, ledger, cfg, overrides, args.expense_account, args.mk,
                           args.loyve, args.bil, splits) for d in docs]
    except InputError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    text = json.dumps({"bilag": out}, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    if args.csv:
        write_csv(args.csv, [b for b in out if b["status"] != "blocked"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
