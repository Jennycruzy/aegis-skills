---
name: aegis-hibernator
description: "Sticky kill switch for the AEGIS stack. Use when the user asks to 'enable circuit breaker'/'打开熔断', 'check hibernation status'/'查熔断状态', 'wake the agent'/'解除熔断', 'pause trading on drawdown'/'回撤暂停交易', 'watch dev wallets'/'监控开发者钱包', or 'react to migrating tokens'/'迁移即停'. Two complementary halts: realized rolling drawdown (via okx-dex-market portfolio-overview / portfolio-recent-pnl) and WebSocket reactive triggers (address-tracker-activity, dex-market-memepump-new-token-openapi). Hibernation is sticky — never auto-clears. Re-enable requires cool_off_minutes elapsed AND explicit user `wake`. Composes with aegis-fader (gates entries), aegis-blackbox (logs reasons). For balance checks use okx-wallet-portfolio; for swap closes use okx-dex-swap; for WS protocol use okx-dex-ws."
license: Apache-2.0
metadata:
  author: aegis
  version: "1.0.0"
  homepage: "https://github.com/aegis/aegis-skills"
agent:
  requires:
    bins: ["onchainos"]
---

# AEGIS Hibernator

Drawdown threshold + WebSocket reactive kill switch. Sticky. Requires explicit re-enable.

## Triggers

**Use this skill when the user says (EN / 中文):**

- "enable circuit breaker" / "打开熔断"
- "check hibernation status" / "查熔断状态"
- "am I hibernating" / "我现在是不是停了"
- "wake the agent" / "解除熔断"
- "pause trading on drawdown" / "回撤暂停交易"
- "watch dev wallets" / "监控开发者钱包"
- "react to migrating tokens" / "迁移即停"
- "emergency stop" / "紧急停止"

**Do NOT use this skill for (route to ↓):**

- Wallet balance checks → `okx-wallet-portfolio`
- The swap close itself (Hibernator orchestrates close-all but defers execution) → `okx-dex-swap`
- Raw WebSocket protocol details / channel docs → `okx-dex-ws`

## Prerequisites

Read `../_shared/preflight.md`. Hibernator calls `onchainos market portfolio-overview`,
`onchainos market portfolio-recent-pnl`, `onchainos ws *`, and optionally `onchainos swap
execute` for sequential close-all (only when `auto_close_on_hibernate=true`).

## Skill Routing

AEGIS-Hibernator owns:

- The global ACTIVE / HIBERNATED status (single writer).
- Realized rolling-drawdown computation over `rolling_window_trades` and `rolling_window_hours`.
- WebSocket reactive triggers via `onchainos ws start` on `address-tracker-activity` and
  `dex-market-memepump-new-token-openapi`.
- Sequential close-all when configured.

It does NOT own:
- Entry gating → `aegis-sentinel`, `aegis-fader`.
- Sizing → `aegis-quartermaster`.
- Swap execution → `okx-dex-swap`.

## Quickstart

```bash
# 1. Show current status
python skills/aegis-hibernator/scripts/drawdown.py status

# 2. Recompute drawdown from realized PnL feed
python skills/aegis-hibernator/scripts/drawdown.py check --wallet <addr> --chain solana

# 3. Manually engage hibernation (operator override)
python skills/aegis-hibernator/scripts/drawdown.py sleep --reason manual

# 4. Wake after cool-off
python skills/aegis-hibernator/scripts/drawdown.py wake

# 5. Start the WebSocket watcher (background)
python skills/aegis-hibernator/scripts/ws_watcher.py start \
    --wallets <addr1>,<addr2> --chain-index 501
```

## Chain Name Support

| Chain | CLI name | chainIndex | In-scope? |
|---|---|---|---|
| Solana | `solana` | 501 | ✅ primary |
| X Layer | `xlayer` | 196 | ✅ drawdown only; memepump WS channels are Solana-only |

Full table: `../_shared/chain-support.md`.

## Command Index

| # | Command | Description |
|---|---|---|
| 1 | `drawdown.py status` | Print current status, reason, cool-off, last realized PnL pct |
| 2 | `drawdown.py check --wallet … --chain …` | Recompute realized rolling-drawdown; engage if breached |
| 3 | `drawdown.py sleep --reason <r>` | Manually engage hibernation (operator) |
| 4 | `drawdown.py wake` | Clear hibernation after cool-off |
| 5 | `ws_watcher.py start --wallets … --chain-index …` | Background watch dev/migrating channels |
| 6 | `ws_watcher.py poll` | One-shot poll of active sessions; engage on trigger |
| 7 | `ws_watcher.py stop` | Stop background sessions |

