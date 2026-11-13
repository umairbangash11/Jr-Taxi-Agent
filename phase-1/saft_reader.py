#!/usr/bin/env python3
"""Phase 1 — SAF-T Reader.

Reads a Norwegian SAF-T Financial (v1.30) XML export and writes the agent's reference data,
phase-1/saft_data.json: accounts, vat_codes, suppliers, supplier_account_map and a summary.

Rules (specs/001-phase1-saft-reader): anything that can't be determined is the literal
"unknown" (never guessed); one streaming pass so large files use flat memory; deterministic,
atomically written output. Standard library only, no LLM.

Usage: python phase-1/saft_reader.py <saft.xml> [-o <output.json>]
Exit codes: 0 ok, 1 unreadable / not XML, 2 not a Norwegian SAF-T file.
"""

import argparse
import json
import os
import sys
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from xml.etree.ElementTree import ParseError, iterparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import (UNKNOWN, Account, Candidate, Supplier,  # noqa: E402
                           SupplierAccountMapping, VatCode)

NS = "urn:StandardAuditFile-Taxation-Financial:NO"
SUPPORTED_VERSION = "1.30"
MAP_THRESHOLD = Decimal("0.80")
SHARE_PLACES = Decimal("0.001")
DEFAULT_OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saft_data.json")
BLANK_VAT = VatCode("", Decimal(0), "Ingen mva-kode (blank)", UNKNOWN, None, None, "implicit")


class SaftReaderError(Exception):
    def __init__(self, message, exit_code):
        super().__init__(message)
        self.exit_code = exit_code


def _q(path):
    return "/".join(f"{{{NS}}}{part}" for part in path.split("/"))


def text_or_none(el, path):
    found = el.find(_q(path))
    if found is None or found.text is None or not found.text.strip():
        return None
    return found.text.strip()


def text_or_unknown(el, path):
    value = text_or_none(el, path)
    return UNKNOWN if value is None else value


def _decimal(text):
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def sort_key(value):
    """Numeric-aware: '930' < '1930' < '7026' < 'A1'."""
    return (0, int(value), value) if value.isdigit() else (1, 0, value)


