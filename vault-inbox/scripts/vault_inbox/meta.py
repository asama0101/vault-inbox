from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .frontmatter import strip_managed

INITIAL_VOCABULARY = (
    "derived_from",
    "supersedes",
    "supports",
    "conflicts_with",
    "related",
)


class MetaCorrupt(Exception):  # noqa: N818 - public name, used by the CLI and tests
    pass


@dataclass
class Doc:
    id: str
    hash: str
    path: str
    date: str
    summary: str
    state: str = "active"  # "active" or "placing"


def _doc(d: dict) -> Doc:
    """A Doc from its stored dict. Older files also hold `tags`, which are dropped."""
    if isinstance(d, dict):
        d = {k: v for k, v in d.items() if k != "tags"}
    return Doc(**d)


def file_hash(path: Path) -> str:
    """SHA-256 of the file. For Markdown, our own frontmatter keys are left out, so
    rewriting them does not make the material look edited."""
    if path.suffix.lower() == ".md":
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            pass  # not text: hash the bytes
        else:
            return hashlib.sha256(strip_managed(text).encode("utf-8")).hexdigest()
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def new_id() -> str:
    return uuid.uuid4().hex


def _posix(path: str) -> str:
    return path.replace("\\", "/")


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("docs"), dict):
        raise ValueError("unexpected meta structure")
    for d in data["docs"].values():
        try:
            _doc(d)
        except TypeError as e:  # missing or unexpected fields, or not a dict
            raise ValueError(f"unexpected doc fields: {e}") from e
    return data


class MetaStore:
    def __init__(self, root: Path):
        self._file = root / ".vault-inbox" / "meta.json"
        self._bak = self._file.with_name("meta.json.bak")
        self._docs: dict[str, Doc] = {}
        self._relations: list[dict] = []
        self._vocabulary: list[str] = list(INITIAL_VOCABULARY)
        self._ignored: list[dict] = []
        self._dups: list[dict] = []
        self._inbox: list[dict] = []

    def load(self) -> None:
        data = None
        corrupt = False
        for p in (self._file, self._bak):
            if not p.exists():
                continue
            try:
                data = _read_json(p)
                break
            except (ValueError, OSError):  # JSONDecodeError is a ValueError
                corrupt = True
        if data is None:
            if corrupt:
                raise MetaCorrupt(f"{self._file} is corrupt and no valid backup exists")
            return
        self._docs = {i: _doc(d) for i, d in data["docs"].items()}
        self._relations = data.get("relations", [])
        self._vocabulary = data.get("vocabulary", list(INITIAL_VOCABULARY))
        self._ignored = data.get("ignored", [])
        self._dups = data.get("dups", [])
        self._inbox = data.get("inbox", [])

    def save(self) -> None:
        data = {
            "version": 1,
            "docs": {i: asdict(d) for i, d in self._docs.items()},
            "relations": self._relations,
            "vocabulary": self._vocabulary,
            "ignored": self._ignored,
            "dups": self._dups,
            "inbox": self._inbox,
        }
        tmp = self._file.with_name("meta.json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if self._file.exists():
            try:
                _read_json(self._file)
                shutil.copyfile(
                    self._file, self._bak
                )  # never overwrite bak with a corrupt file
            except ValueError:
                pass
        Path(tmp).replace(self._file)

    def docs(self) -> list[Doc]:
        return list(self._docs.values())

    def get(self, id: str) -> Doc | None:
        return self._docs.get(id)

    def by_path(self, path: str) -> Doc | None:
        path = _posix(path)
        return next((d for d in self._docs.values() if d.path == path), None)

    def by_hash(self, hash: str) -> list[Doc]:
        return [d for d in self._docs.values() if d.hash == hash]

    def put(self, doc: Doc) -> None:
        doc.path = _posix(doc.path)
        self._docs[doc.id] = doc

    def update_doc(
        self,
        id: str,
        date: str | None = None,
        summary: str | None = None,
    ) -> bool:
        """Change only the given fields. Returns False for an unknown id."""
        doc = self._docs.get(id)
        if doc is None:
            return False
        if date is not None:
            doc.date = date
        if summary is not None:
            doc.summary = summary
        return True

    def remove(self, id: str) -> None:
        """Remove the doc only; its relations stay and show up as dangling."""
        self._docs.pop(id, None)

    def ignore(self, path: str, hash: str) -> None:
        self._add(self._ignored, path, hash)

    def is_ignored(self, path: str, hash: str) -> bool:
        return {"path": _posix(path), "hash": hash} in self._ignored

    def mark_dup(self, path: str, hash: str) -> None:
        self._add(self._dups, path, hash)

    def notified_dup(self, path: str, hash: str) -> bool:
        return {"path": _posix(path), "hash": hash} in self._dups

    def note_inbox(self, name: str, hash: str, status: str) -> None:
        """Remember an inbox leftover that was already reported to the user."""
        entry = {"name": name, "hash": hash, "status": status}
        if entry not in self._inbox:
            self._inbox.append(entry)

    def is_noted(self, name: str, hash: str, status: str) -> bool:
        return {"name": name, "hash": hash, "status": status} in self._inbox

    def noted(self, name: str, hash: str) -> list[str]:
        """Statuses this inbox file was noted with, for this exact content."""
        return [
            e["status"] for e in self._inbox if (e["name"], e["hash"]) == (name, hash)
        ]

    @staticmethod
    def _add(entries: list[dict], path: str, hash: str) -> None:
        entry = {"path": _posix(path), "hash": hash}
        if entry not in entries:
            entries.append(entry)

    def relations(self) -> list[dict]:
        return list(self._relations)

    def _find_relation(self, src: str, dst: str, kind: str) -> dict | None:
        key = (src, dst, kind)
        return next(
            (r for r in self._relations if (r["src"], r["dst"], r["kind"]) == key),
            None,
        )

    def add_relation(self, src: str, dst: str, kind: str) -> None:
        if kind not in self._vocabulary:
            raise ValueError(f"unknown relation kind: {kind}")
        if self._find_relation(src, dst, kind) is None:
            self._relations.append({"src": src, "dst": dst, "kind": kind})

    def remove_relation(self, src: str, dst: str, kind: str) -> None:
        rel = self._find_relation(src, dst, kind)
        if rel is not None:
            self._relations.remove(rel)

    def keep_relation(self, src: str, dst: str, kind: str) -> bool:
        """Mark a relation the user chose to keep, so dangling() skips it."""
        rel = self._find_relation(src, dst, kind)
        if rel is None:
            return False
        rel["kept"] = True
        return True

    def vocabulary(self) -> list[str]:
        return list(self._vocabulary)

    def add_kind(self, kind: str) -> None:
        if kind not in self._vocabulary:
            self._vocabulary.append(kind)
