"""Ledger-vs-bank reconciliation for reconcile-mcp (no MCP dependency, unit-testable).

Ledger side: postings on the bank GL account (default 1920) from SAF-T, read with the
saft-parser skill's read_account_postings (each posting carries its full voucher/bilag).
Bank side: statement lines read with the bank-matcher skill's read_bank (CSV or CAMT);
CAMT opening/closing balances are read here.

Matching: exact signed amount, |ledger date - bank date| <= date_window days, one-to-one,
best first (closest date, then text overlap). Leftovers are then tried as combinations
(2-3 lines on one side summing exactly to one line on the other). What remains is the
difference, itemised by bilag (ledger side) and by bank line (bank side):

    ledger_close - bank_close = sum(ledger_only) - sum(bank_only) + unexplained
"""

import itertools
import os
import re
import sys
from decimal import Decimal

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SKILLS = os.path.join(PROJECT_ROOT, ".claude", "skills")
sys.path.insert(0, os.path.join(SKILLS, "saft-parser", "scripts"))
sys.path.insert(0, os.path.join(SKILLS, "bank-matcher", "scripts"))

import match_bank as mb  # noqa: E402
from parse_saft import SaftError, read_account_postings  # noqa: E402

try:
    from defusedxml.ElementTree import parse as xml_parse
except ImportError:  # pragma: no cover
    from xml.etree.ElementTree import parse as xml_parse

ZERO = Decimal("0.00")
MAX_COMBO = 3
MAX_COMBO_POOL = 30
BANK_EXTS = {".csv", ".txt", ".xml"}


class ReconcileError(Exception):
    """User-facing error."""


def D(v):
    return Decimal(str(v)).quantize(Decimal("0.01"))


def f(v):
    return None if v is None else float(v)


def _words(s):
    return {w for w in re.findall(r"[0-9a-zæøå]{3,}", (s or "").casefold())} - mb.STOPWORDS


def camt_balances(path):
    """{'opening': (date, Decimal) | None, 'closing': ...} from CAMT Bal elements."""
    out = {"opening": None, "closing": None}
    try:
        root = xml_parse(path).getroot()
    except Exception:
        return out
    for bal in mb._find_all(root, "Bal"):
        code = mb._first_text(bal, "Tp", "CdOrPrtry", "Cd")
        amt_el = next((e for e in bal if mb._local(e.tag) == "Amt"), None)
        ind = next((e.text for e in bal if mb._local(e.tag) == "CdtDbtInd"), "CRDT")
        amount = mb.parse_amount(amt_el.text if amt_el is not None else None)
        date = mb.parse_date(mb._first_text(bal, "Dt", "Dt") or mb._first_text(bal, "Dt", "DtTm"))
        if amount is None:
            continue
        amount = -amount if ind == "DBIT" else amount
        if code in ("OPBD", "PRCD") and out["opening"] is None:
            out["opening"] = (date, amount)
        elif code in ("CLBD",):
            out["closing"] = (date, amount)
    return out


