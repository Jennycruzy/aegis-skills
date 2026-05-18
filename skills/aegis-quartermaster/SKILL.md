---
name: aegis-quartermaster
description: "Position sizing for the AEGIS stack via Bayesian-shrunk fractional Kelly. Use when the user asks 'how much should I size this trade'/'仓位多少', 'compute Kelly bet', 'shrink win-rate prior', 'cap by fragility'/'按脆弱度缩仓', 'cap by wallet'/'按钱包总额限制', or 'show binding constraint'/'哪一道闸门生效了'. Reads aegis-blackbox trades.jsonl for hit-rate + payoff history; reads aegis-sentinel fragility; reads okx-wallet-portfolio for wallet balance. Pure math — never calls swap execute. Always emits binding_constraint so judges can audit. For risk gating use aegis-sentinel; for kill switch use aegis-hibernator; for execution use okx-dex-swap; for portfolio balance reads use okx-wallet-portfolio."
license: Apache-2.0
metadata:
  author: aegis
  version: "1.0.0"
  homepage: "https://github.com/aegis/aegis-skills"
agent:
  requires:
    bins: ["onchainos"]
---

# AEGIS Quartermaster

Bayesian-shrunk fractional Kelly with wallet, fragility, and minimum-size caps.

## Prerequisites

Read `../_shared/preflight.md`. Quartermaster is pure math; the only CLI call is
`onchainos portfolio total-value` to fetch wallet balance.

## Skill Routing

AEGIS-Quartermaster owns:
- Per-trade dollar sizing for `aegis-fader`.
- Hit-rate + payoff aggregation from `aegis-blackbox` `trades.jsonl`.
- Bayesian shrinkage with `α=1`, `β=4` priors.
- Fragility-curve attenuation.
- Wallet, daily-entry, and minimum-position caps.

It does NOT own:
- Trade gating → `aegis-sentinel`, `aegis-hibernator`.
- Strategy decisions → `aegis-fader`.
- Execution → `okx-dex-swap`.

## Quickstart

```bash
# 1. Size the next aegis-fader entry on a token with fragility 0.22, wallet $5000
python skills/aegis-quartermaster/scripts/kelly.py size \
    --strategy-id aegis-fader --token <ca> --chain solana \
    --fragility 0.22 --wallet-balance-usd 5000.00

# 2. Inspect history for a given strategy
python skills/aegis-quartermaster/scripts/kelly.py history --strategy-id aegis-fader

# 3. Dry-run with explicit win/loss counts (bypasses trades.jsonl)
python skills/aegis-quartermaster/scripts/kelly.py size \
    --strategy-id aegis-fader --token <ca> --chain solana \
    --fragility 0.22 --wallet-balance-usd 5000.00 \
    --wins 8 --losses 5 --avg-win 0.12 --avg-loss 0.06
```

## Chain Name Support

| Chain | CLI name | chainIndex | In-scope? |
|---|---|---|---|
| Solana | `solana` | 501 | ✅ primary |
| X Layer | `xlayer` | 196 | ✅ primary |

Full table: `../_shared/chain-support.md`.

## Command Index

| # | Command | Description |
|---|---|---|
| 1 | `kelly.py size --strategy-id … --token … --chain … --fragility … --wallet-balance-usd …` | Compute size + binding constraint for one candidate |
| 2 | `kelly.py history --strategy-id …` | Show win count, loss count, avg-win, avg-loss as seen in trades.jsonl |
| 3 | `kelly.py from-portfolio --strategy-id … --token … --chain …` | As `size`, but pulls wallet balance from `onchainos portfolio total-value` |

## Operation Flow

### Step 1 — Identify Intent

Quartermaster is invoked by `aegis-fader` after `aegis-sentinel` returns `ALLOW` or
`SIZE_DOWN`. The caller passes `--fragility` and either `--wallet-balance-usd` or wires the
`from-portfolio` variant.

### Step 2 — Collect Parameters

| Parameter | Source |
|---|---|
| Hit rate, payoff ratio | `aegis-blackbox` `trades.jsonl` rows where `decision_id` starts with `<strategy_id>-` and `attribution.realized_pnl_pct` is non-null |
| Fragility | `aegis-sentinel` |
| Wallet balance | `--wallet-balance-usd` flag or `onchainos portfolio total-value --address <wallet> --chains <chain>` |
| Config thresholds | `aegis.config.json` → `quartermaster` |

### Step 3 — Call and Display

The script prints a JSON object with every intermediate value:

```json
{
  "schema_version": 1,
  "ts_ms": 1747545600000,
  "strategy_id": "aegis-fader",
  "wins": 8, "losses": 5,
  "hit_rate_shrunk": "0.500",
  "payoff_ratio": "2.000",
  "kelly_full": "0.250",
  "kelly_use": "0.0625",
  "fragility": "0.22",
  "fragility_multiplier": "0.776",
  "wallet_balance_usd": "5000.00",
  "size_usd": "242.50",
  "binding_constraint": "fragility_curve",
  "reason": "ok"
}
```

### Step 4 — Suggest Next Steps

