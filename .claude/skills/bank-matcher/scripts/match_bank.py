#!/usr/bin/env python3
"""Match accounting documents to bank statement lines by amount, date and vendor.

Documents: document-reader JSON ({"documents": [...]}) and/or entry-builder JSON ({"bilag": [...]}).
Bank:      CSV export from a Norwegian netbank (columns auto-detected, overridable)
           or ISO 20022 CAMT.053 XML.

Per document status:
  paid         one outgoing bank line with the exact amount, in the date window, and the
               vendor (or invoice number / org number) recognised in the bank text
  uncertain    a candidate exists but something is weak or ambiguous (see reasons)
  not_found    no outgoing bank line with that amount in the date window
  unmatchable  the document has no confirmed amount

A bank line is assigned to at most one document.

Usage:
  python match_bank.py --documents doc.json [--documents bilag.json] --bank statement.csv [-o out.json]
  CSV column overrides: --date-col, --text-col (repeatable), --amount-col, --out-col, --in-col

Exit codes: 0 processed, 1 input error.
"""

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation

try:
    from defusedxml.ElementTree import parse as xml_parse
except ImportError:  # pragma: no cover
    from xml.etree.ElementTree import parse as xml_parse

CENT = Decimal("0.01")
STOPWORDS = {"as", "asa", "ans", "da", "enk", "nuf", "sa", "ltd", "ab", "norge", "norway",
             "avd", "avdeling", "og", "the", "and", "til", "fra", "betaling", "varekjop",
             "varekjøp", "visa", "kortkjop", "kortkjøp", "nettgiro", "giro", "efaktura",
             "overforing", "overføring", "kid", "ref", "dato", "nok", "kr"}


class InputError(Exception):
    pass


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_amount(raw):
    """Signed amount from Norwegian/English formats; None if not a number."""
    if raw is None:
        return None
    s = str(raw).strip().replace(" ", "").replace(" ", "").replace("kr", "")
    if not s:
        return None
    neg = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("-+()")
    if "," in s and "." in s:
        dec_sep = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec_sep == "," else ",", "").replace(dec_sep, ".")
    elif "," in s:
        s = s.replace(",", ".") if re.fullmatch(r"\d+,\d{1,2}", s) else s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        val = Decimal(s).quantize(CENT)
    except InvalidOperation:
        return None
    return -val if neg else val


def parse_date(raw):
    if not raw:
        return None
    s = str(raw).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d-%m-%Y", "%Y.%m.%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def tokens(s):
    words = re.findall(r"[0-9a-zæøå]+", (s or "").casefold())
    return {w for w in words if w not in STOPWORDS}


def compact(s):
    return re.sub(r"[^0-9a-zæøå]", "", (s or "").casefold())


# ---------------------------------------------------------------------------
# Bank statements
# ---------------------------------------------------------------------------

DATE_HEADERS = ["dato", "bokført dato", "bokføringsdato", "bokfort dato", "transaksjonsdato",
                "utført dato", "date", "booking date", "posting date", "transaction date",
                "rentedato", "valuteringsdato", "value date"]
TEXT_HEADERS = ["forklaring", "beskrivelse", "tekst", "transaksjonstekst", "mottaker",
                "mottakernavn", "betalingsmottaker", "motpart", "melding", "kid",
                "referanse", "description", "text", "payee", "counterparty", "message",
                "reference", "til konto navn", "navn"]
AMOUNT_HEADERS = ["beløp", "belop", "beløp nok", "amount", "sum"]
OUT_HEADERS = ["ut", "uttak", "ut fra konto", "utgående", "belastet", "belastning", "debit",
               "beløp ut", "ut av konto"]
IN_HEADERS = ["inn", "innskudd", "inn på konto", "inngående", "godskrevet", "credit",
              "beløp inn"]


def _read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _pick(headers, wanted, override=None):
    norm = [h.strip().casefold() for h in headers]
    if override:
        if override.casefold() not in norm:
            raise InputError(f"Column {override!r} not in CSV header {headers}")
        return norm.index(override.casefold())
    for w in wanted:
        if w in norm:
            return norm.index(w)
    return None