class _Reader:
    def __init__(self):
        self.summary = {"saft_version": UNKNOWN, "company_name": UNKNOWN,
                        "company_registration_number": UNKNOWN,
                        "period": {"start": UNKNOWN, "start_year": UNKNOWN,
                                   "end": UNKNOWN, "end_year": UNKNOWN}}
        self.skipped = []
        self.warnings = []
        self.accounts = {}
        self.vat_codes = []
        self.suppliers = {}
        self.transactions = 0
        self.invoices = {}   # supplier_id -> [{"accounts": set, "vat": set}] per invoice

    # -- handlers -----------------------------------------------------------
    def header(self, el):
        version = text_or_unknown(el, "AuditFileVersion")
        self.summary["saft_version"] = version
        if version != SUPPORTED_VERSION:
            self.warnings.append(f"AuditFileVersion is {version}; reader targets "
                                 f"{SUPPORTED_VERSION}")
        self.summary["company_name"] = text_or_unknown(el, "Company/Name")
        self.summary["company_registration_number"] = text_or_unknown(
            el, "Company/RegistrationNumber")
        self.summary["period"] = {
            "start": text_or_unknown(el, "SelectionCriteria/PeriodStart"),
            "start_year": text_or_unknown(el, "SelectionCriteria/PeriodStartYear"),
            "end": text_or_unknown(el, "SelectionCriteria/PeriodEnd"),
            "end_year": text_or_unknown(el, "SelectionCriteria/PeriodEndYear"),
        }

    def account(self, el):
        account_id = text_or_none(el, "AccountID")
        if account_id is None:
            self.skipped.append("Account without AccountID (description: "
                                f"{text_or_unknown(el, 'AccountDescription')})")
            return
        if account_id in self.accounts:
            self.warnings.append(f"Duplicate AccountID {account_id}; first kept")
            return
        self.accounts[account_id] = Account(account_id, text_or_unknown(el, "AccountDescription"),
                                            text_or_unknown(el, "StandardAccountID"))

    def tax_entry(self, el):
        for detail in el.findall(_q("TaxCodeDetails")):
            code = text_or_none(detail, "TaxCode")
            if code is None:
                self.skipped.append("TaxCodeDetails without TaxCode")
                continue
            pct = _decimal(text_or_none(detail, "TaxPercentage"))
            self.vat_codes.append(VatCode(
                code, UNKNOWN if pct is None else pct, text_or_unknown(detail, "Description"),
                text_or_unknown(detail, "StandardTaxCode"),
                text_or_none(detail, "EffectiveDate"), text_or_none(detail, "ExpirationDate"),
                "tax_table"))

    def supplier(self, el):
        supplier_id = text_or_none(el, "SupplierID")
        if supplier_id is None:
            self.skipped.append(f"Supplier without SupplierID (name: "
                                f"{text_or_unknown(el, 'Name')})")
            return
        if supplier_id in self.suppliers:
            self.warnings.append(f"Duplicate SupplierID {supplier_id}; first kept")
            return
        self.suppliers[supplier_id] = Supplier(supplier_id, text_or_unknown(el, "Name"),
                                               text_or_unknown(el, "RegistrationNumber"), True)

    def transaction(self, el):
        """Learn from supplier invoices only (research R4).

        Invoice = exactly one distinct SupplierID (on lines, else on the transaction) whose
        lines are net credit, i.e. the supplier's payable increased. Payments, credit notes and
        netting between suppliers don't teach the map.
        """
        self.transactions += 1
        lines = []
        for ln in el.findall(_q("Line")):
            lines.append({
                "account": text_or_none(ln, "AccountID") or "",
                "supplier": text_or_none(ln, "SupplierID"),
                "debit": _decimal(text_or_none(ln, "DebitAmount/Amount")) or Decimal(0),
                "credit": _decimal(text_or_none(ln, "CreditAmount/Amount")) or Decimal(0),
                "mk": text_or_none(ln, "TaxInformation/TaxCode") or "",
            })
        on_lines = {ln["supplier"] for ln in lines if ln["supplier"]}
        if on_lines:
            if len(on_lines) != 1:
                return
            supplier = on_lines.pop()
            net = sum((ln["credit"] - ln["debit"] for ln in lines if ln["supplier"] == supplier),
                      Decimal(0))
        else:
            supplier = text_or_none(el, "SupplierID")
            if supplier is None:
                return
            net = sum((ln["credit"] for ln in lines if ln["account"][:1] == "2"), Decimal(0))
        if net <= 0:
            return
        pl = [ln for ln in lines if is_pl_account(ln["account"])]
        self.invoices.setdefault(supplier, []).append(
            {"accounts": {ln["account"] for ln in pl}, "vat": {ln["mk"] for ln in pl}})

    # -- result ---------------------------------------------------------------
    def result(self, source_name):
        for supplier_id in self.invoices:
            if supplier_id not in self.suppliers:
                self.suppliers[supplier_id] = Supplier(supplier_id, UNKNOWN, UNKNOWN, False)
                self.warnings.append(f"SupplierID {supplier_id} used in GeneralLedgerEntries "
                                     "but not in MasterFiles")
        descriptions = {k: a.description for k, a in self.accounts.items()}
        mappings = [decide_mapping(sid, self.suppliers[sid].name, self.invoices.get(sid, []),
                                   descriptions)
                    for sid in sorted(self.suppliers, key=sort_key)]
        mapped = sum(m.account_id != UNKNOWN for m in mappings)
        vat = sorted(self.vat_codes, key=lambda c: (sort_key(c.code), c.effective_date or ""))
        summary = {"source_file": source_name, **self.summary,
                   "counts": {"accounts": len(self.accounts), "vat_codes": len(vat) + 1,
                              "suppliers": len(self.suppliers), "mapped_suppliers": mapped,
                              "unknown_mappings": len(mappings) - mapped,
                              "transactions": self.transactions,
                              "supplier_invoices": sum(len(v) for v in self.invoices.values())},
                   "unknown_values": {}, "skipped": sorted(self.skipped),
                   "warnings": sorted(self.warnings)}
        sections = {
            "accounts": [self.accounts[k].to_dict() for k in sorted(self.accounts, key=sort_key)],
            "vat_codes": [BLANK_VAT.to_dict()] + [c.to_dict() for c in vat],
            "suppliers": [self.suppliers[k].to_dict()
                          for k in sorted(self.suppliers, key=sort_key)],
            "supplier_account_map": [m.to_dict() for m in mappings],
        }
        summary["unknown_values"] = {name: count_unknowns(items)
                                     for name, items in sections.items()}
        return {"summary": summary, **sections}


def count_unknowns(value):
    """Number of "unknown" values in a serialized section (SC-003: every gap is counted)."""
    if value == UNKNOWN:
        return 1
    if isinstance(value, dict):
        return sum(count_unknowns(v) for v in value.values())
    if isinstance(value, list):
        return sum(count_unknowns(v) for v in value)
    return 0


