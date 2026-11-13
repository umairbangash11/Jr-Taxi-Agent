"""Booked-entry store for ledger-mcp (no MCP dependency, unit-testable).

SQLite, amounts as integer øre. Bookkeeping rules enforced in the database:
  * entries and lines can't be deleted; lines can't be changed; an entry's booked
    content can't be changed (only status/reversed_by when it is reversed)
  * corrections are reversal entries (reverse_entry), never edits
  * bilag numbers are gapless per year: YYYY-NNNNN, allocated inside the write transaction
  * every booking/refusal/override/reversal is written to an append-only audit log

Only bilag that passed qa-validator (qa_status == "passed") can be booked.

Duplicate levels:
  duplicate           same source document (sha256), identical lines, or same supplier +
                      invoice number  -> booking always refused
  possible_duplicate  same supplier + amount within 7 days, or same amount + date where the
                      supplier can't be told apart -> refused unless overridden with a reason
"""

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
from decimal import Decimal, InvalidOperation

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_DB = os.path.join(PROJECT_ROOT, "data", "ledger.sqlite")
NEAR_DAYS = 7
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY,
  bilag_no TEXT NOT NULL UNIQUE,
  year INTEGER NOT NULL,
  seq INTEGER NOT NULL,
  date TEXT NOT NULL,
  document_type TEXT,
  supplier_id TEXT,
  org_number TEXT,
  vendor_name TEXT,
  vendor_key TEXT,
  invoice_number TEXT,
  invoice_key TEXT,
  total_cents INTEGER NOT NULL,
  currency TEXT NOT NULL,
  description TEXT,
  source_file TEXT,
  source_sha256 TEXT,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('booked', 'reversed', 'reversal')),
  reversal_of TEXT,
  reversed_by TEXT,
  booked_at TEXT NOT NULL,
  booked_by TEXT NOT NULL,
  note TEXT,
  UNIQUE (year, seq)
);
CREATE INDEX IF NOT EXISTS ix_entries_invoice ON entries (invoice_key);
CREATE INDEX IF NOT EXISTS ix_entries_amount_date ON entries (total_cents, date);
CREATE INDEX IF NOT EXISTS ix_entries_sha ON entries (source_sha256);
CREATE INDEX IF NOT EXISTS ix_entries_content ON entries (content_hash);

CREATE TABLE IF NOT EXISTS lines (
  entry_id INTEGER NOT NULL REFERENCES entries (id),
  line_no INTEGER NOT NULL,
  konto TEXT NOT NULL,
  mk TEXT,
  debet_cents INTEGER,
  kredit_cents INTEGER,
  loyve TEXT,
  bil TEXT,
  tekst TEXT,
  supplier_id TEXT,
  PRIMARY KEY (entry_id, line_no)
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  actor TEXT,
  action TEXT NOT NULL,
  bilag_no TEXT,
  detail TEXT
);

CREATE TRIGGER IF NOT EXISTS entries_no_delete BEFORE DELETE ON entries
BEGIN SELECT RAISE(ABORT, 'entries are append-only; use reverse_entry'); END;
CREATE TRIGGER IF NOT EXISTS entries_immutable BEFORE UPDATE OF
  bilag_no, year, seq, date, document_type, supplier_id, org_number, vendor_name, vendor_key,
  invoice_number, invoice_key, total_cents, currency, description, source_file, source_sha256,
  content_hash, reversal_of, booked_at, booked_by, note ON entries
