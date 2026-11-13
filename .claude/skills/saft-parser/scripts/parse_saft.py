#!/usr/bin/env python3
"""Parse a Norwegian SAF-T Financial (v1.30) XML file into structured JSON.

Extracts:
  - GL accounts            (MasterFiles/GeneralLedgerAccounts/Account)
  - MVA/VAT codes          (MasterFiles/TaxTable/TaxTableEntry/TaxCodeDetails)
  - Suppliers              (MasterFiles/Suppliers/Supplier)
  - Supplier -> account    (derived from GeneralLedgerEntries/Journal/Transaction/Line)

Streams the file with iterparse, so multi-GB exports are fine.
Stdlib only. Uses defusedxml if installed.

Usage:
  python parse_saft.py <file.xml> [-o out.json] [--allow-other-namespace] [--compact]

Exit codes: 0 ok, 1 file/XML error, 2 not a Norwegian SAF-T file (namespace mismatch).
"""

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation

try:  # Prefer hardened parser when available.
    from defusedxml.ElementTree import iterparse
except ImportError:  # pragma: no cover
    from xml.etree.ElementTree import iterparse

SAFT_NO_NS = "urn:StandardAuditFile-Taxation-Financial:NO"
SUPPORTED_VERSION = "1.30"


class SaftError(Exception):
    def __init__(self, message, exit_code=1):
        super().__init__(message)
        self.exit_code = exit_code


def _split(tag):
    """'{ns}Local' -> ('ns', 'Local')."""
    if tag.startswith("{"):
        ns, local = tag[1:].split("}", 1)
        return ns, local
    return "", tag


def _dec(text):
    if text is None or not text.strip():
        return Decimal(0)
    try:
        return Decimal(text.strip())
    except InvalidOperation:
        return Decimal(0)


def _num(value):
    """Decimal -> JSON number with up to 2 decimals (int when whole)."""
    q = value.quantize(Decimal("0.01"))
    return int(q) if q == q.to_integral_value() else float(q)


