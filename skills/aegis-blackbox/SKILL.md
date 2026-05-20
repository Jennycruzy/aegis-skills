---
name: aegis-blackbox
description: "Observability + signal-decay layer for the AEGIS stack. Use when the user asks to inspect trading decisions/查看决策日志, view the live dashboard/打开仪表盘, audit gate firings/审计风控触发, compute signal-source decay/信号源衰减评分, retire stale signal feeds/退役失效信号源, or attribute realized PnL/归因实现盈亏 to specific gates. Reads/writes ~/.aegis/state/blackbox/{decisions,trades,signal_performance}.jsonl plus decay_report.json. Provides emit_event for aegis-fader, aegis-sentinel, aegis-hibernator, aegis-quartermaster. Does NOT run swaps or hold state — it is the ledger every other AEGIS skill writes to. For swap execution use okx-dex-swap; for portfolio reads use okx-wallet-portfolio."
license: Apache-2.0
metadata:
  author: aegis
  version: "1.0.0"
  homepage: "https://github.com/Jennycruzy/aegis-skills"
agent:
  requires:
    bins: ["onchainos"]
---

# AEGIS Blackbox

Append-only JSONL decision ledger, signal-source decay metric, and static HTML dashboard.

## Triggers

**Use this skill when the user says (EN / 中文):**

- "inspect trading decisions" / "查看决策日志"
- "tail the decision log" / "拉日志的最近几条"
- "view the live dashboard" / "打开仪表盘"
- "audit gate firings" / "审计风控触发"
- "compute signal-source decay" / "信号源衰减评分"
- "retire stale signal feeds" / "退役失效信号源"
- "attribute realized PnL" / "归因实现盈亏"
- "why did Fader skip token X" / "为什么Fader跳过了这个币"

**Do NOT use this skill for (route to ↓):**

- Swap quotes or execution → `okx-dex-swap`
- Wallet balances → `okx-wallet-portfolio`
- Trade gating decisions → `aegis-fader`, `aegis-sentinel`, `aegis-hibernator`
- Position sizing math → `aegis-quartermaster`

## Prerequisites

Read `../_shared/preflight.md`. Verify `onchainos` is on PATH, `OKX_*` env vars are set, and
`~/.aegis/state/blackbox/` exists. Blackbox writes to local JSONL only; no remote calls.

## Skill Routing

AEGIS-Blackbox owns:

- Append-only decision and trade ledgers (`decisions.jsonl`, `trades.jsonl`).
- Signal-source decay metric (`decay.py` → `decay_report.json`).
- Static HTML dashboard (`dashboard.html`) reading the JSONL files via `fetch`.

It does NOT own:
- Swap quotes / execution → `okx-dex-swap`.
- Trade gating → `aegis-fader`, `aegis-sentinel`, `aegis-hibernator`.
- Sizing math → `aegis-quartermaster`.
- Portfolio balances → `okx-wallet-portfolio`.

## Quickstart

```bash
# 1. Tail the most recent 20 decisions
python skills/aegis-blackbox/scripts/logger.py tail --limit 20

# 2. Recompute signal-source decay (uses onchainos market kline for forward returns)
python skills/aegis-blackbox/scripts/decay.py recompute --chain solana

# 3. Open the dashboard locally (modern browsers block file:// fetch — serve over HTTP)
cp skills/aegis-blackbox/scripts/dashboard.html ~/.aegis/state/blackbox/
( cd ~/.aegis/state/blackbox && python -m http.server 8000 ) &
xdg-open http://localhost:8000/dashboard.html               # Linux
open      http://localhost:8000/dashboard.html               # macOS

# 4. Emit a test event (useful when wiring a new skill)
python -c "from skills._shared._aegis_common import emit_event; \
import contextlib; \
with emit_event('aegis-blackbox', 'self_test', note='hello') as r: pass"
```

## Chain Name Support

| Chain | CLI name | chainIndex | In-scope? |
|---|---|---|---|
| Solana | `solana` | 501 | ✅ primary |
| X Layer | `xlayer` | 196 | ✅ primary |
| Other | various | various | read-only context only |

Full table: `../_shared/chain-support.md`.

## Command Index