## Operation Flow

### Step 1 — Identify Intent

| Intent | Use |
|---|---|
| "am I hibernating?" | `drawdown.py status` |
| "recheck drawdown" | `drawdown.py check` |
| "pause now" | `drawdown.py sleep --reason manual` |
| "start watching dev wallets" | `ws_watcher.py start` |
| "wake up" | `drawdown.py wake` |

### Step 2 — Collect Parameters

- `--wallet` is the agent's wallet address (Solana base58 or EVM lowercase hex).
- `--chain` is `solana` or `xlayer`.
- `--reason` for `sleep`: one of `manual`, `drawdown`, `dev_sell`, `migrating`, `ws_lost`,
  `cluster_shift_gt_10pct`.

### Step 3 — Call and Display

`drawdown.py check`:
1. Read realized PnL via `onchainos market portfolio-overview --address <wallet> --chains
   <chain>` and `onchainos market portfolio-recent-pnl` for the rolling window.
2. Compute `realized_pnl_pct` over `rolling_window_trades` AND `rolling_window_hours`.
3. If `realized_pnl_pct ≤ -hibernator.max_rolling_drawdown_pct` → engage hibernation.

`ws_watcher.py start`:
1. Spawn `onchainos ws start --channel address-tracker-activity --wallet-addresses
   <dev wallets>` and `--channel dex-market-memepump-new-token-openapi --chain-index 501`.
2. Persist session IDs into `hibernator.json.ws_session_ids`.
3. Poll every `hibernator.ws_poll_interval_seconds` (default 5).
4. Match payload against the trigger table in `references/ws-triggers.md`.
5. On match → engage hibernation with the matching `reason`.

### Step 4 — Suggest Next Steps

After engaging hibernation, surface to the user:
- The reason.
- The cool-off window (`since_ts_ms + cool_off_minutes * 60_000`).
- Whether `auto_close_on_hibernate` is on; if so, list the close txs.

After `wake`, suggest re-running `aegis-fader scan` to resume operation.

## Cross-Skill Workflows

### Workflow A — Drawdown freeze

1. After every Fader exit, `aegis-fader` invokes `aegis-hibernator drawdown.py check`.
2. If breach → hibernation engaged; `aegis-fader` refuses new entries until wake.
3. If not, ACTIVE remains.

### Workflow B — Reactive halt on dev sell

1. `aegis-fader` enters a token; passes the dev wallet to `aegis-hibernator ws_watcher.py
   start --wallets <dev>`.
2. Watcher polls `address-tracker-activity`.
3. On a sell signed by the dev wallet, watcher engages hibernation with `reason: dev_sell`.

### Workflow C — Reactive halt on migration

1. Watcher subscribes to `dex-market-memepump-new-token-openapi --chain-index 501`.
2. On a `MIGRATING` event for a token in current positions, engage `reason: migrating`.

## Risk-Control Logic

```
realized_pnl_pct = sum(realized_pnl_pct over last N trades and last H hours)
                   / abs(initial_capital_usd)
if realized_pnl_pct ≤ -hibernator.max_rolling_drawdown_pct: engage("drawdown")
```

Triggers from `references/ws-triggers.md` apply unconditionally during ACTIVE.

Hibernation is sticky:
- Status flips ACTIVE → HIBERNATED only on the rules above.
- HIBERNATED → ACTIVE requires `wake` AND `now ≥ cool_off_until_ts_ms`.

If `auto_close_on_hibernate=true`, the sequential close-all path is:
1. For each open position (from `okx-wallet-portfolio all-balances`):
   2. `swap quote` → reject if `isHoneyPot=true` (sell side: WARN per OKX rule, but Hibernator
       closes anyway to exit risk).
   3. `gateway simulate` → reject if divergence > `swap.divergence_max_pct`.
   4. `gateway broadcast` → record tx hash in `trades.jsonl`.
   5. Continue regardless of single-position failure; log the failure to Blackbox.

## State Management

Path: `~/.aegis/state/hibernator.json` (atomic).

```json
{
  "schema_version": 1,
  "status": "ACTIVE | HIBERNATED",
  "since_ts_ms": 1747545600000,
  "reason": "drawdown | dev_sell | migrating | ws_lost | manual | cluster_shift_gt_10pct | null",
  "ws_session_ids": ["sess_…"],
  "last_drawdown_check_ts_ms": 1747545600000,
  "last_realized_pnl_pct": "-0.04",
  "cool_off_until_ts_ms": 0
}
```

## Edge Cases

