"""Properties and summary notes.

The module and its CLI command keep the name `indexmd` from when they also wrote a
folder index: the skills and users call the command."""

from __future__ import annotations

import contextlib
import os
import posixpath
import re
import shutil
from pathlib import Path

from . import ownwrites
from .frontmatter import has_foreign_keys, render, set_managed
from .meta import MetaStore

# Folder indexes written by older versions. They are no longer made. Until the next run
# removes them (only when they are ours) they must not be taken in as materials, and a
# file a person made under one of these names is kept, but is not a material either.
_OLD_INDEX_NAMES = (".index.md", "_index.md")
NOTE_SUFFIX = ".要約.md"  # <material name>.要約.md: the visible summary note
# Written into every file we generate (after the frontmatter, which must come first).
# Only a file that carries it (or looks like the _index.md of an older version) is
# overwritten or removed; a file a person made under the same name is left alone.
_MARK = "<!-- vault-inbox:generated -->"
_TMP_SUFFIX = ".vault-inbox.tmp"  # beside a material while we rewrite it
_ROOTS = ("project", "shared")
_OBSIDIAN_EXTS = frozenset({".md", ".pdf", ".png", ".jpg", ".jpeg"})
_LINK_BREAKERS = "[]|#^"


def is_generated(name: str) -> bool:
    """A name this plugin writes (or wrote in an older version): never a material."""
    return (
        name in _OLD_INDEX_NAMES
        or name.endswith(NOTE_SUFFIX)
        or name.endswith(_TMP_SUFFIX)
    )


def link_for(rel_path: str) -> str:
    """[[<vault path>|<name>]] for files Obsidian opens, else the plain name.

    The full path keeps links unambiguous when two folders hold the same name.
    A path with a character that has a meaning inside [[...]] cannot be written as
    a link, so it stays plain text.
    """
    path = rel_path.replace("\\", "/")
    name = posixpath.basename(path)
    if any(c in path for c in _LINK_BREAKERS):
        return name
    if posixpath.splitext(name)[1].lower() in _OBSIDIAN_EXTS:
        return f"[[{path}|{name}]]"
    return name


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _link_to(doc, kind: str, arrow: str) -> str:
    """A link item for the 関連 property: to the Markdown material itself (it carries
    the properties) or, for any other format, to its summary note."""
    path = doc.path if doc.path.lower().endswith(".md") else doc.path + NOTE_SUFFIX
    name = posixpath.basename(doc.path)
    label = f"{kind} {arrow} {name}"
    if any(c in path for c in _LINK_BREAKERS):
        return label
    return f"[[{path}|{label}]]"


def _props(doc, links: list[str]) -> dict:
    return {
        "要約": _one_line(doc.summary),
        "日付": doc.date,
        "関連": links,
    }


def _render_note(doc, props: dict) -> str:
    front = render(props)
    head = f"---\n{front}---\n" if front else ""
    out = [f"{head}{_MARK}", f"# {posixpath.basename(doc.path)}", ""]
    out.append(f"- 資料: {link_for(doc.path)}")
    if props["要約"]:
        out += ["", props["要約"]]
    return "\n".join(out) + "\n"


def _rewrite_frontmatter(root: Path, doc, props: dict, entries: dict) -> bool | None:
    """Set our properties in a Markdown material.

    True: done (or already current). None: not now, try again next run (it is being
    saved, or the disk refused). False: never for this file (not UTF-8 text, a link,
    read-only, or the author uses our key names): the caller writes a note instead.
    """
    path = root / doc.path
    try:
        before = path.stat()
        if path.is_symlink() or before.st_nlink > 1 or not os.access(path, os.W_OK):
            return False  # replacing it would break the link or cannot be done
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return False
    except OSError:
        return None
    if has_foreign_keys(text):
        return False
    new = set_managed(text, props)
    if new == text:
        return True
    tmp = path.with_name(f".{path.name}{_TMP_SUFFIX}")
    try:
        tmp.write_bytes(new.encode("utf-8"))
        shutil.copymode(path, tmp)
        now = path.stat()
        if (now.st_mtime_ns, now.st_size) != (before.st_mtime_ns, before.st_size):
            return None  # saved by someone since we read it: do not overwrite
        tmp.replace(path)  # never leaves a half-written material
        st = path.stat()
    except OSError:
        return None
    except ValueError:  # text that cannot be encoded: leave the material alone
        return False
    finally:
        with contextlib.suppress(OSError):
            tmp.chmod(0o666)  # copymode may have made it read-only
            tmp.unlink()
    entries[doc.path] = [before.st_mtime_ns, before.st_size, st.st_mtime_ns, st.st_size]
    return True


def _has_mark(text: str) -> bool:
    """The mark is the first line, or the first line after a frontmatter block."""
    if text.startswith(_MARK):
        return True
    end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
    return end != -1 and text[end + 5 :].startswith(_MARK)


def _ours(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    # An older _index.md has no mark: it began with the name of its own folder.
    name = re.escape(path.parent.name)
    old = re.match(rf"# {name}\n\n## (資料|サブフォルダ|関係)\n", text)
    return _has_mark(text) or bool(old)


def _write(root: Path, rel: str, text: str) -> bool:
    """Write a generated file. False when it must not (or cannot) be written."""
    target = root / rel
    body = text
    try:
        if target.is_file():
            if target.read_text(encoding="utf-8") == body:
                return True
            if not _ours(target):
                return False
        elif target.exists():
            return False
        with target.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    except (OSError, ValueError):
        return False  # e.g. a path over the Windows limit: skip it, go on
    return True


def write_notes(root: Path, store: MetaStore) -> list[str]:
    """Write our properties into the Markdown materials and a summary note beside every
    other material, and clean up what we wrote earlier. Returns the notes written."""
    active = {
        d.id: d
        for d in store.docs()
        if d.state == "active"
        and d.path.split("/")[0] in _ROOTS
        and (root / d.path).is_file()
    }
    note_links: dict[str, list[str]] = {}
    for r in store.relations():
        src, dst = active.get(r["src"]), active.get(r["dst"])
        if not (src and dst):
            continue
        note_links.setdefault(src.id, []).append(_link_to(dst, r["kind"], "→"))
        note_links.setdefault(dst.id, []).append(_link_to(src, r["kind"], "←"))

    written: list[str] = []
    entries: dict[str, list[int]] = {}
    for doc in active.values():
        props = _props(doc, sorted(set(note_links.get(doc.id, []))))
        is_md = doc.path.lower().endswith(".md")
        if is_md and _rewrite_frontmatter(root, doc, props, entries) is not False:
            continue
        rel = doc.path + NOTE_SUFFIX
        if _write(root, rel, _render_note(doc, props)):
            written.append(rel)
    ownwrites.record(root, entries)
    # normcase: Foo and foo are one folder on Windows, so compare without letter case
    keep = {os.path.normcase(k) for k in written}
    # never remove a registered material
    protected = {os.path.normcase(d.path) for d in store.docs()}
    for top in _ROOTS:
        for dirpath, dirnames, filenames in os.walk(root / top):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                p = Path(dirpath) / name
                if name.endswith(_TMP_SUFFIX):  # left by a run that was cut short
                    with contextlib.suppress(OSError):
                        p.unlink()
                    continue
                rel = os.path.normcase(p.relative_to(root).as_posix())
                if (
                    is_generated(name)
                    and rel not in keep
                    and rel not in protected
                    and _ours(p)
                ):
                    with contextlib.suppress(OSError):
                        p.chmod(0o666)  # a read-only leftover would refuse to go
                        p.unlink()
    return written