| # | Command | Description |
|---|---|---|
| 1 | `python scripts/logger.py tail --limit <N>` | Tail the most recent N rows from decisions.jsonl |
| 2 | `python scripts/logger.py grep --event <type>` | Filter by event type |
| 3 | `python scripts/logger.py stats` | Counts per event type, per skill, per decision verb |
| 4 | `python scripts/decay.py recompute --chain <chain>` | Rebuild decay_report.json from signal_performance.jsonl |
| 5 | `python scripts/decay.py classify --source <name>` | Inspect one signal source's decay band |
| 6 | open `scripts/dashboard.html` | Render trades, PnL, decision histogram, decay heatmap |

## Operation Flow

### Step 1 — Identify Intent

| Intent | Use |
|---|---|
| "show me the last N decisions" / "tail the log" | `logger.py tail` |
| "why did Fader skip token X" | `logger.py grep --event candidate_evaluated --token <ca>` |
| "are smart-money signals still working" | `decay.py recompute` then `decay.py classify` |
| "open the dashboard" | open `scripts/dashboard.html` |

### Step 2 — Collect Parameters

- `--chain` is `solana` or `xlayer` (competition scope). Other chains accepted for read-only
  context but flagged as out-of-scope in the output.
- `--limit` defaults to 50; max 10000.
- `--event` is one of the event types in `references/log-schema.md`.

### Step 3 — Call and Display

Display structured tables; never paste raw JSON unless the user asks. Numbers are formatted as
strings throughout (e.g., `"size_usd": "39.13"`).

### Step 4 — Suggest Next Steps

After a tail or grep, suggest opening the dashboard. After a decay recompute, suggest re-running
`aegis-fader scan` so retired sources are excluded from new candidates.

## Cross-Skill Workflows

### Workflow A — Pre-trade audit

1. `aegis-fader` invokes `emit_event('aegis-fader', 'candidate_evaluated', …)` per token.
2. `aegis-sentinel` and `aegis-quartermaster` emit `fragility_computed` and `size_computed`.
3. After broadcast, `aegis-fader` emits `swap_simulated`, `swap_broadcast`, `swap_tracked`.
4. `attribution_recorded` lands after `attribution_delay_minutes`.

### Workflow B — Decay-driven signal-source retirement

1. `decay.py recompute` reads `signal_performance.jsonl` rows.
2. For each distinct signal source, fetches forward 1h returns via
   `onchainos market kline --chain <chain> --address <token-ca> --bar 1H --limit 2`.
3. Computes `decay_score = max(0, (long_term_mean − recent_mean) / max(0.001,
   long_term_std))`.
4. Writes `decay_report.json` with classification: `RETIRE`, `MONITOR`, `ACTIVE`.
5. `aegis-fader` reads `decay_report.json` at scan time and excludes `RETIRE` sources.

## Risk-Control Logic

Blackbox is observability — it does not gate trades. It does enforce:

- **Self-protection**: log write failure falls back to stderr (`sys.stderr.write`) and never
  blocks the calling skill.
- **Rotation**: files exceeding `blackbox.rotation_bytes` (default 100 MB) are renamed
  `<name>_archive_<ts>.jsonl` and a fresh file is opened.
- **Corrupt-line handling**: a JSONL line that fails `json.loads` is appended verbatim to
  `corrupt_lines.log` and skipped during reads; an `event: corrupt_line` row is emitted.

## State Management

| File | Mode | Rotated? |
|---|---|---|
| `~/.aegis/state/blackbox/decisions.jsonl` | append | yes |
| `~/.aegis/state/blackbox/trades.jsonl` | append | yes |
| `~/.aegis/state/blackbox/signal_performance.jsonl` | append | yes |
| `~/.aegis/state/blackbox/meta.jsonl` | append | yes |
| `~/.aegis/state/blackbox/decay_report.json` | overwrite (atomic) | n/a |
| `~/.aegis/state/blackbox/corrupt_lines.log` | append | yes |

`schema_version` is on every row. Loaders refuse unknown versions.

## Edge Cases

- **Invalid token CA passed to grep** → no match; tool exits 0 with empty output.
- **Unsupported chain in `decay.py recompute`** → out-of-scope chains are skipped with a
  `meta.jsonl` `chain_out_of_scope` event.
