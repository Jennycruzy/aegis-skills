"""Shared utilities for AEGIS skills.

Centralises config loading, CLI invocation, atomic state writes, structured event logging, and
secret redaction. Every AEGIS script imports from here; never duplicate.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

__all__ = [
    "AegisError",
    "CliResult",
    "aegis_home",
    "append_jsonl",
    "atomic_write_json",
    "blackbox_dir",
    "emit_event",
    "load_config",
    "now_ms",
    "operation_id",
    "redact",
    "run_cli",
    "sanitize_external",
    "state_dir",
]


SCHEMA_VERSION: int = 1
GEO_BLOCK_CODES: frozenset[int] = frozenset({50125, 80001})
GEO_BLOCK_MESSAGE: str = (
    "DEX is not available in your region. Please switch to a supported region and try again."
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[0-9a-fA-F]{64}\b"),
    re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{40,}\b"),
    re.compile(r"(?i)(private[_ ]?key|mnemonic|seed|secret|passphrase)\s*[:=]\s*\S+"),
)

_CONTROL_CHARS: re.Pattern[str] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH: re.Pattern[str] = re.compile(r"[​‌‍﻿]")


class AegisError(RuntimeError):
    """Base error for AEGIS framework."""


@dataclass(frozen=True)
class CliResult:
    """Structured outcome of a single `onchainos` invocation."""

    ok: bool
    code: int | str | None
    msg: str
    data: dict[str, Any] | list[Any] | None


# ---------------------------------------------------------------------------
# Paths and time
# ---------------------------------------------------------------------------


def aegis_home() -> Path:
    return Path(os.environ.get("AEGIS_HOME", str(Path.home() / ".aegis")))


def state_dir() -> Path:
    p = aegis_home() / "state"
    p.mkdir(parents=True, exist_ok=True)
    return p


def blackbox_dir() -> Path:
    p = state_dir() / "blackbox"
    p.mkdir(parents=True, exist_ok=True)
    return p


def now_ms() -> int:
    return int(time.time() * 1000)


def operation_id(prefix: str, *parts: str | int) -> str:
    raw = "-".join([prefix, *(str(p) for p in parts)])
    return raw if raw else f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config() -> dict[str, Any]:
    override = os.environ.get("AEGIS_CONFIG")
    if override:
        path = Path(override)
    else:
        cwd_cfg = Path.cwd() / "aegis.config.json"
        example = Path(__file__).resolve().parent.parent.parent / "aegis.config.example.json"
        path = cwd_cfg if cwd_cfg.is_file() else example
    raw = path.read_text(encoding="utf-8")
    cfg: dict[str, Any] = json.loads(raw)
    version = int(cfg.get("schema_version", 0))
    if version != SCHEMA_VERSION:
        raise AegisError(
            f"unsupported config schema_version={version}; expected {SCHEMA_VERSION}",
        )
    return cfg


# ---------------------------------------------------------------------------
# Secret redaction & sanitisation
# ---------------------------------------------------------------------------


def _env_secret_values() -> list[str]:
    out: list[str] = []
    for key in ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE"):
        v = os.environ.get(key, "")
        if v:
            out.append(v)
    return out


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for value in _env_secret_values():
        if value and value in out:
            out = out.replace(value, "<redacted>")
    for pat in _SECRET_PATTERNS:
        out = pat.sub("<redacted>", out)
    return out


def sanitize_external(text: str, *, max_len: int = 200) -> str:
    """Sanitise untrusted CLI output before display.

    See skills/_shared/prompt-injection.md.
    """
    if text is None:
        return ""
    s = str(text)
    s = _CONTROL_CHARS.sub("", s)
    s = _ZERO_WIDTH.sub("·", s)
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


# ---------------------------------------------------------------------------
# Atomic state writes
# ---------------------------------------------------------------------------


def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))


def append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        sys.stderr.write(f"[aegis-blackbox] log write failed: {redact(str(exc))}\n")


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return format(obj, "f")
    raise TypeError(f"object of type {type(obj).__name__} is not JSON serialisable")


# ---------------------------------------------------------------------------
# CLI wrapper
# ---------------------------------------------------------------------------


def run_cli(args: list[str], *, timeout: int = 30, attempts: int = 3) -> CliResult:
    """Invoke the `onchainos` CLI and return a structured result.

    Implements the rules in skills/_shared/error-handling.md:
      - geo-block codes collapse to canonical message;
      - transport errors retry with exponential backoff (max `attempts`);
      - business errors do NOT retry;
      - stdout that is not JSON is a `schema` error;
      - secrets are redacted from any surface.
    """
    binary = os.environ.get("ONCHAINOS_BINARY", "onchainos")
    cmd = [binary, *args]
    delay = 1.0
    last_msg = ""
    for attempt in range(1, attempts + 1):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            last_msg = f"subprocess timeout after {timeout}s"
        except FileNotFoundError:
            return CliResult(
                ok=False,
                code="missing_cli",
                msg="onchainos CLI not found on PATH",
                data=None,
            )
        else:
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            if not stdout.strip():
                last_msg = redact(stderr.strip() or f"empty stdout, exit={proc.returncode}")
            else:
                try:
                    parsed = json.loads(stdout)
                except json.JSONDecodeError:
                    return CliResult(
                        ok=False,
                        code="schema",
                        msg=redact("stdout was not JSON"),
                        data=None,
                    )
                code = _extract_code(parsed)
                if code in GEO_BLOCK_CODES:
                    return CliResult(ok=False, code=code, msg=GEO_BLOCK_MESSAGE, data=None)
                if code is not None and code != 0:
                    msg = redact(_extract_msg(parsed))
                    return CliResult(ok=False, code=code, msg=msg, data=_extract_data(parsed))
                return CliResult(ok=True, code=0, msg="ok", data=_extract_data(parsed))
        if attempt < attempts:
            time.sleep(delay)
            delay *= 2
    return CliResult(ok=False, code="transport", msg=redact(last_msg), data=None)


def _extract_code(parsed: Any) -> int | None:
    if isinstance(parsed, dict):
        for key in ("code", "errorCode"):
            value = parsed.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _extract_msg(parsed: Any) -> str:
    if isinstance(parsed, dict):
        for key in ("msg", "message", "error", "detail"):
            value = parsed.get(key)
            if isinstance(value, str) and value:
                return value
    return "cli error"


def _extract_data(parsed: Any) -> dict[str, Any] | list[Any] | None:
    if isinstance(parsed, dict):
        if "data" in parsed:
            inner = parsed["data"]
            if isinstance(inner, (dict, list)):
                return inner
        return parsed
    if isinstance(parsed, list):
        return parsed
    return None


# ---------------------------------------------------------------------------
# Event emission to aegis-blackbox
# ---------------------------------------------------------------------------


@contextmanager
def emit_event(skill: str, event_type: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Context manager that appends a structured event to decisions.jsonl.

    Yields a mutable dict the caller can populate; on exit, writes the row even on exception.
    Failures fall back to stderr per error-handling.md.
    """
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now_ms(),
        "skill": skill,
        "event": event_type,
    }
    record.update(fields)
    try:
        yield record
    except Exception as exc:
        record.setdefault("error", redact(repr(exc)))
        append_jsonl(blackbox_dir() / "decisions.jsonl", record)
        raise
    append_jsonl(blackbox_dir() / "decisions.jsonl", record)
