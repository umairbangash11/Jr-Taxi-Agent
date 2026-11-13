# filesystem-mcp

A **read-only** MCP server (stdio) for the accounting client folders. It lists and reads
documents in folders such as Bank, Bokført, Innboks and SAF-T, and links them to the other servers.

## Folder convention

```
CLIENTS_ROOT/
  JR Taxi AS/              ← client (one folder per client)
    Bank/                  ← role: bank     (also: Bankutskrifter, Kontoutskrifter)
    Bokført/               ← role: booked   (also: Bokfort, Bokførte bilag)
    Innboks/               ← role: inbox    (also: Ubehandlet, Nye bilag, Bilag, Til bokføring)
    SAF-T/                 ← role: saft     (also: SAFT)
    Anything else/         ← listed and readable, no role
```

Folder names are matched without regard to case or Unicode normalisation, so a `Bokført`
created on a Mac matches too. If `CLIENTS_ROOT` contains role folders directly, it is treated as **one client**.
If your folder names differ, add them to `ROLE_NAMES` in `fs_store.py`.

## Setup

- It is registered in the project's `.mcp.json` as **`filesystem`**. Set **`CLIENTS_ROOT`** before starting Claude Code, then approve the server.
- `LEDGER_DB` is optional and defaults to `data/ledger.sqlite`. It lets `find_unbooked` check the ledger-mcp bookings. The database is opened **read-only**.
- If `CLIENTS_ROOT` is missing, the server still starts, and each tool call explains what to set.

## Tools

| Tool | Purpose |
|---|---|
| `list_clients()` | Lists the clients, their folders, and the roles that were recognised |
| `list_folders(client)` | Lists a client's folders with their role and file count |
| `list_files(client, folder?, pattern="*", recursive=true, modified_after?, limit?)` | Lists files, with `absolute_path` included for the other servers |
| `find_files(query, client?, ext?)` | Searches file and folder names, in one client or across all clients |
| `read_file(client, path, max_chars?, allow_ocr=false)` | Reads one file. CSV, XML, JSON and TXT come back as text (UTF-8, falling back to cp1252). For a PDF, the text is extracted. Images come back as **image content** so Claude can view them, up to 5 MB |
| `find_unbooked(client)` | Finds inbox documents that **aren't booked yet**. Files are compared by content (sha256) with the Bokført folder **and** with the ledger-mcp database, so a renamed copy still counts as booked |
| `locate_inputs(client)` | Gives the newest SAF-T file and the bank statements as absolute paths, ready for saft-mcp, bank-mcp and reconcile-mcp |

## Safety

- **Nothing is ever written, moved or deleted.**
- Every path is resolved and must stay inside `CLIENTS_ROOT`, and inside the given client's folder. Paths with `..`, absolute paths, and Windows drive paths are refused.
- **Symlinks** that point outside the folder are refused through the same `realpath` check, and they are left out of listings. *The test for this is skipped on this machine*, because creating symlinks on Windows requires Developer Mode or admin rights.
- Hidden and system files (`.*`, `~$*`, `Thumbs.db`, `desktop.ini`) are skipped. File reads are limited to 20 MB, and images to 5 MB.

## Pipeline

```
filesystem: find_unbooked ─▶ document-mcp: read_document(absolute_path) ─▶ entry-builder ─▶ qa-validator
filesystem: locate_inputs ─▶ saft-mcp / bank-mcp / reconcile-mcp
                                         ledger-mcp: book_entry  ─▶ find_unbooked no longer lists it
```

## Tests

```bash
python mcp-servers/filesystem-mcp/tests/test_filesystem_mcp.py -v
```
There are 15 store tests and 1 stdio round trip. The round trip checks that an image comes back as text plus image content, and that a path escape is refused. The symlink test is skipped when the system doesn't allow symlinks.