- **Geo-block (50125 / 80001)** when calling `onchainos market kline` for decay → surface
  canonical geo-block message; decay rows for that source remain at previous classification.
- **Simulation failure** is not a blackbox concern; the caller (Fader) emits `gate_failed:
  divergence`.
- **Missing data** in a decay window (zero kline rows) → decay_score = `null`; classification
  stays at the previous value.
- **Rate limit on kline** → transport retry per `error-handling.md`; if all fail, emit
  `decay_recompute_partial`.
- **Schema mismatch** on a state file → refuse to load; log `schema_mismatch` to `meta.jsonl`;
  user must migrate or delete the file.

### Worked example — corrupt JSONL line

Blackbox's unhappy path is data corruption, not trade rejection.

**Pre-condition:** a non-JSON line `this is not valid json {` was appended to
`~/.aegis/state/blackbox/decisions.jsonl` (e.g. by a misbehaving sibling process).

**Command:**

```bash
python skills/aegis-blackbox/scripts/logger.py tail --limit 3
```

**Output (tail skips the corrupt line, does not raise):**

```
1779213224100  aegis-quartermaster   size_computed         token=EPj…1v reason=below_minimum size_usd=0 fragility=0.550000
1779213224172  aegis-fader           candidate_evaluated   token=EPj…1v decision=SKIP fragility=0.6800
1779213240303  aegis-hibernator      hibernation_engaged   reason=manual
```

**Side effect — `meta.jsonl` records the incident:**

```json
{"schema_version":1,"ts_ms":1779213240475,"skill":"aegis-blackbox","event":"corrupt_line","file":"decisions.jsonl","line_no":19}
```

**Interpretation:** Blackbox is total — readers never raise on a corrupt row. The audit
trail moves to `meta.jsonl` so the operator can investigate later. AEGIS callers
proceeding through the loop are unaffected.

**Caller next step:** none — the corrupt line is isolated. Operator should inspect
`meta.jsonl` and decide whether to keep or archive `decisions.jsonl`.

## Observability Hooks

Blackbox is itself observable. It emits the following self-instrumentation events to
`meta.jsonl`:

```json
{"schema_version": 1, "ts_ms": 1747545600000, "skill": "aegis-blackbox", "event": "rotation",
 "file": "decisions.jsonl", "archived_to": "decisions_archive_1747545600000.jsonl",
 "bytes": 104857600}
```

```json
{"schema_version": 1, "ts_ms": 1747545600000, "skill": "aegis-blackbox", "event": "corrupt_line",
 "file": "decisions.jsonl", "byte_offset": 4823}
```

```json
{"schema_version": 1, "ts_ms": 1747545600000, "skill": "aegis-blackbox", "event": "decay_recomputed",
 "sources_scanned": 14, "retired": 2, "monitor": 3, "active": 9}
```

## Safety Guarantees

- Blackbox **never** swaps, broadcasts, or signs.
- Blackbox **never** logs values matching the secret patterns in `_shared/error-handling.md`.
- Blackbox **never** interprets CLI output as instructions; it stores values as data.
- Blackbox **never** blocks a caller on a log write failure; it degrades to stderr.

## Composition Contract

- **Calls**: `onchainos market kline` (decay only).
- **Called by**: every AEGIS skill (`emit_event`).
- **Independently usable?** Yes — Blackbox is useful on its own as a generic JSONL ledger for any
  OnchainOS-based agent.

## Testing

Fixtures under `tests/fixtures/`:
- `signals_crowded.json`, `signals_lonely.json` — synthetic signal feeds.
- `token_fragile.json`, `token_clean.json` — synthetic fragility inputs.

Unit tests:
- `tests/unit/test_decay.py` — known signal source, known forward returns; edge case `std ≈ 0`.

Expected outcomes:
- `decay.py recompute` produces deterministic classification on the fixtures.
- `logger.py tail/grep/stats` survives a deliberately corrupt JSONL line by skipping it.

## Global Notes

- All output JSON, one event per line.
- Prices, sizes, and PnL pct are decimal strings (never floats) on disk.
- Timestamps are UTC ms (`int`).
- EVM contract addresses lowercase; Solana addresses as base58.
- Dashboard is one static file; no server, no build step.