BEGIN SELECT RAISE(ABORT, 'booked entries are immutable; use reverse_entry'); END;
CREATE TRIGGER IF NOT EXISTS entries_status_once BEFORE UPDATE OF status ON entries
WHEN NOT (OLD.status = 'booked' AND NEW.status = 'reversed')
BEGIN SELECT RAISE(ABORT, 'only booked -> reversed is allowed'); END;
CREATE TRIGGER IF NOT EXISTS lines_no_delete BEFORE DELETE ON lines
BEGIN SELECT RAISE(ABORT, 'lines are append-only'); END;
CREATE TRIGGER IF NOT EXISTS lines_immutable BEFORE UPDATE ON lines
BEGIN SELECT RAISE(ABORT, 'lines are immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""


class LedgerError(Exception):
    """User-facing error (bad input, unknown bilag, not allowed)."""


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def to_cents(value, what):
    if value is None or value == "":
        return None
    try:
        d = Decimal(str(value).replace(" ", "").replace(",", ".")) * 100
    except InvalidOperation:
        raise LedgerError(f"{what} is not a number: {value!r}")
    if d != d.to_integral_value():
        raise LedgerError(f"{what} has more than 2 decimals: {value!r}")
    return int(d)


def from_cents(c):
    return None if c is None else float(Decimal(c) / 100)


def invoice_key(s):
    """'INV-000417' == 'inv 417' == 'INV000417': alphanumerics, upper, no leading zeros
    in the numeric part."""
    if not s:
        return None
    groups = re.findall(r"[0-9A-ZÆØÅ]+", str(s).upper())
    k = "".join(re.sub(r"(?<![0-9])0+(?=[0-9])", "", g) for g in groups)
    return k or None


def vendor_key(s):
    if not s:
        return None
    s = re.sub(r"\b(AS|ASA|ANS|DA|ENK|NUF|SA|NORGE|NORWAY)\b\.?", "", s, flags=re.I)
    return re.sub(r"[^0-9a-zæøå]", "", s.casefold()) or None


def digits(s):
    return re.sub(r"\D", "", str(s or "")) or None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def content_hash(date, lines):
    canon = [date] + [[ln["konto"], ln["mk"] or "", ln["debet_cents"] or 0,
                       ln["kredit_cents"] or 0, ln["loyve"] or "", ln["bil"] or ""]
                      for ln in lines]
    return hashlib.sha256(json.dumps(canon, separators=(",", ":")).encode()).hexdigest()


def _parse_date(s, what="date"):
    try:
        return dt.date.fromisoformat(str(s))
    except (TypeError, ValueError):
        raise LedgerError(f"{what} must be YYYY-MM-DD, got {s!r}")


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class LedgerStore:
    def __init__(self, db_path=None, today=None, clock=None):
        self.db_path = db_path or os.environ.get("LEDGER_DB") or DEFAULT_DB
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._today = today
        self._clock = clock
        self.db = sqlite3.connect(self.db_path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        if self.db_path != ":memory:":
            self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        elif version > SCHEMA_VERSION:
            raise LedgerError(f"Database schema v{version} is newer than this server "
                              f"(v{SCHEMA_VERSION})")

    def close(self):
        self.db.close()

    def today(self):
        return self._today or dt.date.today()

    def now(self):
        return (self._clock() if self._clock else
                dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")

    def _audit(self, action, actor=None, bilag_no=None, **detail):
        self.db.execute("INSERT INTO audit_log (at, actor, action, bilag_no, detail) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (self.now(), actor, action, bilag_no,
                         json.dumps(detail, ensure_ascii=False, default=str)))

    # -- input normalisation ----------------------------------------------
    def _normalize(self, bilag, require_qa=True):
        if not isinstance(bilag, dict):
            raise LedgerError("bilag must be an object (qa-validator output item)")
        if require_qa and bilag.get("qa_status") != "passed":
            raise LedgerError(f"Only bilag that passed qa-validator can be booked "
                              f"(qa_status={bilag.get('qa_status')!r}). Run qa-validator first.")
        h = bilag.get("header") or {}
        date = _parse_date(h.get("date"), "header.date")
        if date > self.today():
            raise LedgerError(f"Date {date} is in the future")
        currency = h.get("currency") or "NOK"
        if currency != "NOK":
            raise LedgerError(f"Currency {currency} not supported; amounts must be NOK")
        raw = bilag.get("lines") or []
        if len(raw) < 2:
            raise LedgerError("A bilag needs at least two lines")
        lines, d_sum, k_sum = [], 0, 0
        for n, ln in enumerate(raw, 1):
            d = to_cents(ln.get("debet"), f"line {n} debet")
            k = to_cents(ln.get("kredit"), f"line {n} kredit")
            if (d is None) == (k is None) or (d is not None and d <= 0) or \
                    (k is not None and k <= 0):
                raise LedgerError(f"Line {n} must have exactly one positive debet or kredit")
            if not ln.get("konto"):
                raise LedgerError(f"Line {n} has no konto")
            d_sum += d or 0
            k_sum += k or 0
            lines.append({"line_no": n, "konto": str(ln["konto"]),
                          "mk": None if ln.get("mk") in (None, "") else str(ln["mk"]),
                          "debet_cents": d, "kredit_cents": k, "loyve": ln.get("loyve"),
                          "bil": ln.get("bil"), "tekst": ln.get("tekst"),
                          "supplier_id": ln.get("supplier_id")})
        if d_sum != k_sum:
            raise LedgerError(f"Unbalanced: debet {from_cents(d_sum)} ≠ kredit {from_cents(k_sum)}")
        total = to_cents(h.get("total_amount"), "header.total_amount")
        if total is not None and total != d_sum:
            raise LedgerError(f"header.total_amount {from_cents(total)} ≠ lines {from_cents(d_sum)}")

        source = bilag.get("source_file")
        sha = bilag.get("source_sha256")
        if not sha and source and os.path.isfile(source):
            sha = sha256_file(source)
        return {"date": date.isoformat(), "document_type": h.get("document_type"),
                "supplier_id": h.get("supplier_id"),
                "org_number": digits(h.get("vendor_org_number") or bilag.get("org_number")),
                "vendor_name": h.get("vendor_name"), "vendor_key": vendor_key(h.get("vendor_name")),
                "invoice_number": h.get("invoice_number"),
                "invoice_key": invoice_key(h.get("invoice_number")),
                "total_cents": d_sum, "currency": currency, "description": h.get("description"),
                "source_file": source, "source_sha256": sha,
                "content_hash": content_hash(date.isoformat(), lines), "lines": lines}

    @staticmethod
    def _fields_from_simple(q):
        """check_duplicate also accepts loose fields instead of a full bilag."""
        total = to_cents(q.get("amount", q.get("total_amount")), "amount")
        date = q.get("date")
        if date:
            date = _parse_date(date).isoformat()
        sha = q.get("source_sha256")
        if not sha and q.get("source_file") and os.path.isfile(q["source_file"]):
            sha = sha256_file(q["source_file"])
        name = q.get("vendor_name") or q.get("vendor") or q.get("supplier")
        return {"date": date, "supplier_id": q.get("supplier_id"),
                "org_number": digits(q.get("org_number") or q.get("vendor_org_number")),
                "vendor_name": name, "vendor_key": vendor_key(name),
                "invoice_number": q.get("invoice_number"),
                "invoice_key": invoice_key(q.get("invoice_number")),
                "total_cents": total, "source_sha256": sha, "content_hash": None}

    # -- duplicate detection ----------------------------------------------
    @staticmethod
    def _supplier_relation(a, b):
        """'same' | 'different' | 'unknown'"""
        pairs = [(a["supplier_id"], b["supplier_id"]), (a["org_number"], b["org_number"]),
                 (a["vendor_key"], b["vendor_key"])]
        if any(x and y and x == y for x, y in pairs):
            return "same"
        if any(x and y and x != y for x, y in pairs):
            return "different"
        return "unknown"

    def _check(self, f):
        params, conds = [], []
        for col in ("invoice_key", "source_sha256", "content_hash"):
            if f.get(col):
                conds.append(f"{col} = ?")
                params.append(f[col])
        if f.get("total_cents") is not None:
            if f.get("date"):
                d = dt.date.fromisoformat(f["date"])
                conds.append("(total_cents = ? AND date BETWEEN ? AND ?)")
                params += [f["total_cents"], (d - dt.timedelta(days=NEAR_DAYS)).isoformat(),
                           (d + dt.timedelta(days=NEAR_DAYS)).isoformat()]
            else:
                conds.append("total_cents = ?")
                params.append(f["total_cents"])
        if not conds:
            raise LedgerError("Give at least an amount, invoice number or source document")
        rows = self.db.execute(
            f"SELECT * FROM entries WHERE status IN ('booked', 'reversed') AND ({' OR '.join(conds)})"
            " ORDER BY date, bilag_no", params).fetchall()

        matches = []
        for r in rows:
            e = dict(r)
            rel = self._supplier_relation(f, e)
            inv_differs = bool(f.get("invoice_key") and e["invoice_key"]
                               and f["invoice_key"] != e["invoice_key"])
            level, reasons = None, []
            if f.get("source_sha256") and f["source_sha256"] == e["source_sha256"]:
                level = "duplicate"
                reasons.append("same source document (identical file)")
            if f.get("invoice_key") and f["invoice_key"] == e["invoice_key"] and rel == "same":
                level = "duplicate"
                reasons.append(f"same supplier and invoice number ({e['invoice_number']})")
            if f.get("content_hash") and f["content_hash"] == e["content_hash"]:
                if inv_differs:
                    # Two invoices can legitimately have identical lines; the differing
                    # invoice numbers say they are separate documents.
                    level = level or "possible_duplicate"
                    reasons.append("identical date and lines, but different invoice number")
                else:
                    level = "duplicate"
                    reasons.append("identical date and lines")
            if f.get("total_cents") == e["total_cents"] and level is None:
                days = (abs((dt.date.fromisoformat(f["date"]) -
                             dt.date.fromisoformat(e["date"])).days) if f.get("date") else None)
                if rel == "same" and days is not None and days <= NEAR_DAYS and not inv_differs:
                    level = "possible_duplicate"
                    reasons.append(f"same supplier and amount, {days} day(s) apart")
                elif rel == "same" and inv_differs and days == 0:
                    level = "possible_duplicate"
                    reasons.append("same supplier, amount and date but different invoice number")
                elif rel == "unknown" and days == 0:
                    level = "possible_duplicate"
                    reasons.append("same amount and date; supplier can't be compared")
            if level:
                matches.append({"bilag_no": e["bilag_no"], "level": level,
                                "entry_status": e["status"], "reasons": reasons,
                                "date": e["date"], "amount": from_cents(e["total_cents"]),
                                "vendor_name": e["vendor_name"], "supplier_id": e["supplier_id"],
                                "invoice_number": e["invoice_number"],
                                "source_file": e["source_file"]})

        active = [m for m in matches if m["entry_status"] == "booked"]
        if any(m["level"] == "duplicate" for m in active):
            status = "duplicate"
        elif active:
            status = "possible_duplicate"
        else:
            status = "unique"
        return {"status": status, "matches": active,
                "previously_reversed": [m for m in matches if m["entry_status"] == "reversed"]}

    def check_duplicate(self, bilag):
        if not isinstance(bilag, dict):
            raise LedgerError("bilag must be an object")
        f = (self._normalize(bilag, require_qa=False) if bilag.get("lines")
             else self._fields_from_simple(bilag))
        return self._check(f)

    # -- booking ----------------------------------------------------------
    def _next_no(self, year):
        seq = self.db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM entries WHERE year = ?",
                              (year,)).fetchone()[0]
        return seq, f"{year}-{seq:05d}"

    def _insert(self, f, status, booked_by, note=None, reversal_of=None):
        year = int(f["date"][:4])
        seq, no = self._next_no(year)
        cur = self.db.execute(
            "INSERT INTO entries (bilag_no, year, seq, date, document_type, supplier_id, "
            "org_number, vendor_name, vendor_key, invoice_number, invoice_key, total_cents, "
            "currency, description, source_file, source_sha256, content_hash, status, "
            "reversal_of, booked_at, booked_by, note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, year, seq, f["date"], f.get("document_type"), f.get("supplier_id"),
             f.get("org_number"), f.get("vendor_name"), f.get("vendor_key"),
             f.get("invoice_number"), f.get("invoice_key"), f["total_cents"], f["currency"],
             f.get("description"), f.get("source_file"), f.get("source_sha256"),
             f["content_hash"], status, reversal_of, self.now(), booked_by, note))
        for ln in f["lines"]:
            self.db.execute(
                "INSERT INTO lines (entry_id, line_no, konto, mk, debet_cents, kredit_cents, "
                "loyve, bil, tekst, supplier_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cur.lastrowid, ln["line_no"], ln["konto"], ln["mk"], ln["debet_cents"],
                 ln["kredit_cents"], ln["loyve"], ln["bil"], ln["tekst"], ln["supplier_id"]))
        return no

    def book(self, bilag, booked_by, allow_possible_duplicate=False, override_reason=None):
        booked_by = (booked_by or "").strip()
        if not booked_by:
            raise LedgerError("booked_by (the person approving the booking) is required")
        f = self._normalize(bilag)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            check = self._check(f)
            refused = None
            if check["status"] == "duplicate":
                refused = "Duplicate of an already booked entry; booking refused"
            elif check["status"] == "possible_duplicate":
                if not allow_possible_duplicate:
                    refused = ("Possible duplicate; confirm with the user, then retry with "
                               "allow_possible_duplicate=true and an override_reason")
                elif not (override_reason or "").strip():
                    refused = "override_reason is required to book a possible duplicate"
            if refused:
                self._audit("refused", booked_by, None, reason=refused,
                            source_file=f["source_file"], invoice_number=f["invoice_number"],
                            amount=from_cents(f["total_cents"]),
                            matches=[m["bilag_no"] for m in check["matches"]])
                self.db.execute("COMMIT")
                return {"booked": False, "reason": refused, "duplicate_check": check}
            note = None
            if check["status"] == "possible_duplicate":
                note = f"Booked despite possible duplicate of " \
                       f"{', '.join(m['bilag_no'] for m in check['matches'])}: {override_reason}"
            no = self._insert(f, "booked", booked_by, note)
            self._audit("book", booked_by, no, source_file=f["source_file"],
                        amount=from_cents(f["total_cents"]),
                        override=note is not None, note=note)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return {"booked": True, "bilag_no": no, "duplicate_check": check,
                "entry": self.get_entry(no)}

    def book_file(self, path, booked_by):
        """Book every passed bilag in a qa-validator JSON file (no overrides)."""
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerError(f"Cannot read {path}: {exc}")
        items = data.get("bilag") if isinstance(data, dict) else None
        if items is None:
            raise LedgerError("Expected qa-validator output with a 'bilag' list")
        results = []
        for b in items:
            src = b.get("source_file")
            if b.get("qa_status") != "passed":
                results.append({"source_file": src, "booked": False,
                                "reason": f"qa_status is {b.get('qa_status')!r}"})
                continue
            try:
                r = self.book(b, booked_by)
            except LedgerError as exc:
                r = {"booked": False, "reason": str(exc)}
            r.pop("entry", None)
            results.append({"source_file": src, **r})
        return {"booked": sum(r["booked"] for r in results),
                "refused": sum(not r["booked"] for r in results), "results": results}

    def reverse(self, bilag_no, reason, booked_by, date=None):
        booked_by = (booked_by or "").strip()
        if not booked_by or not (reason or "").strip():
            raise LedgerError("reason and booked_by are required to reverse an entry")
        orig = self.db.execute("SELECT * FROM entries WHERE bilag_no = ?", (bilag_no,)).fetchone()
        if not orig:
            raise LedgerError(f"Bilag {bilag_no} not found")
        if orig["status"] != "booked":
            raise LedgerError(f"Bilag {bilag_no} has status {orig['status']}; only booked "
                              "entries can be reversed")
        rdate = _parse_date(date, "date") if date else self.today()
        if rdate < dt.date.fromisoformat(orig["date"]):
            raise LedgerError("Reversal date can't be before the original date")
        lines = [{**dict(ln), "debet_cents": ln["kredit_cents"], "kredit_cents": ln["debet_cents"],
                  "tekst": f"Reversering av {bilag_no}"}
                 for ln in self.db.execute("SELECT * FROM lines WHERE entry_id = ? "
                                           "ORDER BY line_no", (orig["id"],))]
        f = {**dict(orig), "date": rdate.isoformat(), "source_sha256": None,
             "description": f"Reversering av {bilag_no}: {reason}", "lines": lines}
        f["content_hash"] = content_hash(f["date"], lines)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            no = self._insert(f, "reversal", booked_by, note=reason, reversal_of=bilag_no)
            self.db.execute("UPDATE entries SET status = 'reversed', reversed_by = ? "
                            "WHERE bilag_no = ?", (no, bilag_no))
            self._audit("reverse", booked_by, bilag_no, reversal=no, reason=reason)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return {"reversed": bilag_no, "reversal_bilag_no": no, "entry": self.get_entry(no)}

    # -- reads ------------------------------------------------------------
    def get_entry(self, bilag_no):
        e = self.db.execute("SELECT * FROM entries WHERE bilag_no = ?", (bilag_no,)).fetchone()
        if not e:
            raise LedgerError(f"Bilag {bilag_no} not found")
        lines = self.db.execute("SELECT * FROM lines WHERE entry_id = ? ORDER BY line_no",
                                (e["id"],)).fetchall()
        out = {k: e[k] for k in e.keys()
               if k not in ("id", "year", "seq", "vendor_key", "invoice_key", "total_cents")}
        out["total_amount"] = from_cents(e["total_cents"])
        out["lines"] = [{"konto": ln["konto"], "mk": ln["mk"],
                         "debet": from_cents(ln["debet_cents"]),
                         "kredit": from_cents(ln["kredit_cents"]), "loyve": ln["loyve"],
                         "bil": ln["bil"], "tekst": ln["tekst"], "supplier_id": ln["supplier_id"]}
                        for ln in lines]
        return out

    def list_entries(self, date_from=None, date_to=None, supplier=None, status=None,
                     limit=None):
        conds, params = [], []
        if date_from:
            conds.append("date >= ?")
            params.append(_parse_date(date_from, "date_from").isoformat())
        if date_to:
            conds.append("date <= ?")
            params.append(_parse_date(date_to, "date_to").isoformat())
        if status:
            if status not in ("booked", "reversed", "reversal"):
                raise LedgerError("status must be booked, reversed or reversal")
            conds.append("status = ?")
            params.append(status)
        if supplier:
            conds.append("(supplier_id = ? OR org_number = ? OR vendor_key LIKE ?)")
            params += [supplier, digits(supplier) or "-", f"%{vendor_key(supplier) or '-'}%"]
        limit = 200 if limit is None else max(1, min(int(limit), 1000))
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        total = self.db.execute(f"SELECT COUNT(*) FROM entries {where}", params).fetchone()[0]
        rows = self.db.execute(
            f"SELECT bilag_no, date, document_type, vendor_name, supplier_id, invoice_number, "
            f"total_cents, status, reversal_of, reversed_by, booked_by, booked_at FROM entries "
            f"{where} ORDER BY year, seq LIMIT ?", params + [limit]).fetchall()
        items = [{**{k: r[k] for k in r.keys() if k != "total_cents"},
                  "total_amount": from_cents(r["total_cents"])} for r in rows]
        return {"total": total, "returned": len(items), "truncated": total > len(items),
                "items": items}

    def audit_log(self, bilag_no=None, limit=None):
        limit = 200 if limit is None else max(1, min(int(limit), 1000))
        if bilag_no:
            rows = self.db.execute("SELECT * FROM audit_log WHERE bilag_no = ? OR detail LIKE ? "
                                   "ORDER BY id DESC LIMIT ?",
                                   (bilag_no, f'%"{bilag_no}"%', limit)).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                                   (limit,)).fetchall()
        return [{**dict(r), "detail": json.loads(r["detail"]) if r["detail"] else None}
                for r in rows]

    def summary(self):
        rows = self.db.execute("SELECT status, COUNT(*) n, SUM(total_cents) s FROM entries "
                               "GROUP BY status").fetchall()
        years = self.db.execute("SELECT year, COUNT(*) n, MAX(seq) last FROM entries "
                                "GROUP BY year ORDER BY year").fetchall()
        return {"database": os.path.abspath(self.db_path) if self.db_path != ":memory:"
                else ":memory:",
                "by_status": {r["status"]: {"count": r["n"], "amount": from_cents(r["s"])}
                              for r in rows},
                "by_year": [{"year": y["year"], "entries": y["n"],
                             "last_bilag_no": f"{y['year']}-{y['last']:05d}"} for y in years],
                "audit_events": self.db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]}