def read_csv(path, date_col=None, text_cols=None, amount_col=None, out_col=None, in_col=None):
    text = _read_text(path)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        class dialect(csv.excel):
            delimiter = ";" if sample.count(";") > sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), dialect))

    header_idx = next((i for i, r in enumerate(rows[:15])
                       if _pick(r, DATE_HEADERS, None) is not None), None)
    if header_idx is None:
        raise InputError("No header row with a date column found in bank CSV "
                         "(use --date-col and friends)")
    headers = rows[header_idx]
    di = _pick(headers, DATE_HEADERS, date_col)
    if text_cols:
        ti = [_pick(headers, [], c) for c in text_cols]
    else:
        norm = [h.strip().casefold() for h in headers]
        ti = [i for i, h in enumerate(norm) if h in TEXT_HEADERS]
    ai = _pick(headers, AMOUNT_HEADERS, amount_col)
    oi = _pick(headers, OUT_HEADERS, out_col)
    ii = _pick(headers, IN_HEADERS, in_col)
    if di is None or (ai is None and oi is None):
        raise InputError(f"Cannot identify date/amount columns in {headers}")

    warnings, lines = [], []
    for n, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not any(c.strip() for c in row):
            continue
        cell = lambda i: row[i] if i is not None and i < len(row) else ""  # noqa: E731
        date = parse_date(cell(di))
        if oi is not None or ii is not None:
            out_amt, in_amt = parse_amount(cell(oi)), parse_amount(cell(ii))
            amount = (-abs(out_amt) if out_amt else None) or (abs(in_amt) if in_amt else None)
        else:
            amount = parse_amount(cell(ai))
        if date is None or amount is None:
            warnings.append(f"Row {n} skipped (no date or amount)")
            continue
        lines.append({"id": f"row{n}", "date": date, "amount": amount,
                      "text": " | ".join(cell(i).strip() for i in ti if cell(i).strip())})
    if lines and ai is not None and oi is None and all(ln["amount"] > 0 for ln in lines):
        warnings.append("All amounts are positive in a single amount column; outgoing "
                        "payments cannot be told apart (use --out-col/--in-col)")
    return lines, warnings


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _find_all(el, name):
    return [e for e in el.iter() if _local(e.tag) == name]


def _first_text(el, *path):
    """First text found following a path of local names, at any depth for the first step."""
    for start in _find_all(el, path[0]):
        cur = [start]
        for step in path[1:]:
            cur = [c for e in cur for c in e if _local(c.tag) == step]
        for c in cur:
            if c.text and c.text.strip():
                return c.text.strip()
    return None


def read_camt(path):
    root = xml_parse(path).getroot()
    if "camt.053" not in root.tag and "camt.054" not in root.tag:
        raise InputError(f"Not a CAMT.053/054 document (root {root.tag})")
    lines, warnings = [], []
    for n, entry in enumerate(_find_all(root, "Ntry"), 1):
        amt = next((e for e in entry if _local(e.tag) == "Amt"), None)
        ind = next((e.text for e in entry if _local(e.tag) == "CdtDbtInd"), None)
        amount = parse_amount(amt.text if amt is not None else None)
        date = parse_date(_first_text(entry, "BookgDt", "Dt") or _first_text(entry, "BookgDt", "DtTm")
                          or _first_text(entry, "ValDt", "Dt"))
        if amount is None or date is None or ind not in ("DBIT", "CRDT"):
            warnings.append(f"Entry {n} skipped (missing amount, date or CdtDbtInd)")
            continue
        if amt is not None and amt.get("Ccy") not in (None, "NOK"):
            warnings.append(f"Entry {n} is in {amt.get('Ccy')}")
        texts = []
        for name in ("Nm", "Ustrd", "Ref", "AddtlNtryInf", "AddtlTxInf", "EndToEndId"):
            for e in _find_all(entry, name):
                if e.text and e.text.strip() and e.text.strip() not in texts \
                        and e.text.strip() != "NOTPROVIDED":
                    texts.append(e.text.strip())
        lines.append({"id": f"ntry{n}", "date": date,
                      "amount": -amount if ind == "DBIT" else amount,
                      "text": " | ".join(texts)})
    return lines, warnings


def read_bank(path, **cols):
    if not os.path.isfile(path):
        raise InputError(f"Bank file not found: {path}")
    if path.lower().endswith(".xml"):
        return read_camt(path)
    return read_csv(path, **cols)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def _ok(fields, key):
    f = (fields or {}).get(key) or {}
    return f.get("value") if f.get("status") == "ok" else None


