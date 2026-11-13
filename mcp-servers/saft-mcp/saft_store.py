"""Query layer over a parsed Norwegian SAF-T file (no MCP dependency, unit-testable).

Parsing is delegated to the saft-parser skill (.claude/skills/saft-parser/scripts/parse_saft.py)
so there is one SAF-T implementation in the project. Parsed data is cached and re-parsed
automatically when the file's size or mtime changes.
"""

import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PARSER_DIR = os.path.join(PROJECT_ROOT, ".claude", "skills", "saft-parser", "scripts")
sys.path.insert(0, PARSER_DIR)

from parse_saft import SaftError, parse_file  # noqa: E402

# Norwegian SAF-T standard tax codes, grouped by direction.
INPUT_CODES = {"1", "11", "12", "13", "14", "15"}
OUTPUT_CODES = {"3", "31", "32", "33", "5", "51", "52", "6"}
REVERSE_CHARGE_CODES = {"81", "82", "83", "84", "85", "86", "87", "88", "89", "91", "92"}
DEFAULT_LIMIT = 200


class StoreError(Exception):
    """User-facing error (bad argument, no file loaded, unreadable file)."""


def _direction(std_code):
    if std_code in INPUT_CODES:
        return "input"
    if std_code in OUTPUT_CODES:
        return "output"
    if std_code in REVERSE_CHARGE_CODES:
        return "reverse_charge"
    if std_code == "0":
        return "none"
    return "unknown"


def _norm_name(s):
    s = re.sub(r"\b(AS|ASA|ANS|DA|ENK|NUF|SA)\b\.?", "", s or "", flags=re.I)
    return re.sub(r"[^0-9a-zæøå]", "", s.casefold())


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _limited(items, limit):
    limit = DEFAULT_LIMIT if limit is None else max(1, min(int(limit), 1000))
    return {"total": len(items), "returned": min(len(items), limit),
            "truncated": len(items) > limit, "items": items[:limit]}


