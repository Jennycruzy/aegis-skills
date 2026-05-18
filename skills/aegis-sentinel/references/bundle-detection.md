# bundle-detection.md

## Source

- `onchainos memepump token-bundle-info --address <ca>` → bundler / sniper analytics.

## Normalisation

Two scalar fields surface (names per the OKX reference repo's trenches skill):

- `bundlerHoldingsPercent` — share of supply held by accounts identified as bundlers.
- `sniperHoldingsPercent` — share of supply held by accounts identified as snipers.

```
bundle_share = (bundlerHoldingsPercent + sniperHoldingsPercent) / 100   # already pct
bundle_sniper = clamp(bundle_share / 0.20, 0.0, 1.0)
```

- Combined share ≥ 20 % → factor saturates at 1.
- Combined share = 10 % → factor = 0.5.
- Combined share = 0 → factor = 0.

## Chain availability

`memepump` endpoints are Solana-only per the reference repo. On X Layer or any non-Solana
chain, AEGIS-Sentinel sets `bundle_sniper = 0.5` (uncertain by default) with
`reasons: ["bundle_na"]`.

## Edge

- Either field missing → use the available one; if both missing, default 0.5 with
  `bundle_sniper_unavailable`.
- Geo-block (50125 / 80001) → default 0.5; canonical message surfaced via the caller.
- CLI returns `0` for both → factor is `0` (clean).