class SaftParser:
    def __init__(self, allow_other_namespace=False):
        self.allow_other_namespace = allow_other_namespace
        self.ns = None
        self.meta = {"warnings": []}
        self.accounts = []
        self.vat_codes = []
        self.suppliers = []
        # supplier_id -> {"payable": {acct: count}, "expense": {acct: {...}}, ...}
        self.mapping = defaultdict(lambda: {
            "payable": defaultdict(int),
            "expense": defaultdict(lambda: {"count": 0, "debit": Decimal(0),
                                            "credit": Decimal(0), "tax_codes": set()}),
            "invoice_transactions": 0,
            "other_transactions": 0,
        })
        self.transaction_count = 0

    # -- helpers bound to the detected namespace ---------------------------
    def q(self, path):
        """'A/B' -> '{ns}A/{ns}B' for find()."""
        if not self.ns:
            return path
        return "/".join(f"{{{self.ns}}}{p}" for p in path.split("/"))

    def text(self, el, path):
        found = el.find(self.q(path))
        if found is None or found.text is None:
            return None
        return found.text.strip() or None

    # -- main --------------------------------------------------------------
    def parse(self, source):
        stack = []
        context = iterparse(source, events=("start", "end"))
        for event, el in context:
            ns, local = _split(el.tag)
            if event == "start":
                if not stack:
                    self._check_root(ns, local)
                stack.append(local)
                continue

            parent = stack[-2] if len(stack) > 1 else None
            if local == "Header" and parent == "AuditFile":
                self._handle_header(el)
                el.clear()
            elif local == "Account" and parent == "GeneralLedgerAccounts":
                self._handle_account(el)
                el.clear()
            elif local == "TaxTableEntry" and parent == "TaxTable":
                self._handle_tax_entry(el)
                el.clear()
            elif local == "Supplier" and parent == "Suppliers":
                self._handle_supplier(el)
                el.clear()
            elif local == "Transaction" and parent == "Journal":
                self._handle_transaction(el)
                el.clear()
            else:
                self._handle_other(local, parent, el)
            stack.pop()

        if self.ns is None:
            raise SaftError("Empty XML document")
        return self._result()

    def _check_root(self, ns, local):
        self.ns = ns
        self.meta["namespace"] = ns or None
        if local != "AuditFile":
            raise SaftError(f"Root element is <{local}>, expected <AuditFile>", 2)
        if ns != SAFT_NO_NS:
            msg = (f"Namespace '{ns or '(none)'}' is not the Norwegian SAF-T "
                   f"Financial namespace '{SAFT_NO_NS}'")
            if not self.allow_other_namespace:
                raise SaftError(msg, 2)
            self.meta["warnings"].append(msg)

    def _handle_header(self, el):
        version = self.text(el, "AuditFileVersion")
        self.meta["audit_file_version"] = version
        if version != SUPPORTED_VERSION:
            self.meta["warnings"].append(
                f"AuditFileVersion is '{version}', parser targets {SUPPORTED_VERSION}")
        self.meta["company"] = {
            "name": self.text(el, "Company/Name"),
            "registration_number": self.text(el, "Company/RegistrationNumber"),
        }
        self.meta["selection_criteria"] = {
            "period_start": self.text(el, "SelectionCriteria/PeriodStart"),
            "period_start_year": self.text(el, "SelectionCriteria/PeriodStartYear"),
            "period_end": self.text(el, "SelectionCriteria/PeriodEnd"),
            "period_end_year": self.text(el, "SelectionCriteria/PeriodEndYear"),
        }
        self.meta["default_currency_code"] = self.text(el, "DefaultCurrencyCode")
        self.meta["software"] = {
            "company_name": self.text(el, "SoftwareCompanyName"),
            "id": self.text(el, "SoftwareID"),
            "version": self.text(el, "SoftwareVersion"),
        }

    def _handle_account(self, el):
        account_id = self.text(el, "AccountID")
        if not account_id:
            self.meta["warnings"].append("GL account without AccountID skipped")
            return
        self.accounts.append({
            "id": account_id,
            "description": self.text(el, "AccountDescription"),
            "standard_account_id": self.text(el, "StandardAccountID"),
            "grouping_category": self.text(el, "GroupingCategory"),
            "grouping_code": self.text(el, "GroupingCode"),
            "account_type": self.text(el, "AccountType"),
        })

    def _handle_tax_entry(self, el):
        tax_type = self.text(el, "TaxType")
        for detail in el.findall(self.q("TaxCodeDetails")):
            code = self.text(detail, "TaxCode")
            if not code:
                continue
            pct = self.text(detail, "TaxPercentage")
            self.vat_codes.append({
                "code": code,
                "percentage": _num(_dec(pct)) if pct is not None else None,
                "description": self.text(detail, "Description"),
                "standard_tax_code": self.text(detail, "StandardTaxCode"),
                "tax_type": tax_type,
                "effective_date": self.text(detail, "EffectiveDate"),
                "expiration_date": self.text(detail, "ExpirationDate"),
            })

    def _handle_supplier(self, el):
        supplier_id = self.text(el, "SupplierID")
        if not supplier_id:
            self.meta["warnings"].append("Supplier without SupplierID skipped")
            return
        self.suppliers.append({
            "id": supplier_id,
            "name": self.text(el, "Name"),
            "registration_number": self.text(el, "RegistrationNumber"),
            "account_id": self.text(el, "AccountID"),
        })

    def _handle_transaction(self, el):
        """Derive supplier -> account usage from one transaction.

        Lines carrying a SupplierID are the supplier's payable (reskontro) lines.
        If those lines are net credit, the transaction is treated as a supplier
        invoice and every other line's account is recorded as an expense/counter
        account for that supplier. Net-debit transactions (payments, credit notes)
        only contribute to payable_accounts, so bank accounts don't pollute the map.
        """
        self.transaction_count += 1
        tx_supplier = self.text(el, "SupplierID")  # some systems set it here
        lines = []
        for line in el.findall(self.q("Line")):
            debit = _dec(self.text(line, "DebitAmount/Amount"))
            credit = _dec(self.text(line, "CreditAmount/Amount"))
            lines.append({
                "account": self.text(line, "AccountID"),
                "supplier": self.text(line, "SupplierID"),
                "debit": debit,
                "credit": credit,
                "tax_code": self.text(line, "TaxInformation/TaxCode"),
            })

        supplier_lines = [ln for ln in lines if ln["supplier"]]
        suppliers = {ln["supplier"] for ln in supplier_lines}
        if not suppliers and tx_supplier:
            suppliers = {tx_supplier}
        if not suppliers:
            return
        if len(suppliers) > 1:
            # Ambiguous (e.g. netting between suppliers): record payables only.
            for ln in supplier_lines:
                if ln["account"]:
                    self.mapping[ln["supplier"]]["payable"][ln["account"]] += 1
            return

        supplier = next(iter(suppliers))
        entry = self.mapping[supplier]
        for ln in supplier_lines:
            if ln["account"]:
                entry["payable"][ln["account"]] += 1

        if supplier_lines:
            net = sum(ln["credit"] - ln["debit"] for ln in supplier_lines)
            is_invoice = net > 0
            counter = [ln for ln in lines if not ln["supplier"]]
        else:
            # Supplier only at transaction level: no payable line to measure,
            # so treat all lines as counter lines of an invoice.
            is_invoice = True
            counter = lines

        if not is_invoice:
            entry["other_transactions"] += 1
            return
        entry["invoice_transactions"] += 1
        for ln in counter:
            if not ln["account"]:
                continue
            acc = entry["expense"][ln["account"]]
            acc["count"] += 1
            acc["debit"] += ln["debit"]
            acc["credit"] += ln["credit"]
            if ln["tax_code"]:
                acc["tax_codes"].add(ln["tax_code"])

    def _handle_other(self, local, parent, el):
        """Hook for subclasses; called on the end of every element not handled above."""

    # -- output ------------------------------------------------------------
    def _result(self):
        account_desc = {a["id"]: a["description"] for a in self.accounts}
        supplier_name = {s["id"]: s["name"] for s in self.suppliers}

        mappings = []
        for sid in sorted(self.mapping):
            m = self.mapping[sid]
            if sid not in supplier_name:
                self.meta["warnings"].append(
                    f"SupplierID '{sid}' used in GeneralLedgerEntries but not in MasterFiles")
            expense = sorted(
                ({
                    "account_id": acct,
                    "account_description": account_desc.get(acct),
                    "count": v["count"],
                    "total_debit": _num(v["debit"]),
                    "total_credit": _num(v["credit"]),
                    "tax_codes": sorted(v["tax_codes"]),
                } for acct, v in m["expense"].items()),
                key=lambda x: (-x["count"], -x["total_debit"], x["account_id"]),
            )
            mappings.append({
                "supplier_id": sid,
                "supplier_name": supplier_name.get(sid),
                "invoice_transactions": m["invoice_transactions"],
                "other_transactions": m["other_transactions"],
                "payable_accounts": [
                    {"account_id": a, "account_description": account_desc.get(a), "count": c}
                    for a, c in sorted(m["payable"].items(), key=lambda kv: (-kv[1], kv[0]))
                ],
                "expense_accounts": expense,
                "primary_expense_account": expense[0]["account_id"] if expense else None,
            })

        self.meta["counts"] = {
            "gl_accounts": len(self.accounts),
            "vat_codes": len(self.vat_codes),
            "suppliers": len(self.suppliers),
            "transactions": self.transaction_count,
            "suppliers_with_mappings": len(mappings),
        }
        return {
            "meta": self.meta,
            "gl_accounts": self.accounts,
            "vat_codes": self.vat_codes,
            "suppliers": self.suppliers,
            "supplier_account_mappings": mappings,
        }


