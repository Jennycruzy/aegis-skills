# cluster-rules.md

## Source

- Solana: `onchainos memepump token-details --address <ca>` → `top10HoldingsPercent` plus
  `onchainos token holders --chain solana --token <ca>` for top-N holder breakdown.
- X Layer: `onchainos token holders --chain xlayer --token <ca>` only.

## Normalisation

Define `top10pct` as the share of supply held by the top-10 wallets, 0–1.

```
cluster_concentration = clamp((top10pct - 0.20) / 0.60, 0.0, 1.0)
```

- `top10pct = 0.20` (typical organic) → 0.
- `top10pct = 0.50` (concentrated) → 0.50.
- `top10pct ≥ 0.80` (severe) → 1.

## Edge

- `top10pct` missing → return 0.5 with `cluster_concentration_unavailable`.
- Off-Solana chain with no memepump data → use `token holders` only; if that field is also
  missing, default to 0.5.
- Snapshot includes burn / mint / vesting addresses → AEGIS does NOT try to filter these in this
  initial release; trust the upstream `top10HoldingsPercent` heuristic. Documented as future
  work in `docs/ROADMAP.md`.
