#!/usr/bin/env python3
"""Extract key fields from accounting documents (PDF invoices / receipts).

Fields: vendor_name, vendor_org_number, date, total_amount, vat_rate,
invoice_number, document_type (faktura | kvittering).

Every field is reported as
  {"value", "status": ok|unclear|missing, "confidence": high|medium|low|null,
   "evidence", "candidates", "reason"}
A field is never guessed: conflicting or weak evidence -> "unclear" with candidates.

Text extraction backends (first that yields text wins; all optional):
  pdfplumber -> pypdf -> pdftotext CLI -> OCR (pytesseract+pypdfium2, or tesseract+pdftoppm CLI)
Images (.png/.jpg/.tif) go straight to OCR. --text-file skips extraction entirely
(used for tests, or when Claude transcribed a scan visually).

Usage:
  python read_document.py <file.pdf> [more files...] [-o out.json] [--include-text]
  python read_document.py --text-file transcript.txt [--source-name orig.pdf]

Exit codes: 0 processed (check per-document "status"), 1 usage error.
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal, InvalidOperation

MIN_TEXT_CHARS = 20
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
NORWEGIAN_VAT_RATES = {Decimal(r) for r in ("0", "6", "8", "10", "11.11", "12", "15", "25")}


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def _enough(text):
    return text is not None and len(re.sub(r"\s", "", text)) >= MIN_TEXT_CHARS


def _try_pdfplumber(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        pages = [p.extract_text(layout=True) or "" for p in pdf.pages]
    return "\n\f".join(pages), len(pages)


def _try_pypdf(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = [p.extract_text() or "" for p in reader.pages]
    return "\n\f".join(pages), len(pages)


def _try_pdftotext(path):
    exe = shutil.which("pdftotext")
    if not exe:
        raise ImportError("pdftotext not on PATH")
    out = subprocess.run([exe, "-layout", "-enc", "UTF-8", path, "-"],
                         capture_output=True, timeout=120, check=True)
    text = out.stdout.decode("utf-8", errors="replace")
    return text, max(1, text.count("\f"))


def _ocr_lang(available):
    langs = [lang for lang in ("nor", "eng") if lang in available]
    return "+".join(langs) or None


def _try_ocr_python(path, max_pages):
    import pytesseract
    lang = _ocr_lang(pytesseract.get_languages(config=""))
    if os.path.splitext(path)[1].lower() in IMAGE_EXTS:
        from PIL import Image
        with Image.open(path) as img:
            return pytesseract.image_to_string(img, lang=lang), 1
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    n = min(len(pdf), max_pages)
    pages = [pytesseract.image_to_string(pdf[i].render(scale=300 / 72).to_pil(), lang=lang)
             for i in range(n)]
    return "\n\f".join(pages), n


def _try_ocr_cli(path, max_pages):
    tess = shutil.which("tesseract")
    if not tess:
        raise ImportError("tesseract not on PATH")
    listed = subprocess.run([tess, "--list-langs"], capture_output=True, text=True, timeout=30)
    lang = _ocr_lang(set(listed.stdout.split()))
    lang_args = ["-l", lang] if lang else []

    def ocr(img):
        out = subprocess.run([tess, img, "stdout", *lang_args],
                             capture_output=True, timeout=300, check=True)
        return out.stdout.decode("utf-8", errors="replace")

    if os.path.splitext(path)[1].lower() in IMAGE_EXTS:
        return ocr(path), 1
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise ImportError("pdftoppm not on PATH (needed to rasterise PDF for OCR)")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([pdftoppm, "-r", "300", "-png", "-l", str(max_pages), path,
                        os.path.join(tmp, "page")], check=True, timeout=300)
        images = sorted(f for f in os.listdir(tmp) if f.endswith(".png"))
        pages = [ocr(os.path.join(tmp, f)) for f in images]
    return "\n\f".join(pages), len(pages)


def extract_text(path, max_pages=10, allow_ocr=True):
    """Return (text, info). info["method"] is None when nothing produced text."""
    info = {"method": None, "pages": None, "ocr": False, "tried": []}
    is_image = os.path.splitext(path)[1].lower() in IMAGE_EXTS
    backends = [] if is_image else [("pdfplumber", _try_pdfplumber), ("pypdf", _try_pypdf),
                                    ("pdftotext", _try_pdftotext)]
    if allow_ocr:
        backends += [("ocr-pytesseract", lambda p: _try_ocr_python(p, max_pages)),
                     ("ocr-tesseract-cli", lambda p: _try_ocr_cli(p, max_pages))]
    for name, fn in backends:
        try:
            text, pages = fn(path)
        except ImportError as exc:
            info["tried"].append(f"{name}: unavailable ({exc})")
            continue
        except Exception as exc:  # corrupt/encrypted PDF, OCR failure, timeout
            info["tried"].append(f"{name}: failed ({type(exc).__name__}: {exc})")
            continue
        if _enough(text):
            info.update(method=name, pages=pages, ocr=name.startswith("ocr"))
            return text, info
        info["tried"].append(f"{name}: no usable text")
    return "", info


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def field(value=None, status="missing", confidence=None, evidence=None,
          candidates=None, reason=None):
    return {"value": value, "status": status, "confidence": confidence,
            "evidence": evidence, "candidates": candidates or [], "reason": reason}


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().casefold()


def _lines(text):
    return [ln.rstrip() for ln in text.replace("\f", "\n").splitlines()]


def _decide(found, what, high=True):
    """found: list of (value, evidence). One distinct value -> ok, else unclear."""
    distinct = []
    for value, ev in found:
        if value not in [d[0] for d in distinct]:
            distinct.append((value, ev))
    if not distinct:
        return None
    if len(distinct) == 1:
        value, ev = distinct[0]
        return field(value, "ok", "high" if high else "medium", ev)
    return field(None, "unclear", "low", None, [d[0] for d in distinct],
                 f"Conflicting {what} values found")


def _jsonable(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


# ---------------------------------------------------------------------------
# Amounts
# ---------------------------------------------------------------------------

AMOUNT_RE = re.compile(
    r"(?<![\d.,])(?:\d{1,3}(?:[  .]\d{3})+|\d+)(?:[,.]\d{1,2})?(?:,-)?(?![\d%])")


def parse_amount(raw):
    s = raw.replace(" ", "").replace(" ", "")
    if s.endswith(",-"):
        s = s[:-2]
    if "," in s and "." in s:
        dec_sep = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec_sep == "," else ",", "").replace(dec_sep, ".")
    elif "," in s:
        s = s.replace(",", ".") if re.fullmatch(r"\d+,\d{1,2}", s) else s.replace(",", "")
    elif "." in s and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _amounts_in(line):
    # Remove things that look like numbers but aren't amounts.
    cleaned = re.sub(r"\d+(?:[.,]\d+)?\s*%", " ", line)
    cleaned = re.sub(r"\b\d{1,4}[./-]\d{1,2}[./-]\d{2,4}\b", " ", cleaned)
    cleaned = re.sub(r"\b\d{3}[ .]?\d{3}[ .]?\d{3}\b(?=\s*MVA)", " ", cleaned)
    out = []
    for m in AMOUNT_RE.finditer(cleaned):
        val = parse_amount(m.group(0))
        if val is not None and val > 0:
            out.append(val)
    return out


TOTAL_TIERS = [
    re.compile(r"[åa]\s*betale|til\s*betaling|amount\s*due|balance\s*due|total\s*due|"
               r"sum\s*inkl|total\w*\s*inkl|totalbel[øo]p|totalsum|grand\s*total", re.I),
    re.compile(r"\btotal[t]?\b|\bbetalt\b|bankkort|kortbetaling|\bvisa\b|mastercard", re.I),
    re.compile(r"\bsum\b|\bbel[øo]p\b", re.I),
]
TOTAL_EXCLUDE = re.compile(
    r"\beks\w*|\bexcl|uten\s*mva|grunnlag|subtotal|netto|\bherav\b|av\s*dette|"
    r"^\s*(?:sum\s*)?(?:mva|moms|vat)\b|vat\s*amount|rabatt|discount|vekslepenger|tips|driks",
    re.I)
CURRENCY_RE = re.compile(r"\b(NOK|EUR|USD|SEK|DKK|GBP)\b|\bkr\.?(?=\s*\d)", re.I)


def extract_total(lines, text):
    for tier, pattern in enumerate(TOTAL_TIERS):
        found = []
        for i, line in enumerate(lines):
            if not pattern.search(line) or TOTAL_EXCLUDE.search(line):
                continue
            amounts = _amounts_in(line)
            if not amounts and i + 1 < len(lines):  # label above value
                amounts = _amounts_in(lines[i + 1])
            if amounts:
                found.append((amounts[-1], line.strip()))
        result = _decide(found, "total amount", high=(tier == 0))
        if result:
            if tier == 2 and result["status"] == "ok":
                result.update(confidence="low", status="unclear",
                              reason="Only a generic 'sum'/'beløp' label found",
                              candidates=[result["value"]], value=None)
            break
    else:
        result = field(reason="No total-amount label (Å betale / Totalt / Total) found")

    currencies = {("NOK" if m.group(0).lower().startswith("kr") else m.group(1).upper())
                  for m in CURRENCY_RE.finditer(text)}
    result["currency"] = next(iter(currencies)) if len(currencies) == 1 else None
    if len(currencies) > 1:
        result["currency_candidates"] = sorted(currencies)
    return result


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mai": 5, "may": 5, "jun": 6, "jul": 7,
          "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "des": 12, "dec": 12}
DATE_RE = re.compile(
    r"\b(?P<y1>\d{4})-(?P<m1>\d{1,2})-(?P<d1>\d{1,2})\b"
    r"|\b(?P<d2>\d{1,2})(?P<sep>[./-])(?P<m2>\d{1,2})(?P=sep)(?P<y2>\d{4}|\d{2})\b"
    r"|\b(?P<d3>\d{1,2})\.?\s+(?P<mon>jan|feb|mar|apr|mai|may|jun|jul|aug|sep|okt|oct|nov|des|dec)"
    r"[a-zæøå]*\.?\s+(?P<y3>\d{4})\b", re.I)
DATE_STRONG = re.compile(r"fakturadato|faktura\s*dato|invoice\s*date|kj[øo]psdato|"
                         r"kvitteringsdato|transaksjonsdato|utstedt", re.I)
DATE_WEAK = re.compile(r"\bdato\b|\bdate\b|\btid\b", re.I)
DATE_EXCLUDE = re.compile(r"forfall|due|betalingsfrist|levering|deliver|periode|period|"
                          r"ordre|order|gyldig|valid|f[øo]dt|utl[øo]p|expir", re.I)


def _parse_date(m):
    try:
        if m.group("y1"):
            y, mo, d = int(m.group("y1")), int(m.group("m1")), int(m.group("d1"))
        elif m.group("y2"):
            y, mo, d = int(m.group("y2")), int(m.group("m2")), int(m.group("d2"))
            y += 2000 if y < 100 else 0
        else:
            y, mo, d = int(m.group("y3")), MONTHS[m.group("mon")[:3].lower()], int(m.group("d3"))
        date = dt.date(y, mo, d)
    except (ValueError, KeyError):
        return None, False
    if not (2000 <= date.year <= dt.date.today().year + 1):
        return None, False
    # dd/mm vs mm/dd is ambiguous only with '/' and both parts <= 12.
    ambiguous = bool(m.group("sep") == "/" and int(m.group("d2")) <= 12 and int(m.group("m2")) <= 12)
    return date.isoformat(), ambiguous


def _label_kind(segment):
    if DATE_EXCLUDE.search(segment):
        return "exclude"
    if DATE_STRONG.search(segment):
        return "strong"
    if DATE_WEAK.search(segment):
        return "weak"
    return None


def _header_labels(line):
    """Ordered label kinds in a header row like 'Fakturadato   Forfallsdato'."""
    labels = []
    for seg in re.split(r"\s{2,}|\t|\|", line):
        kind = _label_kind(seg)
        if kind:
            labels.append(kind)
    return labels


def extract_date(lines):
    buckets = {"strong": [], "weak": [], "none": []}
    any_ambiguous = False
    for i, line in enumerate(lines):
        matches = list(DATE_RE.finditer(line))
        prev_end = 0
        header = _header_labels(lines[i - 1]) if i > 0 else []
        for k, m in enumerate(matches):
            iso, ambiguous = _parse_date(m)
            segment = line[prev_end:m.start()]
            prev_end = m.end()
            if not iso:
                continue
            kind = _label_kind(segment)
            if kind is None and header and not DATE_RE.search(lines[i - 1]):
                kind = header[k] if k < len(header) else None
            if kind == "exclude":
                continue
            buckets[kind or "none"].append((iso, line.strip()))
            any_ambiguous |= ambiguous

    for kind in ("strong", "weak"):
        result = _decide(buckets[kind], "date", high=(kind == "strong"))
        if result:
            break
    else:
        result = _decide(buckets["none"], "date", high=False)
        if result and result["status"] == "ok":
            result["reason"] = "Only one date in document, but it has no label"
        elif result:
            result["reason"] = "Several unlabelled dates; cannot tell which is the document date"
    if not result:
        return field(reason="No document date found")
    if any_ambiguous and result["status"] == "ok":
        result["confidence"] = "medium"
        result["reason"] = "Date uses '/' with day and month both <= 12; read as DD/MM"
    return result


# ---------------------------------------------------------------------------
# Invoice / receipt number
# ---------------------------------------------------------------------------

NUMBER_LABEL = re.compile(
    r"(?:faktura\s*(?:nr|nummer|no)\.?|fakturanr\.?|fakturanummer|"
    r"invoice\s*(?:no|number|nr|#)\.?|kreditnota\s*(?:nr|nummer)\.?|"
    r"kvittering\s*(?:nr|nummer)\.?|kvitteringsnr\.?|bong\s*nr\.?|bongnr\.?|"
    r"receipt\s*(?:no|number|#)\.?)\s*[:#.]?\s*", re.I)
NUMBER_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/]*\d[A-Za-z0-9\-/]*")
BARE_FAKTURA = re.compile(r"^\s*(?:faktura|invoice)\s*#?\s*(\d{3,})\s*$", re.I)


def extract_invoice_number(lines):
    found = []
    for i, line in enumerate(lines):
        for m in NUMBER_LABEL.finditer(line):
            rest = line[m.end():]
            tok = NUMBER_TOKEN.match(rest)
            if not tok and not rest.strip() and i + 1 < len(lines):  # value on next line
                tok = NUMBER_TOKEN.match(lines[i + 1].strip())
            if tok and not DATE_RE.fullmatch(tok.group(0)):
                found.append((tok.group(0), line.strip()))
        bare = BARE_FAKTURA.match(line)
        if bare:
            found.append((bare.group(1), line.strip()))
    return _decide(found, "invoice number") or field(
        reason="No invoice/receipt number label found")


# ---------------------------------------------------------------------------
# VAT rate
# ---------------------------------------------------------------------------

VAT_LINE = re.compile(r"\bmva\b|\bmoms\b|\bvat\b|merverdiavgift|\bmva-", re.I)
PERCENT_RE = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%")
VAT_EXEMPT = re.compile(r"fritatt\s*(?:for\s*)?mva|ikke\s*mva-?pliktig|unntatt\s*mva|"
                        r"avgiftsfri|vat\s*exempt|ingen\s*mva", re.I)


def extract_vat_rate(lines):
    rates, evidence = [], {}
    for line in lines:
        if not VAT_LINE.search(line):
            continue
        for m in PERCENT_RE.finditer(line):
            rate = Decimal(m.group(1).replace(",", ".")).normalize()
            rate = rate.quantize(Decimal(1)) if rate == rate.to_integral_value() else rate
            if rate not in rates:
                rates.append(rate)
                evidence[rate] = line.strip()
    if not rates:
        for line in lines:
            if VAT_EXEMPT.search(line):
                return field(0, "ok", "medium", line.strip(),
                             reason="Document states it is exempt from VAT")
        return field(reason="No VAT percentage found next to MVA/VAT label")
    unusual = [r for r in rates if r not in NORWEGIAN_VAT_RATES]
    if len(rates) == 1:
        rate = rates[0]
        if unusual:
            return field(None, "unclear", "low", evidence[rate], [_jsonable(rate)],
                         f"{rate}% is not a Norwegian VAT rate (OCR error?)")
        return field(_jsonable(rate), "ok", "high", evidence[rate])
    reason = "Multiple VAT rates on document (mixed-rate lines need splitting)"
    if unusual:
        reason += f"; non-standard rate(s): {', '.join(str(r) for r in unusual)}"
    return field(None, "unclear", "low", None, [_jsonable(r) for r in sorted(rates)], reason)


# ---------------------------------------------------------------------------
# Document type
# ---------------------------------------------------------------------------

TYPE_KEYWORDS = {
    "faktura": [r"\bfaktura\b", r"fakturanr|fakturanummer|faktura\s*nr", r"fakturadato",
                r"forfall", r"\bkid\b", r"\binvoice\b", r"betales\s*til|betalingsinformasjon",
                r"kontonr|kontonummer|bankkonto"],
    "kvittering": [r"kvittering|\breceipt\b", r"bankkort|kortbetaling|kort\s*betaling",
                   r"kontant", r"\bbetalt\b|\bpaid\b", r"terminal|\bbax\b|\btid\b",
                   r"\bvisa\b|mastercard|vipps", r"kasse|bong", r"vekslepenger|ref\.?\s*nr"],
}
CREDIT_NOTE = re.compile(r"kreditnota|credit\s*note", re.I)


def extract_document_type(lines, text):
    if CREDIT_NOTE.search(text):
        return field(None, "unclear", "low",
                     next(ln.strip() for ln in lines if CREDIT_NOTE.search(ln)),
                     ["faktura", "kvittering"],
                     "Document is a credit note (kreditnota); confirm how to classify it")
    scores = {}
    for doc_type, patterns in TYPE_KEYWORDS.items():
        scores[doc_type] = sum(1 for p in patterns if re.search(p, text, re.I))
    head = [ln.strip().lower() for ln in lines[:12] if ln.strip()]
    titles = {t for t in ("faktura", "kvittering", "invoice", "receipt") if t in head}
    for t in titles:
        scores["faktura" if t in ("faktura", "invoice") else "kvittering"] += 3
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (best, best_score), (_, second) = ranked
    detail = f"keyword scores: faktura={scores['faktura']}, kvittering={scores['kvittering']}"
    if best_score == 0:
        return field(reason="No invoice or receipt keywords found")
    if best_score >= 2 and best_score - second >= 2:
        conf = "high" if titles and best_score - second >= 3 else "medium"
        return field(best, "ok", conf, detail)
    return field(None, "unclear", "low", detail, [k for k, _ in ranked],
                 "Invoice and receipt indicators are too close to call")


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------

ORG_LINE = re.compile(r"org|foretaks|\bmva\b|\bNO\s*\d{3}", re.I)
ORG_RE = re.compile(r"(?<!\d)(\d{3})[ .]?(\d{3})[ .]?(\d{3})(?!\d)")
BUYER_CONTEXT = re.compile(r"kunde|customer|kj[øo]per|buyer|faktura\s*til|fakturamottaker|"
                           r"bill\s*to|mottaker|leveringsadresse|deres\s*ref|your\s*ref", re.I)
COMPANY_SUFFIX = re.compile(
    r"\b(?:AS|ASA|ANS|DA|ENK|NUF|SA|BA|KS|AB|ApS|A/S|Ltd|Limited|GmbH|Inc|LLC|Oy)\b\.?")
NOT_A_NAME = re.compile(r"^\s*(?:faktura|kvittering|invoice|receipt|side|page)\b", re.I)


def valid_org_number(digits):
    """Norwegian organisasjonsnummer modulus-11 check."""
    if len(digits) != 9 or digits[0] not in "89":
        return False
    weights = [3, 2, 7, 6, 5, 4, 3, 2]
    rest = sum(int(d) * w for d, w in zip(digits, weights)) % 11
    check = 0 if rest == 0 else 11 - rest
    return check != 10 and check == int(digits[8])


def _buyer_lines(lines):
    """Indices of lines inside a buyer/customer address block."""
    out = set()
    for i, line in enumerate(lines):
        if BUYER_CONTEXT.search(line):
            out.update(range(i, min(i + 5, len(lines))))
    return out


def extract_vendor(lines):
    buyer = _buyer_lines(lines)

    org_found, org_rows = [], []
    for i, line in enumerate(lines):
        if not ORG_LINE.search(line) or BUYER_CONTEXT.search(line):
            continue
        for m in ORG_RE.finditer(line):
            digits = "".join(m.groups())
            if valid_org_number(digits):
                org_found.append((digits, line.strip()))
                if i not in buyer:
                    org_rows.append(i)
    org_field = _decide(org_found, "organisation number") or field(
        reason="No valid Norwegian organisation number found")
    if org_field["status"] == "ok" and org_found and not org_rows:
        org_field.update(status="unclear", confidence="low", candidates=[org_field["value"]],
                         value=None, reason="Only org number found sits in the buyer block")

    candidates = {}
    for i, line in enumerate(lines):
        if i in buyer:
            continue
        for seg in re.split(r"\s{2,}|\t|\|", line):
            seg = seg.strip(" ,;:")
            if not COMPANY_SUFFIX.search(seg) or BUYER_CONTEXT.search(seg) or len(seg) > 80:
                continue
            seg = re.sub(r"\s*(?:org\.?\s*nr|foretaks).*$", "", seg, flags=re.I).strip(" ,;:")
            if not seg or NOT_A_NAME.match(seg) or not re.search(r"[A-Za-zÆØÅæøå]{2}", seg):
                continue
            key = _norm(seg)
            c = candidates.setdefault(key, {"name": seg, "score": 0, "evidence": line.strip(),
                                            "near_org": False})
            c["score"] += 1
            if i < 8:
                c["score"] += 2
            if any(abs(i - r) <= 3 for r in org_rows):
                c["score"] += 3
                c["near_org"] = True

    if not candidates:
        first = next((ln.strip() for ln in lines if ln.strip() and not NOT_A_NAME.match(ln)), None)
        name = field(None, "unclear" if first else "missing", "low" if first else None, None,
                     [first] if first else [],
                     "No company name with legal suffix (AS, ASA, ENK...) found"
                     + ("; first line of document offered as candidate" if first else ""))
        return name, org_field

    ranked = sorted(candidates.values(), key=lambda c: -c["score"])
    top = ranked[0]
    if len(ranked) > 1 and ranked[1]["score"] == top["score"]:
        name = field(None, "unclear", "low", None, [c["name"] for c in ranked[:4]],
                     "Several company names score equally (vendor vs. buyer?)")
    else:
        conf = "high" if top["near_org"] else "medium"
        name = field(top["name"], "ok", conf, top["evidence"],
                     [c["name"] for c in ranked[1:4]] or None)
    return name, org_field


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

REQUIRED = ["vendor_name", "date", "total_amount", "vat_rate", "invoice_number", "document_type"]


def extract_fields(text, ocr=False):
    lines = _lines(text)
    vendor_name, vendor_org = extract_vendor(lines)
    fields = {
        "document_type": extract_document_type(lines, text),
        "vendor_name": vendor_name,
        "vendor_org_number": vendor_org,
        "date": extract_date(lines),
        "invoice_number": extract_invoice_number(lines),
        "total_amount": extract_total(lines, text),
        "vat_rate": extract_vat_rate(lines),
    }
    for f in fields.values():
        f["value"] = _jsonable(f["value"])
        f["candidates"] = [_jsonable(c) for c in f["candidates"]]
        if ocr and f["confidence"] == "high":
            f["confidence"] = "medium"

    flags = []
    for name in REQUIRED:
        f = fields[name]
        if f["status"] != "ok":
            flags.append(f"{name}: {f['status']}" + (f" - {f['reason']}" if f["reason"] else ""))
    if fields["document_type"]["value"] == "kvittering" and fields["invoice_number"]["status"] == "missing":
        flags = [fl for fl in flags if not fl.startswith("invoice_number")]
        fields["invoice_number"]["reason"] = "Receipts often have no number; not flagged"
    cur = fields["total_amount"].get("currency")
    if cur and cur != "NOK":
        flags.append(f"total_amount: currency is {cur}, not NOK")
    return fields, flags


def process(path, text=None, max_pages=10, allow_ocr=True, include_text=False, source_name=None):
    doc = {"file": source_name or path}
    if text is None:
        if not os.path.isfile(path):
            doc.update(status="error", error="File not found")
            return doc
        text, info = extract_text(path, max_pages, allow_ocr)
    else:
        info = {"method": "text-file", "pages": None, "ocr": False, "tried": []}
    doc["extraction"] = info
    if not info["method"]:
        doc.update(status="needs_ocr", needs_review=True, fields=None,
                   flags=["No text layer and no OCR backend produced text. "
                          "Read the document visually and re-run with --text-file."])
        return doc
    fields, flags = extract_fields(text, info["ocr"])
    doc.update(status="ok", needs_review=bool(flags), flags=flags, fields=fields)
    if include_text:
        doc["text"] = text
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract fields from invoices/receipts.")
    ap.add_argument("files", nargs="*", help="PDF or image files")
    ap.add_argument("--text-file", help="Use this UTF-8 text instead of extracting from a file")
    ap.add_argument("--source-name", help="Original document name to report with --text-file")
    ap.add_argument("-o", "--output", help="Write JSON here instead of stdout")
    ap.add_argument("--no-ocr", action="store_true", help="Never run OCR")
    ap.add_argument("--max-pages", type=int, default=10, help="OCR page limit (default 10)")
    ap.add_argument("--include-text", action="store_true", help="Include extracted text in output")
    args = ap.parse_args(argv)
    if not args.files and not args.text_file:
        ap.error("give at least one file or --text-file")

    docs = []
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as fh:
            docs.append(process(args.text_file, fh.read(), include_text=args.include_text,
                                source_name=args.source_name))
    for path in args.files:
        docs.append(process(path, max_pages=args.max_pages, allow_ocr=not args.no_ocr,
                            include_text=args.include_text))

    out = json.dumps({"documents": docs}, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