class PostingParser(SaftParser):
    """Collects every posting on the given accounts, with its whole voucher (bilag)
    and the accounts' opening/closing balances. Skips the supplier mapping work."""

    def __init__(self, account_ids, allow_other_namespace=False):
        super().__init__(allow_other_namespace)
        self.account_ids = {str(a) for a in account_ids}
        self.balances = {}
        self.postings = []
        self._journal = None

    def _handle_account(self, el):
        super()._handle_account(el)
        account_id = self.text(el, "AccountID")
        if account_id in self.account_ids:
            bal = lambda d, c: _num(_dec(self.text(el, d)) - _dec(self.text(el, c)))  # noqa: E731
            self.balances[account_id] = {
                "description": self.text(el, "AccountDescription"),
                "opening_balance": bal("OpeningDebitBalance", "OpeningCreditBalance"),
                "closing_balance": bal("ClosingDebitBalance", "ClosingCreditBalance"),
            }

    def _handle_other(self, local, parent, el):
        if local == "JournalID" and parent == "Journal":
            self._journal = (el.text or "").strip() or None

    def _handle_transaction(self, el):
        self.transaction_count += 1
        lines = []
        for line in el.findall(self.q("Line")):
            debit = _dec(self.text(line, "DebitAmount/Amount"))
            credit = _dec(self.text(line, "CreditAmount/Amount"))
            lines.append({"record_id": self.text(line, "RecordID"),
                          "account_id": self.text(line, "AccountID"),
                          "description": self.text(line, "Description"),
                          "debit": _num(debit), "credit": _num(credit),
                          "amount": _num(debit - credit),
                          "supplier_id": self.text(line, "SupplierID"),
                          "customer_id": self.text(line, "CustomerID"),
                          "tax_code": self.text(line, "TaxInformation/TaxCode")})
        hits = [ln for ln in lines if ln["account_id"] in self.account_ids]
        if not hits:
            return
        voucher = {"transaction_id": self.text(el, "TransactionID"),
                   "journal_id": self._journal,
                   "date": self.text(el, "TransactionDate"),
                   "gl_posting_date": self.text(el, "GLPostingDate"),
                   "description": self.text(el, "Description"),
                   "lines": lines}
        for ln in hits:
            self.postings.append({**{k: voucher[k] for k in
                                     ("transaction_id", "journal_id", "date",
                                      "gl_posting_date")},
                                  "account_id": ln["account_id"],
                                  "record_id": ln["record_id"],
                                  "description": ln["description"] or voucher["description"],
                                  "amount": ln["amount"],
                                  "voucher": voucher})


