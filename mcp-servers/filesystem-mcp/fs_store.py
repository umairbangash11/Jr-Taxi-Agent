"""Read-only access to client folders for filesystem-mcp (no MCP dependency, unit-testable).

Layout (convention, folder names discovered at runtime):

    CLIENTS_ROOT/
      JR Taxi AS/            <- client
        Bank/                <- role "bank"
        Bokført/             <- role "booked"
        Innboks/             <- role "inbox"
        SAF-T/               <- role "saft"
        (any other folder)   <- listed, no role

If CLIENTS_ROOT itself contains role folders it is treated as a single client.

Security: every path is resolved (realpath) and must stay inside CLIENTS_ROOT, so '..',
absolute paths and symlinks pointing outside are refused. Hidden files are skipped.
Nothing is ever written.
"""

import fnmatch
import hashlib
import os
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
READER_DIR = os.path.join(PROJECT_ROOT, ".claude", "skills", "document-reader", "scripts")
sys.path.insert(0, READER_DIR)

from read_document import extract_text  # noqa: E402

DEFAULT_LEDGER_DB = os.path.join(PROJECT_ROOT, "data", "ledger.sqlite")
ROLE_NAMES = {
    "bank": ["bank", "bankutskrifter", "kontoutskrifter", "bankavstemming"],
    "booked": ["bokført", "bokfort", "bokførte bilag", "posted", "booked"],
    "inbox": ["innboks", "ubehandlet", "nye bilag", "bilag", "inbox", "til bokføring"],
    "saft": ["saf-t", "saft", "saf t"],
}
TEXT_EXTS = {".txt", ".csv", ".xml", ".json", ".md", ".tsv"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
DOC_EXTS = {".pdf"} | IMAGE_EXTS | TEXT_EXTS | {".tif", ".tiff", ".bmp"}
MAX_READ_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_CHARS = 100_000


class FsError(Exception):
    """User-facing error."""


def _norm(name):
    return unicodedata.normalize("NFC", name).casefold().strip()


ROLE_LOOKUP = {_norm(n): role for role, names in ROLE_NAMES.items() for n in names}


def _hidden(name):
    return name.startswith(".") or name.startswith("~$") or name in ("Thumbs.db", "desktop.ini")


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class FsStore:
    def __init__(self, root=None, ledger_db=None):
        root = root or os.environ.get("CLIENTS_ROOT")
        if not root:
            raise FsError("CLIENTS_ROOT is not set; point it at the folder with client folders")
        self.root = os.path.realpath(os.path.expanduser(root))
        if not os.path.isdir(self.root):
            raise FsError(f"CLIENTS_ROOT does not exist: {root}")
        self.ledger_db = ledger_db or os.environ.get("LEDGER_DB") or DEFAULT_LEDGER_DB
        self._hash_cache = {}

    # -- path safety ----------------------------------------------------
    def _inside(self, real):
        return real == self.root or real.startswith(self.root + os.sep)

    def _safe(self, path):
        real = os.path.realpath(path)
        if not self._inside(real):
            raise FsError("Path escapes CLIENTS_ROOT")
        return real

    def _single_client(self):
        return any(ROLE_LOOKUP.get(_norm(d)) for d in self._subdirs(self.root))

    def _subdirs(self, path):
        try:
            names = sorted(os.listdir(path))
        except OSError as exc:
            raise FsError(f"Cannot list {path}: {exc}") from exc
        return [n for n in names if not _hidden(n) and os.path.isdir(os.path.join(path, n))]

    def _client_dir(self, client):
        if self._single_client():
            if client not in (None, "", ".", os.path.basename(self.root)):
                raise FsError(f"Single-client root; the only client is "
                              f"{os.path.basename(self.root)!r}")
            return self.root
        if not client:
            raise FsError("client is required (see list_clients)")
        matches = [d for d in self._subdirs(self.root) if _norm(d) == _norm(client)]
        if not matches:
            raise FsError(f"Client {client!r} not found (see list_clients)")
        return self._safe(os.path.join(self.root, matches[0]))

    def _resolve(self, client, rel_path, want="file"):
        base = self._client_dir(client)
        if rel_path in (None, "", "."):
            real = base
        else:
            if os.path.isabs(rel_path) or os.path.splitdrive(rel_path)[0]:
                raise FsError("path must be relative to the client folder")
            real = self._safe(os.path.join(base, rel_path))
            if not (real == base or real.startswith(base + os.sep)):
                raise FsError("Path escapes the client folder")
        if want == "file" and not os.path.isfile(real):
            raise FsError(f"File not found: {rel_path}")
        if want == "dir" and not os.path.isdir(real):
            raise FsError(f"Folder not found: {rel_path}")
        return base, real

    # -- listing --------------------------------------------------------
    def list_clients(self):
        if self._single_client():
            dirs = [self.root]
        else:
            dirs = [os.path.join(self.root, d) for d in self._subdirs(self.root)]
        clients = []
        for d in dirs:
            folders = self._subdirs(d)
            roles = {ROLE_LOOKUP[_norm(f)]: f for f in folders if _norm(f) in ROLE_LOOKUP}
            clients.append({"client": os.path.basename(d), "folders": folders, "roles": roles})
        return {"root": self.root, "single_client": self._single_client(), "clients": clients}

    def list_folders(self, client):
        base = self._client_dir(client)
        out = []
        for f in self._subdirs(base):
            path = os.path.join(base, f)
            count = sum(1 for _, _, files in os.walk(path)
                        for n in files if not _hidden(n))
            out.append({"folder": f, "role": ROLE_LOOKUP.get(_norm(f)), "files": count})
        return {"client": os.path.basename(base), "folders": out}

    def _role_dirs(self, base, role):
        return [os.path.join(base, f) for f in self._subdirs(base)
                if ROLE_LOOKUP.get(_norm(f)) == role]

    def _walk(self, start, recursive, pattern, base):
        for dirpath, dirnames, files in os.walk(start, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if not _hidden(d))
            for n in sorted(files):
                if _hidden(n) or not fnmatch.fnmatch(n.casefold(), pattern.casefold()):
                    continue
                full = os.path.join(dirpath, n)
                real = os.path.realpath(full)
                if not (real == base or real.startswith(base + os.sep)):
                    continue  # symlink pointing outside the client folder
                yield full
            if not recursive:
                break

    def _info(self, full, base):
        st = os.stat(full)
        rel = os.path.relpath(full, base)
        top = rel.split(os.sep)[0] if os.sep in rel else None
        return {"path": rel.replace(os.sep, "/"), "name": os.path.basename(full),
                "folder": top, "role": ROLE_LOOKUP.get(_norm(top)) if top else None,
                "ext": os.path.splitext(full)[1].lower(), "size": st.st_size,
                "modified": _iso(st.st_mtime), "absolute_path": full}

    def list_files(self, client, folder=None, pattern="*", recursive=True, modified_after=None,
                   limit=None):
        base, start = self._resolve(client, folder, want="dir")
        if any(sep in pattern for sep in ("/", "\\")) or ".." in pattern:
            raise FsError("pattern must be a file-name pattern like '*.pdf'")
        after = None
        if modified_after:
            try:
                after = datetime.fromisoformat(modified_after)
            except ValueError:
                raise FsError("modified_after must be ISO date/time, e.g. 2025-06-01")
            if after.tzinfo is None:
                after = after.replace(tzinfo=timezone.utc)
        items = []
        for full in self._walk(start, recursive, pattern, base):
            info = self._info(full, base)
            if after and datetime.fromisoformat(info["modified"]) < after:
                continue
            items.append(info)
        limit = 500 if limit is None else max(1, min(int(limit), 5000))
        return {"client": os.path.basename(base), "folder": folder or ".",
                "total": len(items), "returned": min(len(items), limit),
                "truncated": len(items) > limit, "items": items[:limit]}

    def find_files(self, query, client=None, ext=None, limit=None):
        if not query or len(query.strip()) < 2:
            raise FsError("query must be at least 2 characters")
        q = _norm(query)
        bases = ([self._client_dir(client)] if client or self._single_client()
                 else [os.path.join(self.root, d) for d in self._subdirs(self.root)])
        items = []
        for base in bases:
            base = self._safe(base)
            for full in self._walk(base, True, "*", base):
                if q in _norm(os.path.relpath(full, base)) and \
                        (not ext or full.lower().endswith(ext.lower())):
                    items.append({"client": os.path.basename(base), **self._info(full, base)})
        limit = 200 if limit is None else max(1, min(int(limit), 2000))
        return {"total": len(items), "returned": min(len(items), limit),
                "truncated": len(items) > limit, "items": items[:limit]}

    # -- reading --------------------------------------------------------
    def read_file(self, client, path, max_chars=DEFAULT_MAX_CHARS, allow_ocr=False):
        """-> (info dict, image bytes or None)."""
        base, real = self._resolve(client, path)
        info = self._info(real, base)
        if info["size"] > MAX_READ_BYTES:
            raise FsError(f"File is larger than {MAX_READ_BYTES // (1024 * 1024)} MB")
        ext = info["ext"]
        max_chars = max(1000, min(int(max_chars), 1_000_000))
        if ext in TEXT_EXTS:
            with open(real, "rb") as fh:
                raw = fh.read()
            for enc in ("utf-8-sig", "cp1252"):
                try:
                    text = raw.decode(enc)
                    info["encoding"] = enc
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = raw.decode("latin-1")
                info["encoding"] = "latin-1"
            info.update(kind="text", text=text[:max_chars], truncated=len(text) > max_chars)
            return info, None
        if ext == ".pdf":
            text, meta = extract_text(real, allow_ocr=allow_ocr)
            info.update(kind="pdf", extraction=meta, text=text[:max_chars] or None,
                        truncated=len(text) > max_chars)
            if not text:
                info["note"] = ("No text layer (scan). Use document-mcp read_document with OCR, "
                                "or view the page image.")
            return info, None
        if ext in IMAGE_EXTS:
            if info["size"] > MAX_IMAGE_BYTES:
                raise FsError("Image larger than 5 MB; use document-mcp to OCR it instead")
            with open(real, "rb") as fh:
                data = fh.read()
            info.update(kind="image", note="Image returned as image content for viewing")
            return info, data
        raise FsError(f"Unsupported file type {ext!r}; readable: "
                      f"{sorted(TEXT_EXTS | IMAGE_EXTS | {'.pdf'})}")

    # -- pipeline helpers -------------------------------------------------
    def _hash(self, full):
        st = os.stat(full)
        key = (full, st.st_size, st.st_mtime_ns)
        if key not in self._hash_cache:
            self._hash_cache[key] = sha256_file(full)
        return self._hash_cache[key]

    def _ledger_hashes(self):
        if not self.ledger_db or not os.path.isfile(self.ledger_db):
            return None
        try:
            uri = "file:" + os.path.abspath(self.ledger_db).replace(os.sep, "/") + "?mode=ro"
            con = sqlite3.connect(uri, uri=True)
            try:
                rows = con.execute("SELECT source_sha256, bilag_no FROM entries "
                                   "WHERE source_sha256 IS NOT NULL AND status != 'reversed'")
                return {sha: no for sha, no in rows}
            finally:
                con.close()
        except sqlite3.Error:
            return None

    def find_unbooked(self, client):
        base = self._client_dir(client)
        inbox_dirs = self._role_dirs(base, "inbox")
        booked_dirs = self._role_dirs(base, "booked")
        if not inbox_dirs:
            raise FsError("Client has no inbox folder (Innboks/Ubehandlet/Bilag/...)")
        booked = {}
        for d in booked_dirs:
            for full in self._walk(d, True, "*", base):
                if os.path.splitext(full)[1].lower() in DOC_EXTS:
                    booked.setdefault(self._hash(full), os.path.relpath(full, base))
        ledger = self._ledger_hashes()
        unbooked, already = [], []
        for d in inbox_dirs:
            for full in self._walk(d, True, "*", base):
                if os.path.splitext(full)[1].lower() not in DOC_EXTS:
                    continue
                info = self._info(full, base)
                h = self._hash(full)
                info["sha256"] = h
                where = []
                if h in booked:
                    where.append(f"copy in booked folder: {booked[h].replace(os.sep, '/')}")
                if ledger and h in ledger:
                    where.append(f"booked in ledger as {ledger[h]}")
                if where:
                    already.append({**info, "already_booked": where})
                else:
                    unbooked.append(info)
        return {"client": os.path.basename(base),
                "inbox_folders": [os.path.basename(d) for d in inbox_dirs],
                "booked_folders": [os.path.basename(d) for d in booked_dirs],
                "ledger_checked": ledger is not None,
                "unbooked": unbooked, "already_booked": already,
                "note": "Matched by file content (sha256), so renamed copies are recognised"}

    def locate_inputs(self, client):
        """Latest SAF-T file and bank statements, as absolute paths for the other servers."""
        base = self._client_dir(client)

        def newest(role, exts):
            files = [self._info(f, base) for d in self._role_dirs(base, role)
                     for f in self._walk(d, True, "*", base)
                     if os.path.splitext(f)[1].lower() in exts]
            return sorted(files, key=lambda i: i["modified"], reverse=True)

        saft = newest("saft", {".xml"})
        bank = newest("bank", {".csv", ".txt", ".xml"})
        return {"client": os.path.basename(base),
                "saft_file": saft[0]["absolute_path"] if saft else None,
                "saft_candidates": [i["path"] for i in saft[:5]],
                "bank_statements": [{"path": i["path"], "absolute_path": i["absolute_path"],
                                     "modified": i["modified"]} for i in bank[:20]],
                "inbox_folders": [os.path.basename(d) for d in self._role_dirs(base, "inbox")],
                "note": "Newest by modification time; confirm the right period with the user"}
