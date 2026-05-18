# signal-aggregation.md

## Source

`onchainos signal list --chain <chain> --wallet-type 1,2,3` — multi-select on `--wallet-type`
combines Smart Money (1) + KOL (2) + Whale (3) into one feed.

(`signal-list` does not exist as a single-token command in the reference repo; we use
`signal list` with space — see `docs/SUBSTITUTIONS.md`.)

## Window

`window_minutes` (default 60). Fader filters returned rows by `ts_ms ≥ now − window_ms`. The
CLI itself may serve a longer window; Fader does the time filtering after the fetch.

## Grouping

Group by `token` (contract address). For each group, collect:

- `signal_count` (number of rows)
- `walletTypes` (set of distinct `walletType` values seen)
- `source_diversity = |walletTypes|`
- `source_ids` (set of `"<wallet_type_name>:<walletAddress>"`)
- `first_ts_ms`, `last_ts_ms`

`crowdedness` is computed at the **window level** by dividing each token's `signal_count` by
the max across the window:

```
crowdedness(token) = signal_count(token) / max(max_signal_count, 1)
```

## Decay filtering

Before grouping, the aggregator drops signals whose `source_id` is classified `RETIRE` in
`decay_report.json`. The report is loaded once per scan. If the report is missing or older
than `blackbox.decay_recompute_hours * 2`, the filter is bypassed and an
`event: decay_stale` row is logged.

## Window-start identifier

For deterministic operation IDs, Fader anchors the window to a 10-second-grid start:

```
window_start_ms = (now_ms // 10_000) * 10_000 - lookback_ms
```

Each candidate's `decision_id = "fader-<chain>-<token>-<window_start_ms>"`. Retrying the same
scan within 10 s reuses the same decision_id, making the flow idempotent.
