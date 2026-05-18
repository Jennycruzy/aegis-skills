# workflows/safe-shutdown.md

Hard exit. Closes positions (optionally), stops WS sessions, engages hibernation.

## Step 1 — Engage hibernation manually

```bash
python skills/aegis-hibernator/scripts/drawdown.py sleep --reason manual
```

This flips status to HIBERNATED with `reason: manual` and starts the cool-off countdown
(`cool_off_minutes`, default 60). `aegis-fader` will refuse new entries immediately.

## Step 2 — Close open positions (if `auto_close_on_hibernate=false`)

If `auto_close_on_hibernate=true`, Step 1 already did this sequentially.

Otherwise, list open positions and close each manually:

```bash
onchainos wallet balance --all
```

For each non-stable holding the operator wants out of:

```bash
onchainos swap quote --from <ca> --to <USDC> --readable-amount <holdings> --chain solana
onchainos gateway simulate --from <ca> --to <USDC> --data <calldata> --chain solana
onchainos swap execute --from <ca> --to <USDC> --readable-amount <holdings> --chain solana \
    --wallet <addr> --gas-level fast --tips 0.0005
```

Honeypot WARN on sell: per OKX rules, selling is allowed for stop-loss; proceed if the
operator explicitly confirms.

## Step 3 — Stop WS sessions

```bash
python skills/aegis-hibernator/scripts/ws_watcher.py stop
```

This calls `onchainos ws stop` and clears `ws_session_ids` from `hibernator.json`.

## Step 4 — Persist state

State is already on disk (every AEGIS write is atomic). The blackbox JSONL files are
append-only and survive any crash.

To confirm:

```bash
ls -la ~/.aegis/state/
ls -la ~/.aegis/state/blackbox/
python skills/aegis-blackbox/scripts/logger.py stats
```

## Step 5 — Operator review

Open `skills/aegis-blackbox/scripts/dashboard.html`. The header should show:

- `hibernation HIBERNATED`
- `prompt-inject N` (where N is the count seen across the session).
- Recent trades table populated with close transactions if Step 2 ran.

## Step 6 — Re-enable later

When the operator is ready to resume (after `cool_off_minutes`):

```bash
python skills/aegis-hibernator/scripts/drawdown.py wake
```

The framework refuses to wake before cool-off:

```
Cool-off active. Wake available at <ISO-8601>.
```
