from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from vault_inbox.vault import init_layout  # noqa: E402


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    init_layout(tmp_path)
    return tmp_path


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
