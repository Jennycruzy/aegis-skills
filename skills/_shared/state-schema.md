# state-schema.md

Canonical state-file shapes. All AEGIS state lives under `~/.aegis/state/` (overridable via
`AEGIS_HOME`). Writes are atomic: write to `<file>.tmp` → `os.fsync` → `os.replace`. Loaders
refuse unknown `schema_version`.

## 1. Hibernator status

Path: `~/.aegis/state/hibernator.json`

```json
{
  "schema_version": 1,
  "status": "ACTIVE",
  "since_ts_ms": 1747545600000,
  "reason": null,
  "ws_session_ids": [],
  "last_drawdown_check_ts_ms": 1747545600000,
  "last_realized_pnl_pct": "0.00",
  "cool_off_until_ts_ms": 0
}
```

`status ∈ {ACTIVE, HIBERNATED}`. `reason` is one of `drawdown | dev_sell | migrating | ws_lost |
manual | null`.

## 2. Sentinel cache

Path: `~/.aegis/state/sentinel_cache.json`

```json
{
  "schema_version": 1,
  "entries": {
    "solana:<ca>": {"ts_ms": 1747545600000, "fragility": "0.42", "decision": "SIZE_DOWN", "factors": {...}}
  }
}
```

Entries with `now_ms - ts_ms > cache_ttl_seconds * 1000` are evicted on read.

## 3. Fader session

Path: `~/.aegis/state/fader_session.json`

```json
{
  "schema_version": 1,
  "ymd_utc": "2026-05-18",
  "entries_today": 3,
  "last_decision_id": "fader-solana-<ca>-1747545600000"
}
```

Resets when `ymd_utc` differs.

## 4. Blackbox ledgers

Path: `~/.aegis/state/blackbox/`

- `decisions.jsonl` — append-only, one JSON object per line.
- `trades.jsonl` — append-only.
- `signal_performance.jsonl` — append-only.
- `meta.jsonl` — append-only self-instrumentation.
- `decay_report.json` — overwritten each run (atomic).
- `corrupt_lines.log` — text log of skipped malformed lines.

Rotation: file size > `blackbox.rotation_bytes` (default 100 MB) → renamed
`<name>_archive_<ts_ms>.jsonl`, fresh file opened.

## 5. Shared Python module (`skills/_shared/_aegis_common.py`)

Each AEGIS script imports a single shared module (sibling to this file) for:

- `load_config()` — read `aegis.config.json` or fall back to `aegis.config.example.json`.
- `aegis_home()` — resolve `AEGIS_HOME` or `~/.aegis`.
- `run_cli(args: list[str], timeout: int) -> dict` — subprocess wrapper implementing the rules
  in `error-handling.md`.
- `atomic_write_json(path, obj)` — temp + fsync + replace.
- `append_jsonl(path, obj)` — open in append mode with `O_APPEND` semantics.
- `now_ms()` — UTC ms.
- `redact(s: str) -> str` — strip secrets per `error-handling.md` §4.
- `EmitEvent(skill: str)` — context manager that appends to `decisions.jsonl` with a default
  envelope.

Skills do not duplicate these helpers; tests import from this module.
