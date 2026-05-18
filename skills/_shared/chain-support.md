# chain-support.md

AEGIS is built for the OKX Agentic Wallet Trading Competition, which counts only Solana and
X Layer token trades. Skills enforce this at every entry point.

## Competition scope

| Chain | CLI name | chainIndex | Notes |
|---|---|---|---|
| Solana | `solana` | **501** | Primary chain for meme/launchpad signal flow. Full memepump support. |
| X Layer | `xlayer` | **196** | Gas-free. Primary chain for stablecoin-pair and lower-risk entries. |

## Reference (out-of-scope, read-only context)

| Chain | CLI name | chainIndex |
|---|---|---|
| Ethereum | `ethereum` | 1 |
| Base | `base` | 8453 |
| BSC | `bsc` | 56 |
| Arbitrum | `arbitrum` | 42161 |
| Polygon | `polygon` | 137 |

AEGIS-Fader refuses chains outside the competition scope with:

> "Chain <name> is outside AEGIS competition scope. AEGIS-Fader runs on Solana and X Layer only.
> See `skills/_shared/chain-support.md`."

`aegis-sentinel` accepts any chain for read-only queries but defaults Solana-only factors
(bundler/sniper, dev rug history) to 0.5 with `reasons: ["bundle_na", "dev_info_na"]` when off
Solana.
