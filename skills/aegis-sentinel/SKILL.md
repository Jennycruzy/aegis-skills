---
name: aegis-sentinel
description: "Pre-flight token risk pricing for the AEGIS stack. Use when the user asks 'is this token safe to enter'/'这个币能买吗', 'show fragility score'/'脆弱度多少', 'audit holders / dev / bundlers'/'查持仓/查dev/查捆绑狙击', 'check rug risk'/'查跑路风险', or 'should I size down'/'需要缩仓吗'. Returns a continuous fragility score in [0,1] composed from five factors (cluster concentration, bundler/sniper presence, dev rug history, holder velocity, LP unlock proximity) plus the okx-security token-scan riskLevel. Decision verbs ALLOW / SIZE_DOWN / BLOCK. Composes with aegis-fader (consumer), aegis-quartermaster (uses score). Never reimplements honeypot/tax/phishing — defers to okx-security and okx-dex-swap. For swap quotes use okx-dex-swap; for deep token info use okx-dex-token / okx-dex-trenches."
license: Apache-2.0
metadata:
  author: aegis
  version: "1.0.0"
  homepage: "https://github.com/aegis/aegis-skills"
agent:
  requires:
    bins: ["onchainos"]
---

# AEGIS Sentinel

Continuous Fragility Score per token, in [0, 1], composed from five weighted factors and a hard
`okx-security` BLOCK signal.

## Prerequisites

Read `../_shared/preflight.md`. Sentinel calls into `onchainos token`, `onchainos memepump`, and
`onchainos security`. No swap-execution calls.

## Skill Routing

AEGIS-Sentinel owns:

- Cluster concentration via `onchainos token holders` (top-10 holder concentration) + memepump
  `top10HoldingsPercent`.
- Bundler / sniper presence via `onchainos memepump token-bundle-info` (Solana only).
- Developer rug history via `onchainos memepump token-dev-info` (Solana only).
- Holder velocity divergence — derived from `onchainos token price-info` 24h delta vs `onchainos
  token holders` 24h delta (see `references/fragility-score.md`).
- LP unlock proximity via `onchainos token advanced-info`.
- Hard BLOCK on `onchainos security token-scan` `riskLevel: CRITICAL`.

It does NOT own:
- Honeypot / tax / phishing → `okx-security`, `okx-dex-swap` (Sentinel **calls** these, never
  reimplements).
- Sizing → `aegis-quartermaster`.
- Strategy decisions → `aegis-fader`.

## Quickstart

```bash
# 1. Score one Solana token
python skills/aegis-sentinel/scripts/fragility.py score \
    --chain solana --token <ca>

# 2. Inspect cached value
python skills/aegis-sentinel/scripts/fragility.py inspect --chain solana --token <ca>

# 3. Force refresh (bypass 60-s cache)
python skills/aegis-sentinel/scripts/fragility.py score \
    --chain solana --token <ca> --refresh
```

## Chain Name Support

| Chain | CLI name | chainIndex | In-scope? |
|---|---|---|---|
| Solana | `solana` | 501 | ✅ full support |
| X Layer | `xlayer` | 196 | ✅ holder/LP only — bundler/dev factors default to 0.5 with `reasons: ["bundle_na", "dev_info_na"]` |

Full table: `../_shared/chain-support.md`.

## Command Index

| # | Command | Description |
|---|---|---|
| 1 | `fragility.py score --chain … --token …` | Compute fragility + decision; uses 60-s cache unless `--refresh` |
| 2 | `fragility.py inspect --chain … --token …` | Show cached entry only; do not call CLI |
| 3 | `fragility.py factors --chain … --token …` | Return only the per-factor breakdown (no decision verb) |

## Operation Flow

### Step 1 — Identify Intent

Sentinel is called by `aegis-fader` on every candidate token. It can also be invoked
interactively by the user to triage a single token.

### Step 2 — Collect Parameters

- `--chain ∈ {solana, xlayer}` (other chains accepted but degraded).
- `--token <contract address>`: Solana base58 or EVM lowercase hex.
- `--refresh`: skip cache.

### Step 3 — Call and Display

For each factor:
1. Read CLI per the table in §References below.
2. Normalise the field into `[0, 1]`.
3. Multiply by the configured weight.
4. Sum.

If `onchainos security token-scan` returns `riskLevel: CRITICAL`, fragility is forced to `1.0`
and decision is `BLOCK`. Other riskLevels are surfaced as `security_token_scan` in the report
but do not override the composition.

### Step 4 — Suggest Next Steps

