# workflows/full-trading-loop.md

End-to-end live trading loop. Calls every AEGIS skill in dependency order. Stops if any gate
fails. **Reads:** OKX_* env vars, `aegis.config.json`. **Writes:** `~/.aegis/state/*`,
`~/.aegis/state/blackbox/*.jsonl`.

> ⚠️ Live broadcasts. Use `workflows/dry-run.md` first.

## Step 0 — Pre-flight (mandatory)

Run the checks in `workflows/INDEX.md` "Pre-loop checklist".

```bash
which onchainos                # must succeed
onchainos --version
onchainos wallet status        # logged in?
python skills/aegis-hibernator/scripts/drawdown.py status
```

If `status: HIBERNATED` → STOP. The kill switch is engaged; investigate the reason field
before doing anything else.

## Step 1 — Refresh decay metric

```bash
python skills/aegis-blackbox/scripts/decay.py recompute --chain solana
```

Writes `~/.aegis/state/blackbox/decay_report.json`. Sources classified `RETIRE` are excluded
from the upcoming signal window.

## Step 2 — Snapshot the signal window

```bash
python skills/aegis-fader/scripts/signal_window.py snapshot \
    --chain solana --window-minutes 60
```

This is the raw `onchainos signal list --chain solana --wallet-type 1,2,3` rollup. Read it,
note the top tokens by `signal_count`.

## Step 3 — Iterate candidates

For each token in the snapshot, run:

```bash
# 3a. Sentinel pre-flight
python skills/aegis-sentinel/scripts/fragility.py score \
    --chain solana --token <ca>

# 3b. Hibernator status
python skills/aegis-hibernator/scripts/drawdown.py status

# 3c. Quartermaster size
python skills/aegis-quartermaster/scripts/kelly.py size \
    --strategy-id aegis-fader --token <ca> --chain solana \
    --fragility <from 3a> --wallet-balance-usd <usd> \
    [--wins N --losses M --avg-win pct --avg-loss pct]

# 3d. Fader decision
python skills/aegis-fader/scripts/fade_score.py score \
    --chain solana --token <ca> \
    --signal-count <n> --source-diversity <d> --crowdedness <c> \
    --fragility <from 3a> --fragility-decision <from 3a> \
    --hibernator-status <from 3b>
```

`decision == FOLLOW_LONG` ⇒ proceed to Step 4.
`decision == FADE_OPPORTUNITY` ⇒ log only; loop continues.
`decision == SKIP` ⇒ loop continues.

## Step 4 — Quote → Simulate → Broadcast → Track

Only when Step 3 chose `FOLLOW_LONG` and Quartermaster returned `size_usd > 0`.

```bash
# 4a. Resolve from/to addresses (native SOL or wSOL per ../skills/_shared/sol-addresses.md)
onchainos token search --query <symbol> --chains solana

# 4b. Quote
onchainos swap quote \
    --from 11111111111111111111111111111111 \
    --to <ca> \
    --readable-amount <size_usd / sol_price> \
    --chain solana

# Reject if isHoneyPot=true OR priceImpactPercent > 5.0
```

```bash
# 4c. Simulate
onchainos gateway simulate \
    --from 11111111111111111111111111111111 \
    --to <ca> \
    --data <calldata-from-quote> \
    --chain solana

# Reject if divergence > 1.5%
```

```bash
# 4d. Broadcast (one-shot via swap execute, since gateway broadcast needs a pre-signed tx)
onchainos swap execute \
    --from 11111111111111111111111111111111 \
    --to <ca> \
    --readable-amount <amount> \
    --chain solana \
    --wallet <addr> \
    --gas-level fast \
    --tips 0.0005
```

Capture `swapTxHash`.

```bash
# 4e. Track
onchainos gateway orders --address <wallet> --chain solana
```

## Step 5 — Log to Blackbox

Each step above emits to `~/.aegis/state/blackbox/decisions.jsonl` via the AEGIS scripts.
`swap execute`'s tx hash is recorded in `trades.jsonl`. No separate command needed.

## Step 6 — Schedule attribution

After `fader.attribution_delay_minutes` (default 60):

```bash
onchainos market portfolio-token-pnl --address <wallet> --chains solana --token <ca>
```

Append the realized PnL pct to the matching trade row in `trades.jsonl` (`attribution.realized_pnl_pct`)
and emit one row per `source_id` to `signal_performance.jsonl`. Subsequent
`aegis-blackbox decay.py recompute` will pick these up.

## Step 7 — Drawdown re-check

```bash
python skills/aegis-hibernator/scripts/drawdown.py check \
    --wallet <addr> --chain solana
```

If the rolling realized PnL pct ≤ `-hibernator.max_rolling_drawdown_pct`, Hibernator engages.
Subsequent loop iterations will skip on `hibernated`.

## Step 8 — Open the dashboard

```bash
xdg-open skills/aegis-blackbox/scripts/dashboard.html
```

Verify every gate, every trade, every decay row landed.