def load_documents(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read {path}: {exc}")
    docs = []
    if "documents" in data:  # document-reader
        for d in data["documents"]:
            f = d.get("fields") or {}
            docs.append({"id": d.get("file"), "vendor": _ok(f, "vendor_name"),
                         "org": _ok(f, "vendor_org_number"), "date": _ok(f, "date"),
                         "amount": _ok(f, "total_amount"),
                         "invoice_number": _ok(f, "invoice_number"),
                         "document_type": _ok(f, "document_type"),
                         "currency": (f.get("total_amount") or {}).get("currency")})
    elif "bilag" in data:  # entry-builder
        for b in data["bilag"]:
            h = b.get("header") or {}
            docs.append({"id": b.get("source_file"), "vendor": h.get("vendor_name"), "org": None,
                         "date": h.get("date"), "amount": h.get("total_amount"),
                         "invoice_number": h.get("invoice_number"),
                         "document_type": h.get("document_type"), "currency": h.get("currency")})
    else:
        raise InputError(f"{path}: expected document-reader or entry-builder JSON")
    for d in docs:
        d["amount"] = parse_amount(d["amount"]) if d["amount"] is not None else None
        d["date"] = parse_date(d["date"])
    return docs


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def vendor_signal(doc, text):
    """-> 'reference' | 'strong' | 'weak' | 'none'"""
    bank_compact, bank_digits = compact(text), re.sub(r"\D", "", text or "")
    inv = compact(doc.get("invoice_number"))
    if inv and len(inv) >= 4 and inv in bank_compact:
        return "reference"
    if doc.get("org") and doc["org"] in bank_digits:
        return "reference"
    vt = tokens(doc.get("vendor"))
    if not vt:
        return "none"
    common = {t for t in vt & tokens(text) if len(t) >= 3}
    vc = compact(" ".join(sorted(vt, key=(doc.get("vendor") or "").casefold().find)))
    if (len(vc) >= 4 and vc in bank_compact) or (common and len(vt & tokens(text)) / len(vt) >= 0.6):
        return "strong"
    return "weak" if common else "none"


def window_for(doc, cfg):
    if doc.get("document_type") == "kvittering":
        return -cfg["early_days"], cfg["receipt_days"]
    return -cfg["early_days"], cfg["invoice_days"]


def score_pair(doc, line, cfg):
    """Return candidate dict or None. Amount must match exactly (within tolerance)."""
    if line["amount"] >= 0:
        return None  # only outgoing payments
    if abs(abs(line["amount"]) - doc["amount"]) > cfg["tolerance"]:
        return None
    lo, hi = window_for(doc, cfg)
    days = (line["date"] - doc["date"]).days if doc["date"] else None
    if days is not None and not (lo <= days <= hi):
        return None
    signal = vendor_signal(doc, line["text"])
    score = 50 + {"reference": 40, "strong": 30, "weak": 10, "none": 0}[signal]
    if days is not None:
        score += 20 * (1 - days / hi) if days >= 0 else -5
    return {"bank_line": line["id"], "date": line["date"].isoformat(),
            "amount": float(line["amount"]), "text": line["text"],
            "days_after_document": days, "vendor_signal": signal, "score": round(score, 1)}


def match(docs, lines, cfg):
    results = []
    for d in docs:
        r = {"id": d["id"], "vendor": d["vendor"],
             "date": d["date"].isoformat() if d["date"] else None,
             "amount": float(d["amount"]) if d["amount"] is not None else None,
             "status": None, "confidence": None, "match": None, "candidates": [], "reasons": []}
        if d["amount"] is None or d["amount"] <= 0:
            r["status"] = "unmatchable"
            r["reasons"].append("Document has no confirmed positive total amount")
        else:
            cands = [c for c in (score_pair(d, ln, cfg) for ln in lines) if c]
            r["candidates"] = sorted(cands, key=lambda c: -c["score"])
        results.append(r)

    # Global greedy one-to-one assignment, best score first.
    pairs = sorted(((c["score"], i, c) for i, r in enumerate(results) for c in r["candidates"]),
                   key=lambda p: -p[0])
    taken, assigned = {}, {}
    for score, i, c in pairs:
        if i in assigned or c["bank_line"] in taken:
            continue
        assigned[i], taken[c["bank_line"]] = c, i

    for i, (r, d) in enumerate(zip(results, docs)):
        if r["status"]:
            continue
        reasons = r["reasons"]
        if d.get("currency") and d["currency"] != "NOK":
            reasons.append(f"Document currency is {d['currency']}; bank amount in NOK may differ")
        if not r["candidates"]:
            r["status"] = "not_found"
            lo, hi = window_for(d, cfg)
            reasons.append(f"No outgoing bank line of {d['amount']} between {lo} and {hi} "
                           "days from document date" if d["date"] else
                           f"No outgoing bank line of {d['amount']}")
            continue
        c = assigned.get(i)
        if c is None:
            owner = taken[r["candidates"][0]["bank_line"]]
            r["status"], r["confidence"] = "uncertain", "low"
            reasons.append(f"Only candidate bank line(s) already matched to {results[owner]['id']}")
            continue
        r["match"] = c
        uncertain = []
        rivals = [o for o in r["candidates"] if o is not c and o["score"] >= c["score"] - 10]
        if rivals:
            uncertain.append("Several bank lines fit almost equally: "
                             + ", ".join(o["bank_line"] for o in rivals))
        contenders = [results[j]["id"] for j, o in enumerate(results) if j != i
                      for oc in o["candidates"]
                      if oc["bank_line"] == c["bank_line"] and oc["score"] >= c["score"] - 5]
        if contenders:
            uncertain.append(f"Bank line {c['bank_line']} fits other document(s) equally: "
                             + ", ".join(dict.fromkeys(contenders)))
        if c["vendor_signal"] == "none":
            uncertain.append("Amount and date match, but vendor not recognised in bank text")
        elif c["vendor_signal"] == "weak":
            uncertain.append("Vendor only partially recognised in bank text")
        if d["date"] is None:
            uncertain.append("Document has no date; matched on amount and vendor only")
        elif c["days_after_document"] < 0:
            uncertain.append(f"Paid {-c['days_after_document']} day(s) before document date")
        reasons.extend(uncertain)
        if uncertain:
            r["status"], r["confidence"] = "uncertain", "low"
        else:
            r["status"] = "paid"
            r["confidence"] = "high" if (c["vendor_signal"] == "reference"
                                         or c["days_after_document"] <= 7) else "medium"
        r["candidates"] = [o for o in r["candidates"] if o is not c]
    return results, taken


def run(doc_paths, bank_path, cfg, **cols):
    docs = [d for p in doc_paths for d in load_documents(p)]
    lines, warnings = read_bank(bank_path, **cols)
    results, taken = match(docs, lines, cfg)
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    unmatched = [{"bank_line": ln["id"], "date": ln["date"].isoformat(),
                  "amount": float(ln["amount"]), "text": ln["text"]}
                 for ln in lines if ln["amount"] < 0 and ln["id"] not in taken]
    return {
        "meta": {"bank_file": bank_path, "bank_lines": len(lines),
                 "outgoing_bank_lines": sum(1 for ln in lines if ln["amount"] < 0),
                 "documents": len(docs), "status_counts": counts, "settings": cfg,
                 "warnings": warnings},
        "documents": results,
        "unmatched_outgoing_bank_lines": unmatched,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Match documents to bank statement lines.")
    ap.add_argument("--documents", action="append", required=True,
                    help="document-reader or entry-builder JSON (repeatable)")
    ap.add_argument("--bank", required=True, help="Bank statement CSV or CAMT.053 XML")
    ap.add_argument("-o", "--output")
    ap.add_argument("--receipt-days", type=int, default=7,
                    help="Max days from receipt date to bank date (default 7)")
    ap.add_argument("--invoice-days", type=int, default=60,
                    help="Max days from invoice date to payment (default 60)")
    ap.add_argument("--early-days", type=int, default=3,
                    help="Allow payment this many days before the document date (default 3)")
    ap.add_argument("--tolerance", default="0", help="Amount tolerance in NOK (default 0)")
    ap.add_argument("--date-col")
    ap.add_argument("--text-col", action="append")
    ap.add_argument("--amount-col")
    ap.add_argument("--out-col")
    ap.add_argument("--in-col")
    args = ap.parse_args(argv)

    cfg = {"receipt_days": args.receipt_days, "invoice_days": args.invoice_days,
           "early_days": args.early_days}
    try:
        tol = parse_amount(args.tolerance)
        if tol is None or tol < 0:
            raise InputError("--tolerance must be a non-negative amount")
        cfg["tolerance"] = tol
        result = run(args.documents, args.bank, cfg, date_col=args.date_col,
                     text_cols=args.text_col, amount_col=args.amount_col,
                     out_col=args.out_col, in_col=args.in_col)
    except (InputError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception as exc:  # malformed XML etc.
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False),
              file=sys.stderr)
        return 1

    result["meta"]["settings"]["tolerance"] = float(cfg["tolerance"])
    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