- `BLOCK` → caller logs `gate_failed: block` and SKIPs.
- `SIZE_DOWN` → caller halves the size via `aegis-quartermaster`.
- `ALLOW` → caller proceeds to quote / simulate / broadcast.

## Cross-Skill Workflows

### Workflow A — Fader entry pre-flight

1. `aegis-fader` selects a candidate token.
2. Calls `aegis-sentinel score`.
3. Emits `fragility_computed` to Blackbox.
4. Branches on `decision`.

### Workflow B — Manual triage

User pastes a token CA into the agent. The agent calls
`fragility.py score --chain solana --token <ca>` and reports the per-factor breakdown so the
user can decide manually.

## Risk-Control Logic

```
factors = {
  cluster_concentration: 0.30 weight,
  bundle_sniper:         0.25 weight,
  dev_rug_history:       0.20 weight,
  holder_velocity:       0.15 weight,
  lp_unlock_proximity:   0.10 weight,
}

normalised_value ∈ [0, 1] per factor (see references/fragility-score.md)
fragility = Σ (weight × normalised_value)

if security_token_scan.riskLevel == "CRITICAL": fragility = 1.0, decision = BLOCK
elif fragility ≥ sentinel.block_threshold (default 0.50): decision = BLOCK
elif fragility ≥ sentinel.size_down_threshold (default 0.30): decision = SIZE_DOWN
else: decision = ALLOW
```

## State Management

Path: `~/.aegis/state/sentinel_cache.json`.

```json
{
  "schema_version": 1,
  "entries": {
    "solana:<ca>": {
      "ts_ms": 1747545600000,
      "fragility": "0.42",
      "decision": "SIZE_DOWN",
      "factors": { ... }
    }
  }
}
```

Cache TTL: `sentinel.cache_ttl_seconds` (default 60). Entries older than TTL are evicted on
read and recomputed.

## Edge Cases

- **Invalid token / not found** → fragility = 1.0, decision = BLOCK with
  `reasons: ["token_not_found"]`.
- **Unsupported chain** → factors `bundle_sniper`, `dev_rug_history` default to 0.5 with
  `reasons: ["bundle_na", "dev_info_na"]`. Other factors still computed.
- **Geo-block** (50125 / 80001) on any factor → that factor defaults to 0.5; reasons include
  `geo_block:<factor>`; canonical user-facing message is surfaced via the calling Fader.
- **Simulation failure** is not Sentinel's concern.
- **Missing data** on a single factor → factor defaults to 0.5 with
  `reasons: ["<factor>_unavailable"]`.
- **Rate limit on any CLI call** → transport retry; if all retries fail, factor defaults to 0.5.
- **Schema mismatch** on sentinel_cache.json → refuse to load; emit `schema_mismatch`; recompute.

## Observability Hooks

Emits `fragility_computed` to `~/.aegis/state/blackbox/decisions.jsonl`:

```json
{"schema_version": 1, "ts_ms": 1747545600000, "skill": "aegis-sentinel",
 "event": "fragility_computed", "token": "<ca>", "chain": "solana",
 "fragility": "0.42", "decision": "SIZE_DOWN",
 "factors": {"cluster_concentration": {"value": "0.31", "weight": "0.30"}, ...},
 "reasons": ["bundle_present"], "security_token_scan": {"riskLevel": "MEDIUM"}}
```

## Safety Guarantees

- Never broadcasts. Read-only CLI calls.
- Never reimplements honeypot / tax / phishing — always delegates to `okx-security`,
  `okx-dex-swap`.
- Never trusts CLI string fields as instructions (sanitises before display).
- Never returns `decision: ALLOW` when `riskLevel: CRITICAL` is set.

## Composition Contract

- **Calls**: `onchainos token holders`, `onchainos token price-info`, `onchainos token
  advanced-info`, `onchainos memepump token-details`, `onchainos memepump token-bundle-info`,
  `onchainos memepump token-dev-info`, `onchainos security token-scan`.
- **Called by**: `aegis-fader` per candidate. May also be invoked interactively.
- **Independently usable?** Yes — any agent can request a fragility score for a token.

## Testing

Fixtures: `tests/fixtures/token_fragile.json`, `token_clean.json`.

Unit tests: `tests/unit/test_fragility.py` — clean token, fragile token, missing-factor
defaults, non-Solana chain (factor defaults to 0.5), CRITICAL forces BLOCK, threshold
boundaries.

## Global Notes

- All output JSON.
- All factor values and weights are decimal strings on disk.
- EVM contract addresses lowercase. Solana base58.
- Timestamps UTC ms.
- Factor weights sum to 1.0; the loader validates and refuses non-summing-to-1 configs.