def _run(parser, path):
    try:
        with open(path, "rb") as fh:
            result = parser.parse(fh)
    except OSError as exc:
        raise SaftError(f"Cannot read file: {exc}") from exc
    except SaftError:
        raise
    except Exception as exc:  # ParseError, defusedxml errors
        raise SaftError(f"Invalid XML: {exc}") from exc
    result["meta"]["source_file"] = path
    return result


def parse_file(path, allow_other_namespace=False):
    return _run(SaftParser(allow_other_namespace=allow_other_namespace), path)


def read_account_postings(path, account_ids, allow_other_namespace=False):
    """Postings on account_ids (e.g. ["1920"]) with full vouchers and balances.

    Amounts are signed: debit positive, credit negative (for a bank account:
    money in positive, money out negative)."""
    parser = PostingParser(account_ids, allow_other_namespace)
    result = _run(parser, path)
    missing = parser.account_ids - set(parser.balances)
    if missing:
        result["meta"]["warnings"].append(
            f"Account(s) not in chart of accounts: {', '.join(sorted(missing))}")
    return {"meta": result["meta"], "accounts": parser.balances, "postings": parser.postings}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Parse Norwegian SAF-T v1.30 XML to JSON.")
    ap.add_argument("file", help="SAF-T XML file")
    ap.add_argument("-o", "--output", help="Write JSON here instead of stdout")
    ap.add_argument("--allow-other-namespace", action="store_true",
                    help="Parse even if the root namespace is not the Norwegian SAF-T one")
    ap.add_argument("--compact", action="store_true", help="Minified JSON")
    args = ap.parse_args(argv)

    try:
        result = parse_file(args.file, args.allow_other_namespace)
    except SaftError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return exc.exit_code

    out = json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
