# drawdown-math.md

## Realized rolling-drawdown definition

Per competition rule, only **realized** PnL counts. Unrealized positions are ignored.

For the most recent `N = hibernator.rolling_window_trades` trades **and** the last
`H = hibernator.rolling_window_hours` hours (whichever bound returns more rows):

```
trades_in_window = realized trades intersected over [now − H hours] and the last N trades
window_pnl_pct   = sum( realized_pnl_pct over trades_in_window )
```

`realized_pnl_pct` per trade comes from `onchainos market portfolio-recent-pnl` — the
per-token realized PnL field (`realizedPnlPercent` or close equivalent in the reference repo).

The hibernation rule:

```
if window_pnl_pct ≤ -hibernator.max_rolling_drawdown_pct:
    engage("drawdown")
```

Default `max_rolling_drawdown_pct = 0.15` (15 %).

## Insufficient history

If `len(trades_in_window) < 3`, the result is `indeterminate`. Status does not change, but
`aegis-fader` must treat indeterminate as "no new entries" until at least 3 realized trades
land in the window.

## Why this shape

- "Last N trades **and** last H hours" guards against both burst losses (many trades in a
  short window) and slow bleeds (steady losses over many hours).
- Realized only — unrealized swings cause false positives during normal volatility.
- Pure sum (no weighting) — auditable and matches what the OKX portfolio endpoint reports.

## Worked example

- `N = 10, H = 24`, default `max_rolling_drawdown_pct = 0.15`.
- Suppose `portfolio-recent-pnl` returns 8 realized trades in the last 24 h:
  `+0.03, +0.05, -0.02, -0.10, -0.08, -0.04, +0.01, -0.02`. Sum = `-0.17`.
- `-0.17 ≤ -0.15` → engage with `reason: drawdown`.