class ReconcileStore:
    def __init__(self, roots=None):
        if roots is None:
            env = os.environ.get("RECONCILE_ROOTS", "")
            roots = [r for r in env.split(os.pathsep) if r.strip()]
        self.roots = [os.path.realpath(os.path.expanduser(r)) for r in roots]
        self._ledger = None   # dict
        self._ledger_key = None
        self._bank = None     # dict
        self._bank_key = None

    # -- loading ------------------------------------------------------------
    def _resolve(self, path, exts):
        if not path or not str(path).strip():
            raise ReconcileError("path is required")
        real = os.path.realpath(os.path.expanduser(str(path)))
        if self.roots and not any(real == r or real.startswith(r + os.sep) for r in self.roots):
            raise ReconcileError(f"{path} is outside the allowed RECONCILE_ROOTS: {self.roots}")
        if not os.path.isfile(real):
            raise ReconcileError(f"File not found: {path}")
        if os.path.splitext(real)[1].lower() not in exts:
            raise ReconcileError(f"Unsupported file type; allowed: {sorted(exts)}")
        return real

    @staticmethod
    def _stamp(real):
        st = os.stat(real)
        return (st.st_size, st.st_mtime_ns)

    def load_ledger(self, saft_path, account_id="1920"):
        real = self._resolve(saft_path, {".xml"})
        account_id = str(account_id).strip()
        try:
            data = read_account_postings(real, [account_id])
        except SaftError as exc:
            raise ReconcileError(f"Cannot read SAF-T: {exc}") from exc
        if account_id not in data["accounts"]:
            raise ReconcileError(f"Account {account_id} is not in the SAF-T chart of accounts")
        postings = []
        for p in data["postings"]:
            date = mb.parse_date(p["date"])
            if date is None:
                data["meta"]["warnings"].append(
                    f"Bilag {p['transaction_id']} skipped: no valid TransactionDate")
                continue
            postings.append({**p, "date": date, "amount": D(p["amount"])})
        acc = data["accounts"][account_id]
        self._ledger = {"file": real, "account_id": account_id,
                        "description": acc["description"],
                        "saft_opening_balance": D(acc["opening_balance"]),
                        "saft_closing_balance": D(acc["closing_balance"]),
                        "period": data["meta"].get("selection_criteria"),
                        "postings": postings, "warnings": data["meta"]["warnings"]}
        self._ledger_key = (real, account_id, self._stamp(real))
        return self.ledger_summary()

    def load_bank(self, path, date_col=None, text_cols=None, amount_col=None, out_col=None,
                  in_col=None):
        real = self._resolve(path, BANK_EXTS)
        cols = {"date_col": date_col, "text_cols": text_cols or None, "amount_col": amount_col,
                "out_col": out_col, "in_col": in_col}
        try:
            lines, warnings = mb.read_bank(real, **cols)
        except mb.InputError as exc:
            raise ReconcileError(str(exc)) from exc
        except Exception as exc:
            raise ReconcileError(f"Cannot read {path}: {type(exc).__name__}: {exc}") from exc
        balances = camt_balances(real) if real.lower().endswith(".xml") else \
            {"opening": None, "closing": None}
        self._bank = {"file": real, "lines": lines, "warnings": warnings, "balances": balances,
                      "cols": cols}
        self._bank_key = (real, self._stamp(real))
        return self.bank_summary()

    def _fresh(self):
        if self._ledger is None:
            raise ReconcileError("No ledger loaded. Call load_ledger(saft_path, account_id).")
        if self._bank is None:
            raise ReconcileError("No bank statement loaded. Call load_bank_statement(path).")
        real, account_id, stamp = self._ledger_key
        if self._stamp(real) != stamp:
            self.load_ledger(real, account_id)
        real, stamp = self._bank_key
        if self._stamp(real) != stamp:
            self.load_bank(real, **self._bank["cols"])

    def ledger_summary(self):
        lg = self._ledger
        dates = [p["date"] for p in lg["postings"]]
        return {"file": lg["file"], "account_id": lg["account_id"],
                "description": lg["description"], "postings": len(lg["postings"]),
                "saft_opening_balance": f(lg["saft_opening_balance"]),
                "saft_closing_balance": f(lg["saft_closing_balance"]),
                "date_from": min(dates).isoformat() if dates else None,
                "date_to": max(dates).isoformat() if dates else None,
                "saft_period": lg["period"], "warnings": lg["warnings"]}

    def bank_summary(self):
        bk = self._bank
        dates = [ln["date"] for ln in bk["lines"]]
        bal = {k: (None if v is None else {"date": v[0].isoformat() if v[0] else None,
                                           "amount": f(v[1])})
               for k, v in bk["balances"].items()}
        return {"file": bk["file"], "lines": len(bk["lines"]),
                "date_from": min(dates).isoformat() if dates else None,
                "date_to": max(dates).isoformat() if dates else None,
                "statement_balances": bal, "warnings": bk["warnings"]}

    # -- bilag lookup -------------------------------------------------------
    def get_bilag(self, transaction_id):
        if self._ledger is None:
            raise ReconcileError("No ledger loaded. Call load_ledger(saft_path, account_id).")
        hits = [p for p in self._ledger["postings"] if p["transaction_id"] == str(transaction_id)]
        if not hits:
            raise ReconcileError(f"Bilag {transaction_id} has no posting on account "
                                 f"{self._ledger['account_id']}")
        return hits[0]["voucher"]

    # -- reconciliation -----------------------------------------------------
    def reconcile(self, date_from=None, date_to=None, bank_opening_balance=None,
                  bank_closing_balance=None, date_window=5):
        self._fresh()
        if not 0 <= int(date_window) <= 31:
            raise ReconcileError("date_window must be between 0 and 31 days")
        window = int(date_window)
        lg, bk = self._ledger, self._bank
        bank_lines = bk["lines"]
        lo = mb.parse_date(date_from) if date_from else (
            min(ln["date"] for ln in bank_lines) if bank_lines else None)
        hi = mb.parse_date(date_to) if date_to else (
            max(ln["date"] for ln in bank_lines) if bank_lines else None)
        if (date_from and lo is None) or (date_to and hi is None):
            raise ReconcileError("date_from/date_to must be dates like 2025-06-30")
        if lo is None or hi is None:
            raise ReconcileError("Bank statement is empty; give date_from and date_to")
        if lo > hi:
            raise ReconcileError("date_from is after date_to")

        ledger = [p for p in lg["postings"] if lo <= p["date"] <= hi]
        bank = [ln for ln in bank_lines if lo <= ln["date"] <= hi]
        before = sum((p["amount"] for p in lg["postings"] if p["date"] < lo), ZERO)
        ledger_open = lg["saft_opening_balance"] + before
        ledger_move = sum((p["amount"] for p in ledger), ZERO)
        ledger_close = ledger_open + ledger_move
        bank_move = sum((ln["amount"] for ln in bank), ZERO)
        warnings = []
        if not ledger and not bank:
            warnings.append("Neither ledger postings nor bank lines fall in the period")

        bank_open, bank_close, bal_source = self._bank_balances(
            bank_opening_balance, bank_closing_balance, bank_move, lo, hi, warnings)

        pairs, ambiguous = self._match_one_to_one(ledger, bank, window)
        matched_l = {id(p) for p, _ in pairs}
        matched_b = {ln["id"] for _, ln in pairs}
        rest_l = [p for p in ledger if id(p) not in matched_l]
        rest_b = [ln for ln in bank if ln["id"] not in matched_b]
        combos, possible = self._match_combinations(rest_l, rest_b, window)
        for c in combos:
            for p in c["_ledger"]:
                matched_l.add(id(p))
            for ln in c["_bank"]:
                matched_b.add(ln["id"])
        ledger_only = [p for p in ledger if id(p) not in matched_l]
        bank_only = [ln for ln in bank if ln["id"] not in matched_b]

        lo_sum = sum((p["amount"] for p in ledger_only), ZERO)
        bo_sum = sum((ln["amount"] for ln in bank_only), ZERO)
        explained = lo_sum - bo_sum
        diff_close = None if bank_close is None else ledger_close - bank_close
        diff_open = None if bank_open is None else ledger_open - bank_open
        unexplained = None if diff_close is None else diff_close - explained
        if unexplained:
            opening = (f"opening difference is {diff_open}" if diff_open is not None
                       else "bank opening balance unknown")
            warnings.append(f"Unexplained difference {unexplained} ({opening}): opening "
                            "balances differ or reconciling items fall outside the period")

        status = "reconciled" if not ledger_only and not bank_only and not unexplained \
            and (diff_close in (None, ZERO)) else "differences"
        if diff_close is None:
            warnings.append("Bank balances unknown (CSV without balances): only movements "
                            "are compared. Pass bank_closing_balance for a balance check.")

        return {
            "status": status,
            "account_id": lg["account_id"],
            "period": {"from": lo.isoformat(), "to": hi.isoformat()},
            "ledger": {"opening_balance": f(ledger_open), "movement": f(ledger_move),
                       "closing_balance": f(ledger_close), "postings": len(ledger)},
            "bank": {"opening_balance": f(bank_open), "movement": f(bank_move),
                     "closing_balance": f(bank_close), "lines": len(bank),
                     "balance_source": bal_source},
            "difference": {"closing_balance": f(diff_close), "opening_balance": f(diff_open),
                           "movement": f(ledger_move - bank_move),
                           "explained_by_items": f(explained), "unexplained": f(unexplained),
                           "sign": "ledger minus bank"},
            "ledger_only": [self._bilag_out(p) for p in sorted(ledger_only,
                                                               key=lambda p: p["date"])],
            "bank_only": [{**self._bank_out(ln), "reason": "On the bank statement but not "
                           "posted on the ledger account — missing bilag?"}
                          for ln in sorted(bank_only, key=lambda ln: ln["date"])],
            "combined_matches": [{k: v for k, v in c.items() if not k.startswith("_")}
                                 for c in combos],
            "possible_combinations": possible,
            "ambiguous_pairings": ambiguous,
            "matched_one_to_one": len(pairs),
            "settings": {"date_window": window},
            "warnings": warnings,
        }

    def _bank_balances(self, opening, closing, bank_move, lo, hi, warnings):
        stmt = self._bank["balances"]
        if opening is not None or closing is not None:
            o = None if opening is None else D(opening)
            c = None if closing is None else D(closing)
            if o is None and c is not None:
                o = c - bank_move
            if c is None and o is not None:
                c = o + bank_move
            return o, c, "user"
        # Statement balances: roll the opening balance forward to the period start and the
        # closing balance back to the period end, using the statement's own lines.
        so, sc = stmt["opening"], stmt["closing"]
        if not so and not sc:
            return None, None, None
        lines = self._bank["lines"]
        o = c = None
        if so:
            d0, amt = so
            if d0 is not None and d0 > lo:
                warnings.append(f"Statement opening balance is dated {d0}, after period start")
            else:
                o = amt + sum((ln["amount"] for ln in lines
                               if (d0 is None or ln["date"] >= d0) and ln["date"] < lo), ZERO)
        if sc:
            d1, amt = sc
            if d1 is not None and d1 < hi:
                warnings.append(f"Statement closing balance is dated {d1}, before period end")
            else:
                c = amt - sum((ln["amount"] for ln in lines
                               if ln["date"] > hi and (d1 is None or ln["date"] <= d1)), ZERO)
        if o is not None and c is not None and o + bank_move != c:
            warnings.append(f"Statement balances inconsistent with its lines: "
                            f"{o} + {bank_move} ≠ {c}")
        if o is None and c is not None:
            o = c - bank_move
        elif c is None and o is not None:
            c = o + bank_move
        return o, c, ("statement" if o is not None else None)

    @staticmethod
    def _score(p, ln):
        days = abs((ln["date"] - p["date"]).days)
        overlap = len(_words(p["description"]) & _words(ln["text"]))
        ref = 5 if p["transaction_id"] and len(p["transaction_id"]) >= 4 and \
            p["transaction_id"] in (ln["text"] or "") else 0
        return 100 - 5 * days + min(overlap, 3) * 3 + ref

    def _match_one_to_one(self, ledger, bank, window):
        cands = []
        for p in ledger:
            for ln in bank:
                if ln["amount"] == p["amount"] and abs((ln["date"] - p["date"]).days) <= window:
                    cands.append((self._score(p, ln), p, ln))
        cands.sort(key=lambda c: (-c[0], c[1]["date"], c[2]["id"]))
        used_l, used_b, pairs, scores = set(), set(), [], {}
        for s, p, ln in cands:
            if id(p) in used_l or ln["id"] in used_b:
                continue
            used_l.add(id(p))
            used_b.add(ln["id"])
            pairs.append((p, ln))
            scores[(id(p), ln["id"])] = s
        ambiguous = []
        for p, ln in pairs:
            s = scores[(id(p), ln["id"])]
            rivals = [c for c in cands if c[0] >= s - 2 and ((c[1] is p) != (c[2] is ln))]
            if rivals:
                ambiguous.append({"bilag": p["transaction_id"], "bank_line": ln["id"],
                                  "amount": f(p["amount"]),
                                  "alternatives": sorted({c[1]["transaction_id"] if c[2] is ln
                                                          else c[2]["id"] for c in rivals}),
                                  "note": "Same amount and similar date; pairing could be "
                                          "swapped (does not change the difference)"})
        return pairs, ambiguous

    def _match_combinations(self, ledger, bank, window):
        """One line on one side == exact sum of 2-3 lines on the other side."""
        combos, possible = [], []
        used_l, used_b = set(), set()

        def search(singles, many, single_side):
            for one in singles:
                key = id(one) if single_side == "ledger" else one["id"]
                if key in (used_l if single_side == "ledger" else used_b):
                    continue
                pool = [m for m in many
                        if (m["id"] if single_side == "ledger" else id(m))
                        not in (used_b if single_side == "ledger" else used_l)
                        and (m["amount"] > 0) == (one["amount"] > 0)
                        and abs((m["date"] - one["date"]).days) <= window
                        and abs(m["amount"]) < abs(one["amount"])][:MAX_COMBO_POOL]
                found = [c for size in range(2, MAX_COMBO + 1)
                         for c in itertools.combinations(pool, size)
                         if sum((m["amount"] for m in c), ZERO) == one["amount"]]
                if not found:
                    continue
                if single_side == "ledger":
                    describe = lambda c: {"bilag": [one["transaction_id"]],  # noqa: E731
                                          "bank_lines": [m["id"] for m in c]}
                else:
                    describe = lambda c: {"bilag": [m["transaction_id"] for m in c],  # noqa: E731
                                          "bank_lines": [one["id"]]}
                if len(found) == 1:
                    c = found[0]
                    entry = {**describe(c), "amount": f(one["amount"]),
                             "type": ("one bilag, several bank lines" if single_side == "ledger"
                                      else "several bilag, one bank line"),
                             "_ledger": [one] if single_side == "ledger" else list(c),
                             "_bank": list(c) if single_side == "ledger" else [one]}
                    combos.append(entry)
                    if single_side == "ledger":
                        used_l.add(id(one))
                        used_b.update(m["id"] for m in c)
                    else:
                        used_b.add(one["id"])
                        used_l.update(id(m) for m in c)
                else:
                    possible.append({"amount": f(one["amount"]),
                                     "options": [describe(c) for c in found[:5]],
                                     "note": "Several combinations sum to this amount; "
                                             "left unmatched — confirm manually"})

        search(bank, ledger, "bank")
        search(ledger, bank, "ledger")
        return combos, possible

    @staticmethod
    def _bilag_out(p):
        v = p["voucher"]
        return {"bilag": p["transaction_id"], "journal": p["journal_id"],
                "date": p["date"].isoformat(), "amount": f(p["amount"]),
                "description": p["description"],
                "counter_lines": [{k: ln[k] for k in ("account_id", "debit", "credit",
                                                      "supplier_id", "customer_id",
                                                      "description")}
                                  for ln in v["lines"] if ln["record_id"] != p["record_id"]
                                  or ln["account_id"] != p["account_id"]],
                "reason": "Posted on the ledger account but not found on the bank statement "
                          "(in transit, wrong amount/date, or posted on the wrong account)"}

    @staticmethod
    def _bank_out(ln):
        return {"bank_line": ln["id"], "date": ln["date"].isoformat(),
                "amount": f(ln["amount"]), "text": ln["text"]}
