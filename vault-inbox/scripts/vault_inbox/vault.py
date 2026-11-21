from __future__ import annotations

from pathlib import Path

DEPTH_LIMIT = 5
SUPPORTED_EXTS = frozenset({".md", ".txt", ".html", ".pdf", ".docx", ".xlsx", ".pptx"})

TOPS = ("project", "shared")

_LAYOUT = ("inbox", "project", "shared", ".vault-inbox", ".vault-inbox/text")


def vault_parts(rel: str) -> list[str]:
    """Split a vault-relative path under project/ or shared/.

    Raises ValueError for anything that could leave those folders or reach a
    hidden one: a backslash, an empty, ".", ".." or dot-prefixed component,
    another top folder, or fewer than 2 components.
    """
    parts = rel.split("/")
    if (
        "\\" in rel
        or len(parts) < 2
        or parts[0] not in TOPS
        or any(p in ("", ".", "..") or p.startswith(".") for p in parts)
    ):
        raise ValueError(f"not a safe path under project/ or shared/: {rel!r}")
    return parts


def find_root(cwd: Path) -> Path:
    return cwd


def has_obsidian(root: Path) -> bool:
    return (root / ".obsidian").is_dir()


def is_initialized(root: Path) -> bool:
    return (root / "inbox").is_dir() and (root / ".vault-inbox").is_dir()


def init_layout(root: Path) -> list[str]:
    created = []
    for name in _LAYOUT:
        d = root / name
        if not d.exists():
            d.mkdir(parents=True)
            created.append(name)
    return created
