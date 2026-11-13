"""Document extraction layer for document-mcp (no MCP dependency, unit-testable).

Extraction is delegated to the document-reader skill
(.claude/skills/document-reader/scripts/read_document.py) so the field rules live in one
place. Results are cached per file (path + size + mtime) so OCR is not repeated.

Optional sandbox: DOCUMENT_ROOTS (os.pathsep-separated directories) restricts which
files may be read.
"""

import glob
import importlib.util
import os
import shutil
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
READER_DIR = os.path.join(PROJECT_ROOT, ".claude", "skills", "document-reader", "scripts")
sys.path.insert(0, READER_DIR)

from read_document import IMAGE_EXTS, process  # noqa: E402

ALLOWED_EXTS = {".pdf"} | IMAGE_EXTS
MAX_BATCH = 100
SUMMARY_KEYS = {"supplier": "vendor_name", "org_number": "vendor_org_number", "date": "date",
                "amount": "total_amount", "vat_rate": "vat_rate", "type": "document_type",
                "invoice_number": "invoice_number"}


class DocError(Exception):
    """User-facing error (bad path, disallowed file, bad argument)."""


def summarize(doc):
    """Compact view: only confirmed (status ok) values; everything else is null."""
    fields = doc.get("fields") or {}
    out = {}
    for key, name in SUMMARY_KEYS.items():
        f = fields.get(name) or {}
        out[key] = f.get("value") if f.get("status") == "ok" else None
    out["currency"] = (fields.get("total_amount") or {}).get("currency")
    out["unclear_fields"] = [k for k, name in SUMMARY_KEYS.items()
                             if (fields.get(name) or {}).get("status") == "unclear"]
    out["missing_fields"] = [k for k, name in SUMMARY_KEYS.items()
                             if (fields.get(name) or {}).get("status") == "missing"]
    return out


class DocStore:
    def __init__(self, roots=None):
        if roots is None:
            env = os.environ.get("DOCUMENT_ROOTS", "")
            roots = [r for r in env.split(os.pathsep) if r.strip()]
        self.roots = [os.path.realpath(os.path.expanduser(r)) for r in roots]
        self._cache = {}

    # -- path safety ------------------------------------------------------
    def _resolve(self, path, must_be="file"):
        if not path or not str(path).strip():
            raise DocError("path is required")
        real = os.path.realpath(os.path.expanduser(str(path)))
        if self.roots and not any(real == r or real.startswith(r + os.sep) for r in self.roots):
            raise DocError(f"{path} is outside the allowed DOCUMENT_ROOTS: {self.roots}")
        if must_be == "file":
            if not os.path.isfile(real):
                raise DocError(f"File not found: {path}")
            if os.path.splitext(real)[1].lower() not in ALLOWED_EXTS:
                raise DocError(f"Unsupported file type; allowed: {sorted(ALLOWED_EXTS)}")
        elif not os.path.isdir(real):
            raise DocError(f"Folder not found: {path}")
        return real

    # -- extraction -------------------------------------------------------
    def read(self, path, include_text=False, allow_ocr=True, max_pages=10):
        real = self._resolve(path)
        if not 1 <= int(max_pages) <= 50:
            raise DocError("max_pages must be between 1 and 50")
        st = os.stat(real)
        key = (real, st.st_size, st.st_mtime_ns, bool(allow_ocr), int(max_pages))
        doc = self._cache.get(key)
        if doc is None:
            doc = process(real, max_pages=int(max_pages), allow_ocr=allow_ocr,
                          include_text=True)
            self._cache[key] = doc
        result = {k: v for k, v in doc.items() if include_text or k != "text"}
        result["file"] = path
        if doc.get("status") == "ok":
            result["summary"] = summarize(doc)
        return result

    def read_many(self, paths, include_text=False, allow_ocr=True):
        if not paths:
            raise DocError("paths must be a non-empty list")
        if len(paths) > MAX_BATCH:
            raise DocError(f"At most {MAX_BATCH} files per call")
        docs = []
        for p in paths:
            try:
                docs.append(self.read(p, include_text, allow_ocr))
            except DocError as exc:
                docs.append({"file": p, "status": "error", "error": str(exc)})
        return self._batch(docs)

    def read_folder(self, folder, pattern="*.pdf", recursive=False, allow_ocr=True):
        real = self._resolve(folder, must_be="dir")
        if os.sep in pattern or "/" in pattern or ".." in pattern:
            raise DocError("pattern must be a file name pattern like '*.pdf'")
        glob_pat = os.path.join(real, "**", pattern) if recursive else os.path.join(real, pattern)
        files = sorted(f for f in glob.glob(glob_pat, recursive=recursive)
                       if os.path.isfile(f) and os.path.splitext(f)[1].lower() in ALLOWED_EXTS)
        if not files:
            return {**self._batch([]), "note": f"No matching documents in {folder}"}
        truncated = len(files) > MAX_BATCH
        result = self.read_many(files[:MAX_BATCH], allow_ocr=allow_ocr)
        result["truncated"] = truncated
        result["files_found"] = len(files)
        return result

    def from_text(self, text, source_name=None):
        """Field rules applied to text Claude transcribed (vision fallback for scans)."""
        if not text or len(text.strip()) < 10:
            raise DocError("text is empty or too short to extract from")
        doc = process(source_name or "transcription", text=text,
                      source_name=source_name or "transcription")
        doc["extraction"]["method"] = "transcription"
        doc["summary"] = summarize(doc)
        doc["note"] = "Fields extracted from a transcription; confirm values against the original"
        return doc

    @staticmethod
    def backends():
        def has(mod):
            return importlib.util.find_spec(mod) is not None
        tesseract = shutil.which("tesseract")
        return {
            "pdf_text": {"pdfplumber": has("pdfplumber"), "pypdf": has("pypdf"),
                         "pdftotext_cli": bool(shutil.which("pdftotext"))},
            "ocr": {"pytesseract+pypdfium2": has("pytesseract") and has("pypdfium2"),
                    "tesseract_cli": bool(tesseract),
                    "pdftoppm_cli": bool(shutil.which("pdftoppm"))},
            "can_read_text_pdfs": has("pdfplumber") or has("pypdf") or bool(shutil.which("pdftotext")),
            "can_ocr_scans": (has("pytesseract") and has("pypdfium2"))
                             or bool(tesseract and shutil.which("pdftoppm")),
            "allowed_extensions": sorted(ALLOWED_EXTS),
        }

    @staticmethod
    def _batch(docs):
        counts = {}
        for d in docs:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        return {"count": len(docs), "status_counts": counts,
                "needs_review": [d["file"] for d in docs
                                 if d["status"] != "ok" or d.get("needs_review")],
                "documents": docs}

