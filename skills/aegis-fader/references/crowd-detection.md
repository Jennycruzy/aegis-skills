# crowd-detection.md

## Hypothesis

When many distinct signal sources (Smart Money, KOL, Whale) buy the same token within a
short window, the trade is **crowded**. Crowded trades unwind disproportionately when the
loudest sources start exiting — late entries get the worst fills.

Conversely, an under-followed entry (few signals, but **diverse** wallet types) is higher-EV:
fewer late-tape buyers means less unwinding pressure.

## Inputs

`onchainos signal list --chain <chain> --wallet-type 1,2,3 [--window-minutes <N>]` returns
rows of the shape (per the OKX reference repo):

```json
{
  "ts_ms": 1747545600000,
  "token": "<contract address>",
  "walletType": 1,           // 1 = Smart Money, 2 = KOL, 3 = Whale
  "walletAddress": "<addr>"
}
```

## Derived metrics (per token, within the lookback window)

```
signal_count        = |signals(token)|
source_diversity   = |distinct walletType in signals(token)|       # 1..3
max_signal_count   = max(signal_count over all tokens in window)
crowdedness        = signal_count / max(max_signal_count, 1)
                                                 ∈ [0, 1]
```

## Decay filter

Before counting, filter out any signal whose
`source_id = "<wallet_type_name>:<walletAddress>"` is classified `RETIRE` in
`decay_report.json`. This is computed by `aegis-blackbox` and refreshed hourly.

## Thresholds (config)

- `crowd_threshold` — default 0.70. At or above, candidate is "crowded".
- `min_source_diversity` — default 3. Requires Smart Money, KOL, **and** Whale all firing.

## Decision verbs (per token)

| crowdedness | source_diversity | fragility | Decision |
|---|---|---|---|
| ≥ 0.70 | any | < block_threshold | `FADE_OPPORTUNITY` (log-only) |
| ≥ 0.70 | any | ≥ block_threshold | `SKIP` (gate_failed: block) |
| < 0.70 | ≥ 3 | < 0.30 | `FOLLOW_LONG` (execute) |
| < 0.70 | < 3 | any | `SKIP` (gate_failed: diversity) |
| < 0.70 | ≥ 3 | 0.30–0.50 | `SKIP` (sentinel says SIZE_DOWN; but Fader gate insists frag < 0.30 for FOLLOW_LONG; reason: fragility) |
| < 0.70 | ≥ 3 | ≥ 0.50 | `SKIP` (gate_failed: block) |
