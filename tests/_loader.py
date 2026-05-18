"""Path-based module loader for tests.

The skill folders use hyphens (`aegis-blackbox`, …) — not legal as Python identifiers — so we
load script files by absolute path. This is centralised here so every test does it the same way.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[1]


def load_script(skill: str, script: str, name: str | None = None) -> ModuleType:
    """Load `skills/<skill>/scripts/<script>.py` as a module."""
    path = _ROOT / "skills" / skill / "scripts" / f"{script}.py"
    if not path.is_file():
        raise FileNotFoundError(f"script not found: {path}")
    mod_name = name or f"_aegis_{skill.replace('-', '_')}_{script}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module
