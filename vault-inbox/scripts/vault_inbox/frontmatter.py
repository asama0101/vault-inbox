"""The properties (YAML frontmatter) that this plugin keeps in a Markdown material.

Our keys are MANAGED plus a marker key, `vault-inbox: true`. The marker says the block
is ours to rewrite: a file that has one of our key names without the marker belongs to
its author, and nothing here touches it. The keys are found by name, not by a comment,
because Obsidian may rewrite the block and drop comments.
"""

from __future__ import annotations

import datetime
import json
import re

MANAGED = ("要約", "日付", "関連")
MARKER_KEY = "vault-inbox"
LEGACY_KEYS = ("タグ",)  # written by an earlier version: removed, never written
_KEY = re.compile(rf"(?:{'|'.join((*MANAGED, *LEGACY_KEYS, MARKER_KEY))})\s*:")
_MARKER = re.compile(rf"{MARKER_KEY}\s*:")
_OURS = re.compile(rf"(?:{'|'.join(MANAGED)})\s*:")
_LINE_BREAKS = {" ": "\\u2028", " ": "\\u2029", "\x85": "\\x85"}


_FIRST_KEY = re.compile(r"""(?:"[^"]*"|'[^']*'|[^\s#"'-][^:]*?)\s*:(?:\s|$)""")


def _looks_like_properties(inner: list[str]) -> bool:
    """An empty block, or one whose first line is a `key:` (a list or prose between
    two --- lines is a horizontal rule and text, not properties)."""
    for line in inner:
        s = line.strip()
        if s and not s.startswith("#"):
            return bool(_FIRST_KEY.match(s))
    return True


def _split_bom(text: str) -> tuple[str, str]:
    return ("﻿", text[1:]) if text.startswith("﻿") else ("", text)


def _block_end(lines: list[str]) -> int | None:
    """Index of the closing --- line when the text opens with a YAML block."""
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            return i if _looks_like_properties(lines[1:i]) else None
    return None


def _is_value_line(s: str) -> bool:
    return bool(s) and (s[0] in " \t" or s.startswith("-"))


def _drop_managed(inner: list[str]) -> tuple[list[str], bool]:
    kept: list[str] = []
    pending: list[
        str
    ] = []  # blank lines after a dropped key: dropped only if more value follows
    skipping = removed = False
    for line in inner:
        s = line.rstrip("\r\n")
        if _KEY.match(s):
            skipping = removed = True
            pending = []
            continue
        if skipping and not s.strip():
            pending.append(line)
            continue
        if skipping and _is_value_line(s):
            pending = []
            continue
        skipping = False
        kept += pending + [line]
        pending = []
    return kept + pending, removed


def _find_block(text: str):
    bom, body = _split_bom(text)
    lines = body.splitlines(keepends=True)
    return bom, lines, _block_end(lines)


def is_ours(text: str) -> bool:
    """True when the block carries our marker key."""
    _, lines, end = _find_block(text)
    return end is not None and any(_MARKER.match(x) for x in lines[1:end])


def has_foreign_keys(text: str) -> bool:
    """True when the author uses one of our key names without our marker."""
    _, lines, end = _find_block(text)
    if end is None or is_ours(text):
        return False
    return any(_OURS.match(x) for x in lines[1:end])


def strip_managed(text: str) -> str:
    """The text without our keys (a block that only we made goes away entirely)."""
    bom, lines, end = _find_block(text)
    if end is None or not is_ours(text):
        return text
    inner, _ = _drop_managed(lines[1:end])
    if all(not x.strip() for x in inner):
        return bom + "".join(lines[end + 1 :])
    return bom + "".join([lines[0], *inner, *lines[end:]])


def _quote(value: str) -> str:
    out = json.dumps(value, ensure_ascii=False)
    for ch, esc in _LINE_BREAKS.items():
        out = out.replace(ch, esc)
    return out


def _is_date(value: str) -> bool:
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return len(value) == 10


def render(props: dict, nl: str = "\n") -> str:
    """YAML lines for the keys of props that have a value, in MANAGED order."""
    out = []
    for key in MANAGED:
        value = props.get(key)
        if not value:
            continue
        if isinstance(value, list):
            out.append(f"{key}:{nl}")
            out += [f"  - {_quote(v)}{nl}" for v in value]
        elif _is_date(value):
            out.append(f"{key}: {value}{nl}")
        else:
            out.append(f"{key}: {_quote(value)}{nl}")
    return "".join(out)


def set_managed(text: str, props: dict) -> str:
    """The text with our keys set to props (our old keys are replaced).

    The caller checks has_foreign_keys first: this does not look at who owns a key."""
    bom, body = _split_bom(strip_managed(text))
    lines = body.splitlines(keepends=True)
    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    new = render(props, nl)
    if not new:
        return bom + body
    new += f"{MARKER_KEY}: true{nl}"
    end = _block_end(lines)
    # An empty block of the person's is left alone and ours goes before it: if we put
    # our keys inside it, taking them out again would also take the block away.
    if end is None or all(not x.strip() for x in lines[1:end]):
        return f"{bom}---{nl}{new}---{nl}{body}"
    return bom + "".join(lines[:end]) + new + "".join(lines[end:])