class SaftStore:
    def __init__(self, path=None):
        self._path = None
        self._stamp = None
        self._data = None
        if path:
            self.load(path)

    # -- loading ----------------------------------------------------------
    def load(self, path):
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(path):
            raise StoreError(f"SAF-T file not found: {path}")
        try:
            data = parse_file(path)
        except SaftError as exc:
            raise StoreError(f"Cannot parse {path}: {exc}") from exc
        st = os.stat(path)
        self._path, self._stamp, self._data = path, (st.st_size, st.st_mtime_ns), data
        self._index()
        return self.summary()

    def _index(self):
        d = self._data
        self._accounts = {a["id"]: a for a in d["gl_accounts"]}
        self._suppliers = {s["id"]: s for s in d["suppliers"]}
        self._mappings = {m["supplier_id"]: m for m in d["supplier_account_mappings"]}
        for c in d["vat_codes"]:
            c["direction"] = _direction(c.get("standard_tax_code"))

    def data(self):
        if self._path is None:
            raise StoreError("No SAF-T file loaded. Call load_saft_file(path) or set the "
                             "SAFT_FILE environment variable for the server.")
        try:
            st = os.stat(self._path)
        except OSError as exc:
            raise StoreError(f"Loaded SAF-T file is no longer readable: {exc}") from exc
        if (st.st_size, st.st_mtime_ns) != self._stamp:
            self.load(self._path)
        return self._data

    # -- queries ----------------------------------------------------------
    def summary(self):
        meta = self.data()["meta"]
        return {"file": self._path,
                "company": meta.get("company"),
                "audit_file_version": meta.get("audit_file_version"),
                "selection_criteria": meta.get("selection_criteria"),
                "software": meta.get("software"),
                "counts": meta.get("counts"),
                "warnings": meta.get("warnings", [])}

    def list_accounts(self, query=None, prefix=None, limit=None):
        self.data()
        q = (query or "").casefold().strip()
        items = [a for a in self._accounts.values()
                 if (not prefix or a["id"].startswith(prefix))
                 and (not q or q in a["id"].casefold() or q in (a["description"] or "").casefold())]
        return _limited(items, limit)

    def get_account(self, account_id):
        self.data()
        acc = self._accounts.get(str(account_id).strip())
        if not acc:
            raise StoreError(f"Account {account_id} does not exist in the chart of accounts")
        used_by = []
        for m in self._mappings.values():
            for e in m["expense_accounts"]:
                if e["account_id"] == acc["id"]:
                    used_by.append({"supplier_id": m["supplier_id"],
                                    "supplier_name": m["supplier_name"],
                                    "count": e["count"], "tax_codes": e["tax_codes"]})
        used_by.sort(key=lambda u: -u["count"])
        return {**acc, "used_by_suppliers": used_by[:20],
                "used_by_suppliers_total": len(used_by)}

    def list_vat_codes(self, direction=None):
        codes = self.data()["vat_codes"]
        if direction:
            valid = {"input", "output", "reverse_charge", "none", "unknown"}
            if direction not in valid:
                raise StoreError(f"direction must be one of {sorted(valid)}")
            codes = [c for c in codes if c["direction"] == direction]
        return {"total": len(codes), "items": codes}

    def find_vat_code(self, rate, direction="input", date=None):
        """VAT codes with this percentage and direction, valid on date (YYYY-MM-DD) if given."""
        try:
            target = Decimal(str(rate).replace(",", ".").rstrip("%").strip())
        except InvalidOperation:
            raise StoreError(f"Not a VAT rate: {rate!r}")
        if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise StoreError("date must be YYYY-MM-DD")
        matches = []
        for c in self.list_vat_codes(direction)["items"]:
            pct = c.get("percentage")
            if target == 0 and c["direction"] == "none":
                pass
            elif pct is None or Decimal(str(pct)) != target:
                continue
            if date and ((c.get("effective_date") or "0000") > date
                         or (c.get("expiration_date") or "9999") < date):
                continue
            matches.append(c)
        status = "unique" if len(matches) == 1 else ("none" if not matches else "ambiguous")
        return {"rate": float(target), "direction": direction, "date": date,
                "status": status, "matches": matches}

    def search_suppliers(self, query=None, org_number=None, limit=None):
        self.data()
        if not query and not org_number:
            items = list(self._suppliers.values())
        else:
            q, org = _norm_name(query), _digits(org_number)
            items = [s for s in self._suppliers.values()
                     if (org and _digits(s.get("registration_number")).endswith(org))
                     or (q and (q in _norm_name(s.get("name")) or q == s["id"]))]
        items = [{**s, "has_history": s["id"] in self._mappings} for s in items]
        return _limited(items, limit)

    def get_supplier_history(self, supplier_id):
        self.data()
        sid = str(supplier_id).strip()
        sup = self._suppliers.get(sid)
        m = self._mappings.get(sid)
        if not sup and not m:
            raise StoreError(f"Supplier {supplier_id} not found")
        result = {"supplier": sup, "in_master_files": sup is not None,
                  "invoice_transactions": 0, "other_transactions": 0,
                  "payable_accounts": [], "expense_accounts": []}
        if not m:
            result["note"] = "No transactions for this supplier in GeneralLedgerEntries"
            return result
        cost = [e for e in m["expense_accounts"] if not e["account_id"].startswith("27")]
        total = sum(e["count"] for e in cost) or 1
        expense = []
        for e in m["expense_accounts"]:
            is_vat = e["account_id"].startswith("27")
            expense.append({**e, "is_vat_account": is_vat,
                            "share_of_cost_lines": None if is_vat else round(e["count"] / total, 3)})
        result.update(invoice_transactions=m["invoice_transactions"],
                      other_transactions=m["other_transactions"],
                      payable_accounts=m["payable_accounts"], expense_accounts=expense)
        return result

    def export_json(self, output_path):
        if not output_path.lower().endswith(".json"):
            raise StoreError("output_path must end with .json")
        output_path = os.path.abspath(os.path.expanduser(output_path))
        parent = os.path.dirname(output_path)
        if not os.path.isdir(parent):
            raise StoreError(f"Directory does not exist: {parent}")
        data = self.data()
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return {"written": output_path, "counts": data["meta"]["counts"]}
