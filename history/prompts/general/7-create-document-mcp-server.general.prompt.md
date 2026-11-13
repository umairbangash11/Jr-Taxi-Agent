---
id: 7
title: Create document-mcp server
stage: general
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: none
labels: ["mcp", "pdf", "ocr", "invoice", "receipt"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .mcp.json
 - mcp-servers/document-mcp/server.py
 - mcp-servers/document-mcp/doc_store.py
 - mcp-servers/document-mcp/requirements.txt
 - mcp-servers/document-mcp/README.md
 - mcp-servers/document-mcp/tests/test_document_mcp.py
tests:
 - mcp-servers/document-mcp/tests/test_document_mcp.py (10 tests incl. stdio round trip, all pass)
---

## Prompt

document-mcp — reads invoice/receipt PDFs and extracts supplier, date, amount, VAT, type.

## Response snapshot

Built a stdio FastMCP server that reuses the document-reader skill's `process`, so there is one set of field rules. It has 5 tools: read_document, read_documents, read_folder, extract_from_text (the vision fallback for scans without OCR) and get_extraction_backends. Each result includes a compact `summary` that holds only confirmed values, with unclear and missing fields listed, plus the full per-field detail. Results are cached per file by path, size and mtime. The optional DOCUMENT_ROOTS sandbox resolves realpath, refuses paths outside the roots and accepts only .pdf and image extensions. Folder globs reject path traversal, and batches are capped at 100. The server is registered in `.mcp.json` as `documents`.

## Outcome

- ✅ Impact: Claude can read bilag PDFs through MCP using the same no-guessing rules as the skill.
- 🧪 Tests: 10 pass, including a real stdio round trip that checks the needs_ocr status, extraction from transcribed text and sandbox rejection.
- 📁 Files: .mcp.json updated plus 5 new files under mcp-servers/document-mcp/
- 🔁 Next prompts: Approve the server; set DOCUMENT_ROOTS to the bilag folder; decide on installing OCR.
- 🧠 Reflection: The summary view exposes only confirmed values, so a consumer of the summary can't treat an unclear value as fact by mistake.

## Evaluation notes (flywheel)

- Failure modes observed: none; an unused import was removed before the tests ran.
- Graders run and results (PASS/FAIL): unittest PASS
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Run read_folder on a real month of bilag and measure the share of fields with status ok.