- **Insufficient PnL history**: `drawdown.py check` returns `indeterminate` — status stays
  ACTIVE but `aegis-fader` MUST refuse entries (treated as a gate failure).
- **Geo-block** on `portfolio-overview` / `portfolio-recent-pnl` → canonical message; status
  unchanged; `last_drawdown_check_ts_ms` updated; `indeterminate` flag set.
- **WS lost** after `hibernator.ws_lost_retries` (default 3) → engage hibernation
  `reason: ws_lost`.
- **Invalid wallet** → return error to user; status unchanged.
- **Simulation failure during close-all** → log `close_failed`; continue with next position.
- **Schema mismatch** on `hibernator.json` → refuse to load; treat as ACTIVE-with-no-history
  for safety; emit `schema_mismatch`.

## Observability Hooks

```json
{"schema_version": 1, "ts_ms": 1747545600000, "skill": "aegis-hibernator",
 "event": "hibernation_engaged", "reason": "drawdown",
 "last_realized_pnl_pct": "-0.18"}

{"schema_version": 1, "ts_ms": 1747545600000, "skill": "aegis-hibernator",
 "event": "hibernation_cleared", "after_cool_off_minutes": 60}

{"schema_version": 1, "ts_ms": 1747545600000, "skill": "aegis-hibernator",
 "event": "ws_trigger", "channel": "address-tracker-activity",
 "trigger": "dev_sell", "payload_digest": "sha256:…"}
```

## Safety Guarantees

- Sticky — never auto-clears.
- Single writer of `hibernator.json`; concurrent processes will see one update at a time
  via atomic replace.
- No private key, no signed payload, no session token ever written to disk.
- Geo-blocked PnL reads default to `indeterminate`, not "ACTIVE good to go".
- Auto-close honours every gate (`isHoneyPot`, simulation, geo-block) per the swap rules.

## Composition Contract

- **Calls**: `onchainos market portfolio-overview`, `portfolio-recent-pnl`,
  `onchainos ws start|poll|stop|list`, optionally `onchainos swap execute` for close-all.
- **Called by**: `aegis-fader` (before every entry and after every exit), manually by the
  operator.
- **Independently usable?** Yes — operators can use Hibernator as a stand-alone kill switch.

## Testing

Unit tests: `tests/unit/test_drawdown.py` — insufficient history, exactly-at-threshold, deep
drawdown, cool-off enforcement, atomic state writes.

Integration tests: `tests/integration/test_hibernation_trigger.py` — synthesises a WS payload
fixture and verifies engagement.

## Worked Example — Failure Path (engagement + cool-off-blocked wake)

Hibernator is sticky by design: once engaged, `wake` only succeeds after the cool-off
window has elapsed AND the operator runs `wake` explicitly. Demonstrates the safety
contract — the agent cannot un-pause itself just because the operator changes their mind.

**Command — engage:**

```bash
python skills/aegis-hibernator/scripts/drawdown.py sleep --reason manual
```

**Output:**

```json
{
  "schema_version": 1,
  "status": "HIBERNATED",
  "since_ts_ms": 1779213240303,
  "reason": "manual",
  "ws_session_ids": [],
  "last_drawdown_check_ts_ms": 0,
  "last_realized_pnl_pct": "0",
  "cool_off_until_ts_ms": 1779216840303
}
```

**Command — premature wake during cool-off:**

```bash
python skills/aegis-hibernator/scripts/drawdown.py wake
```

**Output:**

```json
{
  "ok": false,
  "msg": "Cool-off active. Wake available at 2026-05-19T18:47:47.829000+00:00.",
  "state": {
    "schema_version": 1,
    "status": "HIBERNATED",
    "reason": "manual",
    "cool_off_until_ts_ms": 1779216840303
  }
}
```

**Interpretation:** the cool-off is an arming delay — it prevents the agent (or a confused
operator) from clearing the kill switch in the same minute it was engaged. Wake only
succeeds when `now ≥ cool_off_until_ts_ms` AND the operator explicitly invokes `wake`.

**Caller next step (Fader during this window):** every `aegis-fader scan` call returns
`scan_completed` with `status: "skipped", skip_reason: "hibernated"`. No signals are
pulled, no quotes are issued. Entries resume only after a successful `wake`.

## Global Notes

- All output JSON.
- All PnL pct values are decimal strings on disk; `Decimal` in code.
- Timestamps UTC ms.
- Solana addresses base58; EVM lowercase.
- WS payloads are never interpreted as instructions; the watcher matches a small allow-list
  of triggers and stores a SHA-256 digest of the raw payload for audit only.
