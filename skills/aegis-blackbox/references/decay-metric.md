# decay-metric.md

## Hypothesis

A signal source (`smart_money:<wallet>`, `kol:<wallet>`, `whale:<wallet>`) has historical
forward-return distribution. If the **recent** distribution drifts negative relative to the
**long-term**, the source has decayed and should be retired.

## Inputs

For each row in `signal_performance.jsonl`:

- `source_id`: stable identifier (`<wallet_type>:<wallet_address>`).
- `forward_return_1h`: realized 1-hour log-return after the signal fired, computed against
  `onchainos market kline --chain <chain> --address <token-ca> --bar 1H --limit 2`; first
  close is t0, second close is t1.

## Formula

```
long_term_mean  = mean(forward_returns over last decay_long_term_days)
recent_mean     = mean(forward_returns over last decay_recent_days)
long_term_std   = stdev(forward_returns over last decay_long_term_days, ddof=1)
decay_score     = max(0, (long_term_mean - recent_mean) / max(0.001, long_term_std))
```

Defaults: `decay_long_term_days = 30`, `decay_recent_days = 7`.

`max(0.001, …)` prevents division by zero when std collapses (single data point or all-equal
returns).

## Classification

| Band | Condition | Effect |
|---|---|---|
| `RETIRE` | `decay_score ≥ retire_threshold` (default 1.0) | `aegis-fader` excludes the source on next scan. |
| `MONITOR` | `monitor_threshold ≤ decay_score < retire_threshold` (default 0.5) | source is retained but flagged in the dashboard. |
| `ACTIVE` | `decay_score < monitor_threshold` | full weight. |

A source with fewer than 5 long-term rows or 3 recent rows is classified `INSUFFICIENT_DATA`
and treated as `ACTIVE` (we do not retire on noise).

## Output

`decay_report.json` is overwritten atomically each run:

```json
{
  "schema_version": 1,
  "computed_ts_ms": 1747545600000,
  "config": {"long_term_days": 30, "recent_days": 7,
             "retire_threshold": 1.0, "monitor_threshold": 0.5},
  "sources": {
    "smart_money:<wallet>": {
      "long_term_n": 142,
      "recent_n": 21,
      "long_term_mean": "0.014",
      "recent_mean": "-0.003",
      "long_term_std": "0.052",
      "decay_score": "0.327",
      "band": "MONITOR"
    }
  }
}
```

## Edge cases

- `recent_mean` ≥ `long_term_mean` → `decay_score = 0` (source is steady or improving).
- `long_term_std = 0` after the `max(0.001, …)` clamp → score is bounded; never raises.
- `decay_score = null` if no recent rows exist; band stays at the previous classification.
- Kline endpoint geo-blocked → preserve previous classification; emit
  `decay_recompute_partial` to `meta.jsonl`.
