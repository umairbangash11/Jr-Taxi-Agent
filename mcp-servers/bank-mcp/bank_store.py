"""Bank statement layer for bank-mcp (no MCP dependency, unit-testable).

Parsing and matching are delegated to the bank-matcher skill
(.claude/skills/bank-matcher/scripts/match_bank.py) so the rules live in one place.
The loaded statement is cached and re-read when the file's size or mtime changes.

Optional sandbox: BANK_ROOTS (os.pathsep-separated directories) restricts readable files.
"""

import os
import re
import sys
from decimal import Decimal

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MATCHER_DIR = os.path.join(PROJECT_ROOT, ".claude", "skills", "bank-matcher", "scripts")
sys.path.insert(0, MATCHER_DIR)

import match_bank as mb  # noqa: E402

ALLOWED_EXTS = {".csv", ".txt", ".xml"}
DEFAULT_LIMIT = 200
MAX_DOCUMENTS = 500


class BankError(Exception):
    """User-facing error (no statement loaded, bad path, bad argument)."""


def _line_out(ln):
    return {"bank_line": ln["id"], "date": ln["date"].isoformat(),
            "amount": float(ln["amount"]), "text": ln["text"]}


def _date(value, name):
    if value in (None, ""):
        return None
    d = mb.parse_date(value)
    if d is None:
        raise BankError(f"{name} must be a date like 2025-03-10 or 10.03.2025")
    return d


def _amount(value, name):
    if value in (None, ""):
        return None
    a = mb.parse_amount(value)
    if a is None:
        raise BankError(f"{name} is not an amount: {value!r}")
    return a


def settings(receipt_days=7, invoice_days=60, early_days=3, tolerance=0):
    tol = _amount(tolerance, "tolerance")
    if tol is None or tol < 0:
        raise BankError("tolerance must be a non-negative amount")
    for name, v in (("receipt_days", receipt_days), ("invoice_days", invoice_days),
                    ("early_days", early_days)):
        if not 0 <= int(v) <= 366:
            raise BankError(f"{name} must be between 0 and 366")
    if int(receipt_days) == 0 or int(invoice_days) == 0:
        raise BankError("receipt_days and invoice_days must be at least 1")
    return {"receipt_days": int(receipt_days), "invoice_days": int(invoice_days),
            "early_days": int(early_days), "tolerance": tol}


def normalize_document(d, n):
    """Accept bank-matcher, document-mcp summary or free-form dicts."""
    if not isinstance(d, dict):
        raise BankError(f"documents[{n}] must be an object")
    pick = lambda *keys: next((d[k] for k in keys if d.get(k) not in (None, "")), None)  # noqa: E731
    amount = pick("amount", "total_amount")
    doc_type = pick("document_type", "type")
    if doc_type not in (None, "faktura", "kvittering"):
        raise BankError(f"documents[{n}].type must be faktura or kvittering")
    return {"id": str(pick("id", "file", "source_file") or f"doc{n + 1}"),
            "vendor": pick("vendor", "supplier", "vendor_name"),
            "org": re.sub(r"\D", "", str(pick("org", "org_number", "vendor_org_number") or ""))
            or None,
            "date": _date(pick("date"), f"documents[{n}].date"),
            "amount": _amount(amount, f"documents[{n}].amount"),
            "invoice_number": pick("invoice_number"),
            "document_type": doc_type,
            "currency": pick("currency")}


