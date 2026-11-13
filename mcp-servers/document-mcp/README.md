# document-mcp

An MCP server (stdio) that reads invoice (**faktura**) and receipt (**kvittering**) PDFs and images. It
extracts **supplier, org number, date, total amount, VAT rate, invoice number and type**.

Extraction is done by the `document-reader` skill
(`.claude/skills/document-reader/scripts/read_document.py`), so Claude and the scripts use the same rules.
No field is ever guessed. Each field has a status: `ok`, `unclear` (with candidates) or `missing`.
Results are cached per file using its size and mtime, so scans aren't OCR'd twice.

## Setup

- Requires Python ≥ 3.10 and `mcp>=1.9,<2`, which is already installed. Optional backends are listed in `requirements.txt`.
- It is registered in the project's `.mcp.json` as **`documents`**. Approve it the first time you start `claude`.
- **Sandbox (recommended):** set `DOCUMENT_ROOTS` to the folder(s) that hold the bilag, separated with `;` on Windows. Every path outside those folders is refused. If it's unset, any `.pdf` or image file the user can read is allowed.

## Tools

| Tool | Purpose |
|---|---|
| `read_document(path, include_text=false, allow_ocr=true, max_pages=10)` | Reads one file |
| `read_documents(paths)` | Reads up to 100 files. An error in one file doesn't fail the batch |
| `read_folder(folder, pattern="*.pdf", recursive=false)` | Reads every matching document in a folder, up to 100 |
| `extract_from_text(text, source_name?)` | **Vision fallback:** when a scan comes back `needs_ocr`, Claude views the file, copies the text exactly, and calls this |
| `get_extraction_backends()` | Shows which PDF-text and OCR backends are installed |

### Result per document

```jsonc
{
  "file": "C:/bilag/kvittering.pdf",
  "status": "ok",                       // ok | needs_ocr | error
  "summary": {                          // confirmed values only; unclear/missing -> null
    "supplier": "OSLO TAXI SENTRAL AS", "org_number": "912345610", "date": "2025-06-14",
    "amount": 845, "currency": "NOK", "vat_rate": 12, "type": "kvittering",
    "invoice_number": null, "unclear_fields": [], "missing_fields": ["invoice_number"]
  },
  "fields": { "vendor_name": {"value", "status", "confidence", "evidence", "candidates", "reason"}, ... },
  "needs_review": false, "flags": [], "extraction": {"method": "pdftotext", "ocr": false, ...}
}
```
The batch tools return `{count, status_counts, needs_review: [files], documents: [...]}`.

## Backends on this machine

The `pdftotext` program (shipped with Git for Windows) reads PDFs that have a text layer.
Scans and photos need OCR. Either install `pytesseract`, `pypdfium2` and Tesseract (`nor`), or
use the vision fallback through `extract_from_text`.

## Tests

```bash
python mcp-servers/document-mcp/tests/test_document_mcp.py -v
```
There are 9 store tests (summary, cache invalidation, needs_ocr, unclear fields, sandbox, batch and folder reads) and 1 full stdio round trip.
