---
id: 11
title: Create filesystem-mcp server
stage: general
date: 2026-11-12
surface: agent
model: claude-opus-5-5
feature: none
branch: master
user: umairbangash11
command: none
labels: ["mcp", "filesystem", "client-folders", "read-only", "security"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .mcp.json
 - mcp-servers/filesystem-mcp/server.py
 - mcp-servers/filesystem-mcp/fs_store.py
 - mcp-servers/filesystem-mcp/requirements.txt
 - mcp-servers/filesystem-mcp/README.md
 - mcp-servers/filesystem-mcp/tests/test_filesystem_mcp.py
tests:
 - mcp-servers/filesystem-mcp/tests/test_filesystem_mcp.py (16 tests: 15 pass, 1 skipped — symlinks not permitted on this Windows account)
 - full regression: 163 tests across 5 skills + 6 MCP servers pass (1 skipped)
---

## Prompt

filesystem-mcp — reads documents from the client folders (Bank, Bokført, etc.).

## Response snapshot

Built a read-only stdio FastMCP server over CLIENTS_ROOT.

**Folder roles:** the client and folder layout is convention-based, with Bank→bank, Bokført→booked, Innboks/Ubehandlet/Bilag→inbox and SAF-T→saft. Names are matched case-insensitively and NFC-normalised. If the root contains role folders directly, it is treated as a single client.

**7 tools:**
- list_clients, list_folders, list_files (with absolute_path) and find_files
- read_file: text with a UTF-8/cp1252 fallback, PDF text through document-reader's extract_text, and images returned as MCP image content
- find_unbooked: compares inbox files by sha256 with the Bokført folder and with the ledger-mcp database, opened read-only
- locate_inputs: the newest SAF-T file and the bank statements, for the other servers

**Safety:** every path is resolved with realpath and must stay inside the root and the client folder, so `..`, absolute and drive paths are refused. Symlinks are filtered, hidden and system files are skipped, and there are size limits. Nothing is written. A missing CLIENTS_ROOT doesn't crash the server; the tools report it instead. The server is registered in `.mcp.json` as `filesystem`.

## Outcome

- ✅ Impact: Claude can browse the client folders safely and see what is not booked yet, with renamed copies recognised.
- 🧪 Tests: 15 pass and 1 is skipped (the symlink test needs Developer Mode or admin). The stdio round trip verifies image content and path-escape refusal. The full regression passes.
- 📁 Files: 5 new files under mcp-servers/filesystem-mcp/, .mcp.json updated
- 🔁 Next prompts: Set CLIENTS_ROOT to the real client folder; approve the 6 servers; adjust ROLE_NAMES if the folder names differ; commit.
- 🧠 Reflection: Content hashes link the folder view to the ledger, so "unbooked" means booked nowhere rather than only "not moved yet".

## Evaluation notes (flywheel)

- Failure modes observed: none in the tests. The symlink-escape protection is implemented but not verified on this machine, and this is stated in the README.
- Graders run and results (PASS/FAIL): unittest PASS (1 skip)
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Run find_unbooked on the real JR Taxi folders and compare the result with the bookkeeper's own list of open bilag.