class BankStore:
    def __init__(self, roots=None):
        if roots is None:
            env = os.environ.get("BANK_ROOTS", "")
            roots = [r for r in env.split(os.pathsep) if r.strip()]
        self.roots = [os.path.realpath(os.path.expanduser(r)) for r in roots]
        self._path = None
        self._cols = {}
        self._stamp = None
        self._lines = None
        self._warnings = []

    def _resolve(self, path, exts=ALLOWED_EXTS):
        if not path or not str(path).strip():
            raise BankError("path is required")
        real = os.path.realpath(os.path.expanduser(str(path)))
        if self.roots and not any(real == r or real.startswith(r + os.sep) for r in self.roots):
            raise BankError(f"{path} is outside the allowed BANK_ROOTS: {self.roots}")
        if not os.path.isfile(real):
            raise BankError(f"File not found: {path}")
        if os.path.splitext(real)[1].lower() not in exts:
            raise BankError(f"Unsupported file type; allowed: {sorted(exts)}")
        return real

    # -- loading ----------------------------------------------------------
    def load(self, path, date_col=None, text_cols=None, amount_col=None, out_col=None,
             in_col=None):
        real = self._resolve(path)
        cols = {"date_col": date_col, "text_cols": text_cols or None, "amount_col": amount_col,
                "out_col": out_col, "in_col": in_col}
        try:
            lines, warnings = mb.read_bank(real, **cols)
        except mb.InputError as exc:
            raise BankError(str(exc)) from exc
        except Exception as exc:  # malformed XML/CSV
            raise BankError(f"Cannot read {path}: {type(exc).__name__}: {exc}") from exc
        st = os.stat(real)
        self._path, self._cols, self._stamp = real, cols, (st.st_size, st.st_mtime_ns)
        self._lines, self._warnings = lines, warnings
        return self.summary()

    def lines(self):
        if self._path is None:
            raise BankError("No bank statement loaded. Call load_bank_statement(path).")
        try:
            st = os.stat(self._path)
        except OSError as exc:
            raise BankError(f"Loaded statement is no longer readable: {exc}") from exc
        if (st.st_size, st.st_mtime_ns) != self._stamp:
            self.load(self._path, **self._cols)
        return self._lines

    # -- queries ----------------------------------------------------------
    def summary(self):
        lines = self.lines()
        out = [ln for ln in lines if ln["amount"] < 0]
        inc = [ln for ln in lines if ln["amount"] > 0]
        dates = [ln["date"] for ln in lines]
        return {"file": self._path, "format": "camt" if self._path.lower().endswith(".xml")
                else "csv", "lines": len(lines), "outgoing": len(out), "incoming": len(inc),
                "total_out": float(-sum((ln["amount"] for ln in out), Decimal(0))),
                "total_in": float(sum((ln["amount"] for ln in inc), Decimal(0))),
                "date_from": min(dates).isoformat() if dates else None,
                "date_to": max(dates).isoformat() if dates else None,
                "warnings": self._warnings}

    def list_transactions(self, direction="all", date_from=None, date_to=None, query=None,
                          min_amount=None, max_amount=None, limit=None):
        if direction not in ("all", "outgoing", "incoming"):
            raise BankError("direction must be all, outgoing or incoming")
        lo, hi = _date(date_from, "date_from"), _date(date_to, "date_to")
        amin, amax = _amount(min_amount, "min_amount"), _amount(max_amount, "max_amount")
        q = (query or "").casefold()
        items = []
        for ln in self.lines():
            a = ln["amount"]
            if (direction == "outgoing" and a >= 0) or (direction == "incoming" and a <= 0):
                continue
            if (lo and ln["date"] < lo) or (hi and ln["date"] > hi):
                continue
            if (amin is not None and abs(a) < amin) or (amax is not None and abs(a) > amax):
                continue
            if q and q not in ln["text"].casefold():
                continue
            items.append(_line_out(ln))
        limit = DEFAULT_LIMIT if limit is None else max(1, min(int(limit), 1000))
        return {"total": len(items), "returned": min(len(items), limit),
                "truncated": len(items) > limit, "items": items[:limit]}

    def find_payment(self, amount, date=None, vendor=None, invoice_number=None,
                     org_number=None, document_type=None, **cfg_args):
        """Ad-hoc candidates for one document, best first (no one-to-one assignment)."""
        cfg = settings(**cfg_args)
        doc = normalize_document({"amount": amount, "date": date, "vendor": vendor,
                                  "invoice_number": invoice_number, "org": org_number,
                                  "type": document_type}, 0)
        if doc["amount"] is None or doc["amount"] <= 0:
            raise BankError("amount must be a positive number")
        cands = [c for c in (mb.score_pair(doc, ln, cfg) for ln in self.lines()) if c]
        cands.sort(key=lambda c: -c["score"])
        lo, hi = mb.window_for(doc, cfg)
        return {"amount": float(doc["amount"]),
                "window_days": None if doc["date"] is None else [lo, hi],
                "candidates": cands,
                "note": ("Candidates only; use match_documents for one-to-one assignment and "
                         "paid/uncertain status")}

    def match_documents(self, documents, **cfg_args):
        if not documents:
            raise BankError("documents must be a non-empty list")
        if len(documents) > MAX_DOCUMENTS:
            raise BankError(f"At most {MAX_DOCUMENTS} documents per call")
        cfg = settings(**cfg_args)
        docs = [normalize_document(d, n) for n, d in enumerate(documents)]
        return self._match(docs, cfg)

    def match_documents_file(self, json_path, **cfg_args):
        real = self._resolve(json_path, exts={".json"})
        cfg = settings(**cfg_args)
        try:
            docs = mb.load_documents(real)
        except mb.InputError as exc:
            raise BankError(str(exc)) from exc
        return self._match(docs, cfg)

    def _match(self, docs, cfg):
        lines = self.lines()
        results, taken = mb.match(docs, lines, cfg)
        counts = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {"statement": self._path, "status_counts": counts,
                "settings": {**cfg, "tolerance": float(cfg["tolerance"])},
                "documents": results,
                "unmatched_outgoing_bank_lines": [_line_out(ln) for ln in lines
                                                  if ln["amount"] < 0 and ln["id"] not in taken]}

