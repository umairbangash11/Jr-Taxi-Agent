#!/usr/bin/env python3
"""Quality gate for entry-builder bilag before they reach a human.

Each bilag gets qa_status "passed" or "blocked". Any error blocks; warnings never do.
Checks: debet = kredit, line amounts well-formed, accounts exist in SAF-T, MK codes exist /
are valid on the bilag date / are input codes on cost lines, required fields (date, amount,
løyve on P&L lines), supplier exists for faktura, løyve/bil consistent with config,
duplicate invoices in the batch.

Usage:
  python validate_entries.py --entries bilag.json --saft saft.json [--config jr_taxi_config.json]
                             [-o qa.json] [--csv passed.csv]

Exit codes: 0 all passed, 2 at least one bilag blocked, 1 input error.
"""

import argparse
import csv
import datetime as dt
import json
import sys
from decimal import Decimal, InvalidOperation

CENT = Decimal("0.01")
OUTPUT_STANDARD_CODES = {"3", "31", "32", "33", "5", "51", "52", "6"}  # utgående / salg


class InputError(Exception):
    pass


def amount(v):
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v)).quantize(CENT)
    except InvalidOperation:
        return "invalid"


def is_pl(konto):
    """Resultatkonto (classes 3-8) carry MK and løyve; balance accounts don't."""
    return bool(konto) and konto[0] in "345678"


def is_cost(konto):
    return bool(konto) and konto[0] in "4567"


def compact(s):
    return "".join((s or "").split()).replace("-", "").upper()


class Validator:
    def __init__(self, saft, cfg, today=None):
        self.accounts = {a["id"] for a in saft.get("gl_accounts", [])}
        self.vat = {}
        for c in saft.get("vat_codes", []):
            self.vat.setdefault(str(c["code"]), []).append(c)
        self.suppliers = {s["id"] for s in saft.get("suppliers", [])}
        self.payable = str(cfg.get("payable_account", "2400"))
        self.loyver = {compact(e["loyve"]): e for e in cfg.get("loyver", []) if e.get("loyve")}
        self.today = today or dt.date.today()
        if not self.accounts:
            raise InputError("SAF-T JSON has no gl_accounts; cannot validate account codes")

    def _mk_valid_on(self, mk, date):
        """-> None if valid, else error message."""
        entries = self.vat.get(mk)
        if not entries:
            return f"MK {mk} does not exist in SAF-T tax table"
        if date is None:
            return None
        for e in entries:
            start = e.get("effective_date")
            end = e.get("expiration_date")
            if (not start or start <= date.isoformat()) and (not end or date.isoformat() <= end):
                return None
        return f"MK {mk} is not valid on {date.isoformat()} (effective/expiration dates)"

    def validate(self, b, seen):
        errors, warnings = [], []
        err = lambda code, msg, line=None: errors.append(  # noqa: E731
            {"code": code, "message": msg, "line": line})
        warn = lambda code, msg, line=None: warnings.append(  # noqa: E731
            {"code": code, "message": msg, "line": line})

        status = b.get("status")
        if status == "blocked":
            for r in b.get("blocked_reasons", []) or ["(no reason given)"]:
                err("UPSTREAM_BLOCKED", r)
            return errors, warnings
        for r in b.get("review_reasons", []):
            warn("UPSTREAM_REVIEW", r)

        h = b.get("header") or {}
        lines = b.get("lines") or []

        # -- header ---------------------------------------------------------
        date = None
        if not h.get("date"):
            err("MISSING_DATE", "Bilag has no date")
        else:
            try:
                date = dt.date.fromisoformat(h["date"])
            except (TypeError, ValueError):
                err("INVALID_DATE", f"Date {h['date']!r} is not YYYY-MM-DD")
            else:
                if date > self.today:
                    err("FUTURE_DATE", f"Date {date} is in the future")
        total = amount(h.get("total_amount"))
        if total is None:
            err("MISSING_AMOUNT", "Bilag has no total amount")
        elif total == "invalid" or total <= 0:
            err("INVALID_AMOUNT", f"Total amount {h.get('total_amount')!r} is not a positive number")
            total = None
        if h.get("currency") not in (None, "NOK"):
            err("FOREIGN_CURRENCY", f"Amounts are in {h['currency']}, must be NOK")

        # -- lines ----------------------------------------------------------
        if not lines:
            err("NO_LINES", "Bilag has no lines")
        debit_sum, credit_sum = Decimal(0), Decimal(0)
        for n, ln in enumerate(lines, 1):
            konto, mk = ln.get("konto"), ln.get("mk")
            d, k = amount(ln.get("debet")), amount(ln.get("kredit"))
            if "invalid" in (d, k) or (d is not None and d <= 0) or (k is not None and k <= 0):
                err("LINE_AMOUNT_INVALID", "Debet/kredit must be positive numbers", n)
                continue
            if (d is None) == (k is None):
                err("LINE_AMOUNT_INVALID", "Line must have exactly one of debet or kredit", n)
                continue
            debit_sum += d or 0
            credit_sum += k or 0

            if not konto:
                err("MISSING_ACCOUNT", "Line has no account", n)
            elif konto not in self.accounts:
                err("UNKNOWN_ACCOUNT", f"Account {konto} does not exist in SAF-T chart", n)

            if mk not in (None, ""):
                mk = str(mk)
                msg = self._mk_valid_on(mk, date)
                if msg:
                    err("INVALID_MK", msg, n)
                elif is_cost(konto) and d and any(
                        e.get("standard_tax_code") in OUTPUT_STANDARD_CODES for e in self.vat[mk]):
                    err("OUTPUT_MK_ON_COST", f"MK {mk} is an output (sales) VAT code on cost "
                                             f"account {konto}", n)
                if konto and not is_pl(konto):
                    warn("MK_ON_BALANCE_LINE", f"MK {mk} on balance account {konto}", n)
            elif is_pl(konto):
                err("MISSING_MK", f"P&L account {konto} has no MK (use the 'no VAT' code if "
                                  "the cost has no VAT)", n)

            if is_pl(konto):
                self._check_loyve(ln, n, err, warn)

            if konto == self.payable and k:
                sid = ln.get("supplier_id")
                if not sid:
                    err("MISSING_SUPPLIER", f"Credit to payable account {konto} without "
                                            "supplier ID", n)
                elif sid not in self.suppliers:
                    err("UNKNOWN_SUPPLIER", f"Supplier {sid} does not exist in SAF-T", n)

        if lines and debit_sum != credit_sum:
            err("UNBALANCED", f"Debet {debit_sum} ≠ kredit {credit_sum} "
                              f"(difference {debit_sum - credit_sum})")
        if total is not None and lines and debit_sum != total:
            err("AMOUNT_MISMATCH", f"Lines total {debit_sum} but bilag total is {total}")
        totals = b.get("totals") or {}
        if totals and totals.get("balanced") is True and debit_sum != credit_sum:
            err("TOTALS_INCONSISTENT", "Bilag claims balanced but lines are not")

        # -- duplicates -----------------------------------------------------
        if h.get("invoice_number") and (h.get("supplier_id") or h.get("vendor_name")):
            key = ("inv", h.get("supplier_id") or h.get("vendor_name"), h["invoice_number"])
            if key in seen:
                err("DUPLICATE_INVOICE", f"Invoice {h['invoice_number']} from {key[1]} also "
                                         f"in {seen[key]}")
            else:
                seen[key] = b.get("source_file")
        elif h.get("date") and total is not None:
            key = ("soft", h.get("vendor_name"), h["date"], str(total))
            if key in seen:
                warn("POSSIBLE_DUPLICATE", f"Same vendor, date and amount as {seen[key]}")
            else:
                seen[key] = b.get("source_file")
        return errors, warnings

    def _check_loyve(self, ln, n, err, warn):
        lo, bil = ln.get("loyve"), ln.get("bil")
        if not lo:
            err("MISSING_LOYVE", "P&L line has no løyve", n)
            return
        if not self.loyver:
            warn("LOYVE_UNCHECKED", "No løyver configured; løyve value not verified", n)
            return
        entry = self.loyver.get(compact(lo))
        if not entry:
            err("UNKNOWN_LOYVE", f"Løyve {lo} is not in the configured løyve list", n)
        elif not bil:
            warn("MISSING_BIL", f"No bil on line (løyve {lo} → {entry.get('bil')})", n)
        elif entry.get("bil") and compact(entry["bil"]) != compact(bil):
            err("BIL_MISMATCH", f"Bil {bil} does not belong to løyve {lo} "
                                f"(configured: {entry['bil']})", n)


