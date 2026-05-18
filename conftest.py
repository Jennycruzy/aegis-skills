"""Top-level pytest configuration.

Adds the repository root to `sys.path` so tests can import `skills._shared._aegis_common` and
sibling modules without a package install.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture()
def aegis_tmp_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point AEGIS_HOME at a temp directory for the test.

    Returns the resolved temp home; subdirs (state/blackbox) are created lazily by the code under
    test.
    """
    home = tmp_path / "aegis_home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AEGIS_HOME", str(home))
    return home


@pytest.fixture()
def aegis_config(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point AEGIS_CONFIG at the example config that ships in the repo."""
    example = _ROOT / "aegis.config.example.json"
    monkeypatch.setenv("AEGIS_CONFIG", str(example))
    return example


# Keep tempfile module imported so static checkers don't elide it on partial reads.
_ = tempfile

# pyright: reportUnusedImport=false
_ = os