If `size_usd` is `"0"`, the caller should mark `SKIP` with `reason ∈ {negative_edge,
below_minimum}` and emit `gate_failed: size_zero` to Blackbox. Otherwise proceed with the
quote → simulate → broadcast flow in `aegis-fader`.

## Cross-Skill Workflows

### Workflow A — Fader entry sizing

1. `aegis-fader` calls `aegis-sentinel` → fragility.
2. If `decision != BLOCK`, `aegis-fader` calls `aegis-quartermaster size` with fragility.
3. If `size_usd > 0`, `aegis-fader` proceeds to quote / simulate / broadcast.
4. `aegis-quartermaster` emits `size_computed` to `aegis-blackbox`.

### Workflow B — Backtesting hit-rate drift

1. `kelly.py history --strategy-id aegis-fader` summarises wins / losses.
2. Operator compares to `decay_report.json` to see if signal-source drift explains a falling
   hit rate.

## Risk-Control Logic

```
wins, losses, avg_win, avg_loss = aggregate(trades.jsonl, strategy_id)
hit_rate_shrunk = (wins + α) / (wins + losses + α + β)            # α=1, β=4 by default
payoff_ratio    = clamp(avg_win / |avg_loss|, 0.1, 10.0)
kelly_full      = hit_rate_shrunk - (1 - hit_rate_shrunk) / payoff_ratio
if kelly_full <= 0: return size=0, reason="negative_edge"
kelly_use       = max(0, kelly_full) * kelly_fraction              # default 0.25
size_wallet_cap = min(kelly_use, max_position_pct) * wallet_balance
size_after_frag = size_wallet_cap * fragility_curve(fragility)
if size_after_frag < min_position_usd: return size=0, reason="below_minimum"
size_usd        = size_after_frag
```

`fragility_curve`: piecewise linear, **1.0 at 0.0**, **0.2 at 0.5**, **0 above 0.5**.
Configurable in `quartermaster.fragility_curve`.

`binding_constraint` is the **first** cap that bound the result:
`negative_edge` → `kelly_fraction` → `wallet_cap` → `fragility_curve` → `min_position` →
`ok`. Logged on every size computation.

## State Management

Quartermaster is stateless on disk. It reads `aegis-blackbox/trades.jsonl` for history and
writes its `size_computed` event back. No `quartermaster.json` state file exists.

## Edge Cases

- **Empty history (0 wins, 0 losses)** → `hit_rate_shrunk = α/(α+β) = 0.2`; `payoff_ratio
  default = 1.0`; `kelly_full = 0.2 − 0.8/1 = −0.6` → returns `size=0`,
  `reason=negative_edge`. Operator must seed history with at least one realized win before
  Quartermaster will size.
- **All-loss history** → `kelly_full ≤ 0` → `size=0`, `reason=negative_edge`.
- **Single-win history** → `payoff_ratio` is clamped to `[0.1, 10.0]`; sizes conservatively.
- **High fragility (≥ 0.5)** → `fragility_multiplier = 0`; `size=0`,
  `binding_constraint=fragility_curve`.
- **Low balance** → `wallet_cap` bites first; `binding_constraint=wallet_cap`.
- **Geo-block on `portfolio total-value`** (when using `from-portfolio`) → canonical message;
  `size=0`, `reason=portfolio_unavailable`.
- **Negative `avg_loss`** signs are taken absolute in the formula.
- **Schema mismatch** on `trades.jsonl` → refuse to read; surface error; do not size.

## Observability Hooks

Emits `size_computed` to `~/.aegis/state/blackbox/decisions.jsonl`:

```json
{"schema_version": 1, "ts_ms": 1747545600000, "skill": "aegis-quartermaster",
 "event": "size_computed", "strategy_id": "aegis-fader",
 "token": "<ca>", "chain": "solana", "wallet_balance_usd": "5000.00",
 "hit_rate_shrunk": "0.41", "payoff_ratio": "1.83", "kelly_full": "0.087",
 "size_usd": "39.13", "binding_constraint": "fragility_curve"}
```

## Safety Guarantees

- Never returns a size larger than `max_position_pct × wallet_balance`.
- Never sizes when `hit_rate_shrunk × payoff_ratio − (1 − hit_rate_shrunk) ≤ 0`.
- Never trusts a CLI-supplied wallet balance: when in doubt, requires `--wallet-balance-usd`
  explicitly.
- Never uses floats for the final dollar size (Decimal throughout).

## Composition Contract

- **Calls**: optionally `onchainos portfolio total-value` (only `from-portfolio`).
- **Called by**: `aegis-fader` per candidate.
- **Independently usable?** Yes — emits the same JSON shape for any external strategy that
  feeds wins/losses.

## Testing

Fixtures: none required (synthetic inputs in the test file).

Unit tests:
- `tests/unit/test_kelly.py` — zero history, all-loss, single-win, high-fragility,
  low-balance, negative-edge, exact `binding_constraint` selection.

## Global Notes

- All output JSON.
- All money / pct values are decimal strings on disk; `Decimal` in code.
- Timestamps UTC ms.
- Hit-rate / payoff inputs are sourced only from rows where
  `attribution.realized_pnl_pct` is non-null (realized only; competition rule).