def is_pl_account(account_id):
    """Profit-and-loss account (NS 4102 classes 3–8). Bank 1930, payable 2400, VAT 27xx: no."""
    return account_id[:1] in "345678" and account_id != ""


def decide_mapping(supplier_id, supplier_name, invoices, descriptions):
    """Apply the ≥ 80 % rule per invoice (research R6, data-model decision table)."""
    total = len(invoices)
    counts = {}
    for inv in invoices:
        for account in inv["accounts"]:
            counts[account] = counts.get(account, 0) + 1
    vat_seen = tuple(sorted({mk for inv in invoices for mk in inv["vat"]}))

    def share(n):
        return (Decimal(n) / Decimal(total)).quantize(SHARE_PLACES, ROUND_HALF_UP)

    candidates = tuple(
        Candidate(acc, descriptions.get(acc, UNKNOWN), n, share(n))
        for acc, n in sorted(counts.items(), key=lambda kv: (-kv[1], sort_key(kv[0]))))
    unknown = dict(account_id=UNKNOWN, account_description=UNKNOWN, share=None)

    if total == 0:
        return SupplierAccountMapping(supplier_id, supplier_name, invoice_count=0,
                                      reason="no booking history", **unknown)
    if not counts:
        return SupplierAccountMapping(supplier_id, supplier_name, invoice_count=total,
                                      reason="no cost account on invoices",
                                      vat_codes_seen=vat_seen, **unknown)
    qualifying = [acc for acc, n in counts.items()
                  if Decimal(n) / Decimal(total) >= MAP_THRESHOLD]
    if len(qualifying) == 1:
        acc = qualifying[0]
        return SupplierAccountMapping(supplier_id, supplier_name, acc,
                                      descriptions.get(acc, UNKNOWN), share(counts[acc]), total,
                                      candidates, None, vat_seen)
    reason = ("multiple accounts on the same invoices" if qualifying else "ambiguous history")
    return SupplierAccountMapping(supplier_id, supplier_name, invoice_count=total,
                                  candidates=candidates, reason=reason,
                                  vat_codes_seen=vat_seen, **unknown)


HANDLERS = {("Header", "AuditFile"): "header",
            ("Account", "GeneralLedgerAccounts"): "account",
            ("TaxTableEntry", "TaxTable"): "tax_entry",
            ("Supplier", "Suppliers"): "supplier",
            ("Transaction", "Journal"): "transaction"}


def read_saft(path):
    """Parse a SAF-T file into the saft_data.json structure. Raises SaftReaderError."""
    reader = _Reader()
    stack = []
    try:
        with open(path, "rb") as fh:
            for event, el in iterparse(fh, events=("start", "end")):
                ns, _, local = el.tag[1:].partition("}") if el.tag.startswith("{") \
                    else ("", "", el.tag)
                if event == "start":
                    if not stack and (local != "AuditFile" or ns != NS):
                        raise SaftReaderError(
                            f"Not a Norwegian SAF-T file: root is <{local}> in namespace "
                            f"{ns or '(none)'!r}, expected <AuditFile> in {NS!r}", 2)
                    stack.append(local)
                    continue
                parent = stack[-2] if len(stack) > 1 else None
                handler = HANDLERS.get((local, parent))
                if handler and ns == NS:
                    getattr(reader, handler)(el)
                    el.clear()
                stack.pop()
    except OSError as exc:
        raise SaftReaderError(f"Cannot read {path}: {exc}", 1) from exc
    except ParseError as exc:
        raise SaftReaderError(f"Not well-formed XML: {exc}", 1) from exc
    return reader.result(os.path.basename(path))


def write_saft_data(data, path):
    """Write deterministically and atomically (temp file in the same folder + os.replace)."""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 1 SAF-T reader -> saft_data.json")
    ap.add_argument("saft", help="Norwegian SAF-T Financial XML file")
    ap.add_argument("-o", "--output", default=DEFAULT_OUTPUT,
                    help="output JSON (default: phase-1/saft_data.json)")
    args = ap.parse_args(argv)
    try:
        data = read_saft(args.saft)
    except SaftReaderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    write_saft_data(data, args.output)
    c = data["summary"]["counts"]
    print(f"{os.path.basename(args.output)}: {c['accounts']} accounts, {c['vat_codes']} VAT codes, "
          f"{c['suppliers']} suppliers, {c['mapped_suppliers']} mapped / "
          f"{c['unknown_mappings']} unknown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
