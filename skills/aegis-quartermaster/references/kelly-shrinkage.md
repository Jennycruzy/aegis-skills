# kelly-shrinkage.md

## Why shrinkage

The classical Kelly criterion `f* = p − q/b` is brittle when `p` is estimated from few trades.
A naïve win rate of 1/1 inflates the bet; 0/3 collapses it to zero — both wrong. We use a
Beta(α=1, β=4) prior, equivalent to "seen 1 imaginary win and 4 imaginary losses". This is
intentionally pessimistic: the prior pulls early-life estimates toward `1/5 = 0.20`, well
below break-even for most payoff ratios.

```
hit_rate_shrunk = (wins + α) / (wins + losses + α + β)
```

Defaults: `α = 1`, `β = 4`. Adjustable via `quartermaster.shrinkage_alpha` /
`shrinkage_beta`.

## Fractional Kelly

Even the shrunk estimate is uncertain. We multiply by a fraction (default 0.25 — "quarter
Kelly") to absorb model error and avoid drawdowns that exceed the Kelly assumptions:

```
kelly_use = max(0, kelly_full) × kelly_fraction
```

`kelly_fraction` is the single most impactful tuning knob. Conservative defaults; the
competition rewards risk control more than aggressive sizing.

## Payoff ratio clamp

`avg_win / |avg_loss|` is clamped to `[0.1, 10.0]` to bound the Kelly formula's sensitivity
to outliers. A single 100× moonshot does not warp future sizing.

## Worked example

- 8 wins, 5 losses → `hit_rate_shrunk = 9/18 = 0.500`.
- `avg_win = 0.12`, `avg_loss = -0.06` → `payoff_ratio = 2.0`.
- `kelly_full = 0.5 − 0.5/2 = 0.25`.
- `kelly_use = 0.25 × 0.25 = 0.0625` (6.25 %).
- `max_position_pct = 0.05` → wallet-cap bites: 5 %.
- `wallet_balance_usd = 5000` → `size_wallet_cap = $250`.
- `fragility = 0.22` → curve maps 0.22 to ~0.776 → `size_after_frag = $194.05`.
- Above `min_position_usd = $5` → `size_usd = $194.05`,
  `binding_constraint = wallet_cap` (the wallet-pct cap fired first; fragility curve only
  trimmed it further, not bound it).

The rule for `binding_constraint`: report the cap whose **inequality strictly bound the
result** — i.e., the cap whose removal would have produced a larger size by more than 1 %.
This is implemented in `kelly.py` `_binding`.
