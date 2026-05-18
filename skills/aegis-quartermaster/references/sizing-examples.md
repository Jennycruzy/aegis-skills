# sizing-examples.md

Worked examples for each `binding_constraint`. Reproduce with the exact CLI invocation below.

## Example 1 — `kelly_fraction` binds (clean entry)

```bash
python kelly.py size --strategy-id aegis-fader --token <ca> --chain solana \
    --fragility 0.10 --wallet-balance-usd 100000.00 \
    --wins 50 --losses 50 --avg-win 0.20 --avg-loss 0.05
```

- `hit_rate_shrunk = 51/105 = 0.486`.
- `payoff_ratio = 0.20 / 0.05 = 4.0`.
- `kelly_full = 0.486 − 0.514/4 = 0.357`.
- `kelly_use = 0.357 × 0.25 = 0.089` (8.9 %).
- `wallet_cap pct = 5 %` → wallet cap bites at $5 000.
- `fragility 0.10` → multiplier ≈ 0.84 → `$4 200`.
- `binding_constraint = wallet_cap`.

## Example 2 — `negative_edge`

```bash
python kelly.py size --strategy-id aegis-fader --token <ca> --chain solana \
    --fragility 0.10 --wallet-balance-usd 5000.00 \
    --wins 0 --losses 5 --avg-win 0.10 --avg-loss 0.10
```

`hit_rate_shrunk = 1/10 = 0.1`; `payoff_ratio = 1.0`; `kelly_full = 0.1 − 0.9/1 = −0.8`.
Return `size_usd = "0"`, `reason = "negative_edge"`,
`binding_constraint = "negative_edge"`.

## Example 3 — `fragility_curve` binds

```bash
python kelly.py size --strategy-id aegis-fader --token <ca> --chain solana \
    --fragility 0.55 --wallet-balance-usd 5000.00 \
    --wins 20 --losses 10 --avg-win 0.15 --avg-loss 0.08
```

`fragility = 0.55` → multiplier ≈ 0 (curve is `[0.5, 0.2]` → `[1.0, 0.0]`).
`size_after_frag ≈ $0` → below `min_position_usd = $5` → return 0,
`binding_constraint = "fragility_curve"`.

## Example 4 — `min_position` binds

```bash
python kelly.py size --strategy-id aegis-fader --token <ca> --chain solana \
    --fragility 0.45 --wallet-balance-usd 100.00 \
    --wins 5 --losses 5 --avg-win 0.10 --avg-loss 0.05
```

Wallet cap = 5 % of $100 = $5; fragility ≈ 0.36 multiplier; size_after_frag ≈ $1.80 <
$5 floor → return 0, `binding_constraint = "min_position"`.

## Example 5 — `wallet_cap` binds (typical case)

Already shown above in Example 1. The wallet-pct cap is the most common bind in practice,
because Kelly with `α=1 β=4` shrinkage on a healthy strategy lands in the 5–10 % range, and
`max_position_pct = 0.05`.
