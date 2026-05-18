# fragility-score.md

Canonical reference for AEGIS-Sentinel's composite Fragility Score.

## Composition

```
fragility = 0.30 × cluster_concentration
          + 0.25 × bundle_sniper
          + 0.20 × dev_rug_history
          + 0.15 × holder_velocity
          + 0.10 × lp_unlock_proximity
```

Weights live in `aegis.config.json` `sentinel.weights` and **must sum to 1.0**; the loader
asserts this.

## Per-factor normalisation

| Factor | Source | Normalisation |
|---|---|---|
| cluster_concentration | `memepump token-details.top10HoldingsPercent` + `token holders` | `clamp((top10pct − 0.20) / 0.60, 0, 1)` |
| bundle_sniper | `memepump token-bundle-info.bundlerHoldingsPercent + sniperHoldingsPercent` | `clamp(combined / 0.20, 0, 1)` — Solana only |
| dev_rug_history | `memepump token-dev-info.rugPullCount` (and tokenCount) | `clamp(rugPullCount / 3, 0, 1)`; on `tokenCount=0` → 0 |
| holder_velocity | `token price-info` 24h delta + `token holders` 24h delta | `abs(holder_delta_pct − price_delta_pct) / 0.5`, clamped |
| lp_unlock_proximity | `token advanced-info.lpUnlockTimeMs` | `1 − clamp(days_to_unlock / 30, 0, 1)`; locked > 30 d → 0 |

## OKX security override

If `onchainos security token-scan` returns `riskLevel == "CRITICAL"`, fragility is forced to
`1.0` and decision is `BLOCK`, **regardless** of the factor composition. Lower riskLevels are
attached to the report (`security_token_scan.riskLevel`) but do not alter the math.

## Decision verbs

```
if fragility ≥ sentinel.block_threshold       (default 0.50): BLOCK
elif fragility ≥ sentinel.size_down_threshold (default 0.30): SIZE_DOWN
else:                                                         ALLOW
```

## Defaults when a factor is unavailable

- Off-Solana → `bundle_sniper = 0.5`, `dev_rug_history = 0.5` with reasons
  `["bundle_na", "dev_info_na"]`.
- CLI failure on any factor → that factor defaults to `0.5` with
  `reasons: ["<factor>_unavailable"]`.
- Geo-block on any factor → factor defaults to `0.5`; canonical message surfaced via the caller.

The "default to 0.5" choice is deliberately moderate; it does not auto-allow a token whose data
we cannot read.

## Substitutions

The OKX reference repo does not currently expose `lpUnlockTimeMs` under `token advanced-info`
verbatim; we fall back to the closest available field (`lpLockUntilTimestamp` or similar). See
`docs/SUBSTITUTIONS.md` if your CLI version differs.
