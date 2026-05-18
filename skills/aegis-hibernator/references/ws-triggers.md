# ws-triggers.md

Allow-list of WebSocket event patterns that engage hibernation. The watcher does NOT execute
arbitrary CLI from payload contents; it matches a small set of structural fields.

## Channel → trigger map

### `address-tracker-activity`

Subscribed with `--wallet-addresses <dev_wallet_1>,<dev_wallet_2>,…`. Triggers:

| Trigger | Pattern | Reason |
|---|---|---|
| `dev_sell` | event has `txType == "sell"` AND `walletAddress` matches a subscribed dev wallet | `dev_sell` |
| `dev_transfer_out` | `txType == "transfer"` AND `direction == "out"` AND `amount` ≥ 1 % of supply | `dev_sell` |

### `dex-market-memepump-new-token-openapi`

Subscribed with `--chain-index 501`. Triggers:

| Trigger | Pattern | Reason |
|---|---|---|
| `migrating` | `stage` transitions from `MIGRATING` to `MIGRATED` (or `bondingPercent` ≥ 100) AND token is in current positions | `migrating` |

### `dex-market-memepump-update-metrics-openapi`

Subscribed with `--chain-index 501`. Triggers:

| Trigger | Pattern | Reason |
|---|---|---|
| `cluster_shift_gt_10pct` | `top10HoldingsPercent` change > 10 percentage points within 5 min for a token in current positions | `cluster_shift_gt_10pct` |

## Loss-of-connection trigger

If the watcher loop fails to poll any session for `hibernator.ws_lost_retries` consecutive
attempts (default 3), it engages hibernation with `reason: ws_lost`. The threshold is reset
on successful poll.

## Audit digest

The watcher records a SHA-256 digest of the raw payload at trigger time (not the payload
itself) in `decisions.jsonl` so an auditor can correlate without exposing potentially
prompt-injecting content.
