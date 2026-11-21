from __future__ import annotations

import sqlite3
from pathlib import Path

from .extract import ExtractError, extract_text
from .meta import MetaStore

_MIN_FTS_LEN = 3


def text_dir(root: Path) -> Path:
    return root / ".vault-inbox" / "text"


def _text_path(root: Path, doc_id: str) -> Path:
    return text_dir(root) / f"{doc_id}.txt"


def _db_path(root: Path) -> Path:
    return root / ".vault-inbox" / "index.db"


def save_text(root: Path, doc_id: str, text: str) -> Path:
    path = _text_path(root, doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def load_text(root: Path, doc_id: str) -> str:
    return _text_path(root, doc_id).read_text(encoding="utf-8")


def _connect(root: Path) -> sqlite3.Connection:
    return sqlite3.connect(_db_path(root))


def rebuild(root: Path, store: MetaStore) -> int:
    db = _db_path(root)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)
    conn = _connect(root)
    try:
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE docs "
                "USING fts5(id UNINDEXED, body, tokenize='trigram')"
            )
        except sqlite3.OperationalError as e:
            raise RuntimeError("fts5 trigram unavailable") from e
        count = 0
        for doc in store.docs():
            if doc.state != "active":
                continue
            try:
                text = load_text(root, doc.id)
            except OSError:
                try:
                    text = extract_text(root / doc.path)
                except (ExtractError, OSError):
                    continue
                save_text(root, doc.id, text)
            conn.execute("INSERT INTO docs (id, body) VALUES (?, ?)", (doc.id, text))
            count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def ensure(root: Path, store: MetaStore) -> bool:
    """Rebuild the index if it is missing, unreadable, or lacks an active doc whose
    text we hold (a pass that stopped between saving meta.json and the index update).
    A doc with no text file is skipped: rebuild would skip it too, so checking it
    would rebuild on every search."""
    if _db_path(root).exists():
        try:
            conn = _connect(root)
            try:
                indexed = {r[0] for r in conn.execute("SELECT id FROM docs")}
            finally:
                conn.close()
            if all(
                d.id in indexed or not _text_path(root, d.id).exists()
                for d in store.docs()
                if d.state == "active"
            ):
                return False
        except sqlite3.DatabaseError:
            pass
    rebuild(root, store)
    return True


def search(root: Path, store: MetaStore, query: str, limit: int = 20) -> list[str]:
    terms = query.split()
    if not terms:
        return []
    long_terms = [t for t in terms if len(t) >= _MIN_FTS_LEN]
    short_terms = [t.casefold() for t in terms if len(t) < _MIN_FTS_LEN]
    active = {d.id for d in store.docs() if d.state == "active"}

    if long_terms:
        match = " ".join('"' + t.replace('"', '""') + '"' for t in long_terms)
        conn = _connect(root)
        try:
            rows = conn.execute(
                "SELECT id FROM docs WHERE docs MATCH ? ORDER BY rank", (match,)
            ).fetchall()
        finally:
            conn.close()
        ids = [r[0] for r in rows if r[0] in active]
    else:
        ids = [d.id for d in store.docs() if d.id in active]

    result = []
    for doc_id in ids:
        if short_terms:
            try:
                body = load_text(root, doc_id).casefold()
            except OSError:
                continue
            if not all(t in body for t in short_terms):
                continue
        result.append(doc_id)
        if len(result) >= limit:
            break
    return result