def validate_all(bilag_list, saft, cfg, today=None):
    v = Validator(saft, cfg, today)
    seen, results = {}, []
    for b in bilag_list:
        errors, warnings = v.validate(b, seen)
        results.append({**b, "qa_status": "blocked" if errors else "passed",
                        "qa_errors": errors, "qa_warnings": warnings})
    summary = {"bilag": len(results),
               "passed": sum(r["qa_status"] == "passed" for r in results),
               "blocked": sum(r["qa_status"] == "blocked" for r in results),
               "error_codes": {}}
    for r in results:
        for e in r["qa_errors"]:
            summary["error_codes"][e["code"]] = summary["error_codes"].get(e["code"], 0) + 1
    return {"summary": summary, "bilag": results}


def fmt_no(v):
    return "" if v is None else f"{Decimal(str(v)):.2f}".replace(".", ",")


def write_csv(path, results):
    """Same layout as entry-builder --csv, but only bilag that passed QA."""
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Bilag", "Dato", "Konto", "MK", "Debet", "Kredit", "Løyve", "Bil", "Tekst"])
        for n, b in enumerate((r for r in results if r["qa_status"] == "passed"), 1):
            for ln in b["lines"]:
                w.writerow([n, b["header"]["date"], ln.get("konto") or "", ln.get("mk") or "",
                            fmt_no(ln.get("debet")), fmt_no(ln.get("kredit")),
                            ln.get("loyve") or "", ln.get("bil") or "", ln.get("tekst") or ""])


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read {path}: {exc}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="QA gate for JR Taxi bilag.")
    ap.add_argument("--entries", required=True, help="entry-builder JSON ({'bilag': [...]})")
    ap.add_argument("--saft", required=True, help="saft-parser JSON")
    ap.add_argument("--config", help="entry-builder config (løyver, payable_account)")
    ap.add_argument("-o", "--output", help="Write JSON report here instead of stdout")
    ap.add_argument("--csv", help="Write CSV containing only bilag that passed")
    args = ap.parse_args(argv)
    try:
        entries = load_json(args.entries)
        if not isinstance(entries, dict) or "bilag" not in entries:
            raise InputError("--entries must be entry-builder output with a 'bilag' list")
        cfg = load_json(args.config) if args.config else {}
        result = validate_all(entries["bilag"], load_json(args.saft), cfg)
    except InputError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(out)
    if args.csv:
        write_csv(args.csv, result["bilag"])
    return 2 if result["summary"]["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
