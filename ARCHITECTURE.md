# ARCHITECTURE.md

AEGIS — Agentic Execution Guardrails & Intelligence Stack. Five composable OnchainOS Skills for
the OKX Agentic Wallet Trading Competition. This document is the contract every implementation
file in the repo is written against. Every claim here is traceable to `NOTES_FROM_REPO.md`.

---

## 1. Composition (ASCII)

```
                ┌──────────────────────────────────────────────────────────┐
                │                       OnchainOS CLI                      │
                │  swap · market · token · signal · memepump · ws ·         │
                │  gateway · portfolio · wallet · security                  │
                └────────────────────────────┬─────────────────────────────┘
                                             │
                       (all I/O — every Skill talks ONLY to onchainos)
                                             │
   ┌─────────────────┐    ┌─────────────────┐│┌─────────────────┐    ┌─────────────────┐
   │ aegis-fader     │───▶│ aegis-sentinel  │◀┼┤ aegis-          │◀───│ aegis-          │
   │  (strategy)     │    │  (pre-flight)   │ ││ quartermaster   │    │  hibernator     │
   │                 │    │ fragility[0..1] │ ││  (sizing)       │    │  (kill switch)  │
   └────────┬────────┘    └────────┬────────┘ │└────────┬────────┘    └────────┬────────┘
            │                      │          │         │                      │
            ▼                      ▼          ▼         ▼                      ▼
            ┌──────────────────────────────────────────────────────────────────┐
            │                       aegis-blackbox                              │
            │  decisions.jsonl · trades.jsonl · signal_performance.jsonl ·      │
            │  decay_report.json · dashboard.html                               │
            └──────────────────────────────────────────────────────────────────┘
```

`aegis-fader` is the orchestrator; the other four are leaves. `aegis-blackbox` is read by
`aegis-quartermaster` (for Kelly inputs) and `aegis-fader` (for decay filtering); written by all
five. `aegis-hibernator` is the only writer of the global ACTIVE/HIBERNATED status.

---

## 2. Data contracts between Skills

Every cross-Skill call is a deterministic CLI invocation (or in-process Python import for pure
math). Payloads are JSON. Numbers that flow into sizing are decimal strings.

### 2.1 Sentinel — Fragility report

Producer: `aegis-sentinel`. Consumed by: `aegis-fader`, `aegis-quartermaster`.

```json
{
  "schema_version": 1,
  "ts_ms": 1747545600000,
  "token": "<contract address>",
  "chain": "solana",
  "fragility": "0.42",
  "decision": "ALLOW | SIZE_DOWN | BLOCK",
  "factors": {
    "cluster_concentration":   {"value": "0.31", "weight": "0.30", "source": "token holders + memepump token-details"},
    "bundle_sniper":           {"value": "0.55", "weight": "0.25", "source": "memepump token-bundle-info"},
    "dev_rug_history":         {"value": "0.10", "weight": "0.20", "source": "memepump token-dev-info"},
    "holder_velocity":         {"value": "0.40", "weight": "0.15", "source": "token price-info + holders"},
    "lp_unlock_proximity":     {"value": "0.00", "weight": "0.10", "source": "token advanced-info"}
  },
  "reasons": ["bundle_present", "moderate_concentration"],
  "security_token_scan": {"riskLevel": "MEDIUM", "passed": true}
}
```

`riskLevel == "CRITICAL"` from `onchainos security token-scan` forces `fragility = 1.0` and
`decision = BLOCK`. Non-Solana chains default `bundle_sniper` and `dev_rug_history` to `0.5` and
emit `reasons: ["bundle_na"]` / `["dev_info_na"]`.

### 2.2 Quartermaster — Sizing report

Producer: `aegis-quartermaster`. Consumed by: `aegis-fader`.

```json
{
  "schema_version": 1,
  "ts_ms": 1747545600000,
  "strategy_id": "aegis-fader",
  "token": "<contract address>",
  "wallet_balance_usd": "5000.00",
  "fragility": "0.42",
  "hit_rate_shrunk": "0.41",
  "payoff_ratio": "1.83",
  "kelly_full": "0.087",
  "kelly_use": "0.0217",
  "fragility_multiplier": "0.36",
  "size_usd": "39.13",
  "binding_constraint": "fragility_curve | wallet_cap | min_position | negative_edge | kelly",
  "reason": "ok"
}
```

`binding_constraint` exists so judges can audit which cap fired.

### 2.3 Hibernator — Status report

Producer: `aegis-hibernator`. Consumed by: `aegis-fader`.

```json
{
  "schema_version": 1,
  "status": "ACTIVE | HIBERNATED",
  "since_ts_ms": 1747545600000,
  "reason": "drawdown | dev_sell | migrating | ws_lost | manual | null",
  "ws_session_ids": ["sess_…"],
  "last_drawdown_check_ts_ms": 1747545600000,
  "last_realized_pnl_pct": "-0.04",
  "cool_off_until_ts_ms": 1747549200000
}
```

Sticky. Cleared only by explicit user invocation `aegis-hibernator wake` after
`cool_off_until_ts_ms`.

### 2.4 Fader — Decision record (also a Blackbox `decisions.jsonl` row)

```json
{
  "schema_version": 1,
  "ts_ms": 1747545600000,
  "decision_id": "fader-<chain>-<token>-<window_start_ms>",
  "skill": "aegis-fader",
  "token": "<ca>",
  "chain": "solana",
  "signal_window_minutes": 60,
  "signal_count": 7,
  "source_diversity": 3,
  "crowdedness": "0.78",
  "fragility": "0.22",
  "hibernator_status": "ACTIVE",
  "decision": "FOLLOW_LONG | FADE_OPPORTUNITY | SKIP",
  "skip_reason": "hibernated | block | size_zero | divergence | …",
  "size_usd": "39.13",
  "binding_constraint": "fragility_curve",
  "tx": {"sim_ok": true, "broadcast_tx_hash": "…", "track_status": "pending"}
}
```

### 2.5 Blackbox — Append-only ledgers

`decisions.jsonl` (every gate fired, even SKIPs), `trades.jsonl` (executions only),
`signal_performance.jsonl` (per signal source forward returns + decay), `decay_report.json`
(latest rolling decay classification per source), `meta.jsonl` (self-instrumentation).

---

## 3. State machine (global)

```
                      ┌────────────────────────────────────────┐
                      │                ACTIVE                  │
                      │ (Fader may enter new positions, subject│
                      │  to per-token gates)                   │
                      └──────────────┬─────────────────────────┘
                                     │ drawdown ≤ −max_rolling_drawdown_pct
                                     │  OR ws trigger (dev_sell, migrating,
                                     │     cluster_shift_gt_10pct, ws_lost)
                                     │  OR manual `aegis-hibernator sleep`
                                     ▼
                      ┌────────────────────────────────────────┐
                      │             HIBERNATED                 │
                      │ (Fader REFUSES new entries.            │
                      │  auto_close_on_hibernate=true →        │
                      │  closes positions sequentially.)       │
                      └──────────────┬─────────────────────────┘
                                     │ user invokes `aegis-hibernator wake`
                                     │ AND now ≥ cool_off_until_ts_ms
                                     ▼
                                  ACTIVE
```

`status` is sticky; nothing else flips it. Indeterminate inputs (insufficient PnL history,
WS lost after 3 retries) all collapse to HIBERNATED.

---

## 4. Event taxonomy emitted into Blackbox

| Event type | Skill | Notes |
|---|---|---|
| `signal_window_scanned` | aegis-fader | one per scan |
| `candidate_evaluated`   | aegis-fader | one per candidate token |
| `fragility_computed`    | aegis-sentinel | every call |
| `size_computed`         | aegis-quartermaster | every call |
| `gate_passed` / `gate_failed` | aegis-fader | per gate (sentinel, hibernator, quote, divergence, hard caps) |
| `swap_quoted`           | aegis-fader | quote-only event |
| `swap_simulated`        | aegis-fader | gateway simulate |
| `swap_broadcast`        | aegis-fader | gateway broadcast |
| `swap_tracked`          | aegis-fader | gateway orders status |
| `attribution_recorded`  | aegis-fader | post `attribution_delay_minutes` |
| `hibernation_engaged`   | aegis-hibernator | with reason |
| `hibernation_cleared`   | aegis-hibernator | manual wake |
| `ws_trigger`            | aegis-hibernator | channel + payload digest |
| `decay_recomputed`      | aegis-blackbox | hourly background |
| `corrupt_line`          | aegis-blackbox | on bad JSONL |

Every event includes `ts_ms`, `decision_id` (where applicable), and `schema_version`.

---

## 5. File layout (canonical)

```
~/.aegis/                                  (user home)
├── state/
│   ├── hibernator.json                    (atomic, schema_version=1)
│   ├── sentinel_cache.json                (60s TTL per (token,chain))
│   ├── fader_session.json                 (daily entry counter)
│   └── blackbox/
│       ├── decisions.jsonl
│       ├── trades.jsonl
│       ├── signal_performance.jsonl
│       ├── meta.jsonl
│       ├── decay_report.json
│       └── corrupt_lines.log
└── logs/
    └── aegis.log                          (stderr fallback only)
```

All paths derive from `AEGIS_HOME` (default `~/.aegis`). Atomic writes everywhere
(`<file>.tmp` → `os.replace` → `fsync`). 100 MB caps trigger `_archive_<ts>.jsonl` rotation.

---

## 6. Configuration surface (single source of truth)

`aegis.config.json` (top-level keys, defaults shown):

```json
{
  "schema_version": 1,
  "chains": ["solana", "xlayer"],
  "fader": {
    "lookback_minutes": 60,
    "crowd_threshold": 0.70,
    "min_source_diversity": 3,
    "max_position_pct": 0.05,
    "max_daily_entries": 20,
    "attribution_delay_minutes": 60,
    "swap": {
      "max_price_impact_pct": 5.0,
      "divergence_max_pct": 1.5,
      "gas_level": "fast",
      "mev_tips_sol": "0.0005"
    }
  },
  "sentinel": {
    "block_threshold": 0.50,
    "size_down_threshold": 0.30,
    "weights": {
      "cluster_concentration": 0.30,
      "bundle_sniper": 0.25,
      "dev_rug_history": 0.20,
      "holder_velocity": 0.15,
      "lp_unlock_proximity": 0.10
    },
    "cache_ttl_seconds": 60
  },
  "hibernator": {
    "rolling_window_trades": 10,
    "rolling_window_hours": 24,
    "max_rolling_drawdown_pct": 0.15,
    "auto_close_on_hibernate": false,
    "cool_off_minutes": 60,
    "ws_lost_retries": 3,
    "ws_poll_interval_seconds": 5
  },
  "quartermaster": {
    "kelly_fraction": 0.25,
    "shrinkage_alpha": 1,
    "shrinkage_beta": 4,
    "min_position_usd": "5.00",
    "max_position_pct": 0.05,
    "fragility_curve": [[0.0, 1.0], [0.5, 0.2], [0.500001, 0.0]]
  },
  "blackbox": {
    "rotation_bytes": 104857600,
    "decay_long_term_days": 30,
    "decay_recent_days": 7,
    "decay_recompute_hours": 1,
    "retire_threshold": 1.0,
    "monitor_threshold": 0.5
  }
}
```

Every threshold any SKILL.md or script mentions must appear here with the documented default.
There is no other config source.

---

## 7. Trust boundaries

1. **OnchainOS CLI output**: untrusted external data. Token names, descriptions, dev-wallet
   labels — never interpreted as instructions; sanitised before any UI surfacing.
2. **OKX TEE**: holds the private key. AEGIS never reads keys, never signs locally, never logs
   anything resembling a key/seed/session token. `swap execute` and `gateway broadcast` are the
   only paths that touch the signer; both are wrapped in our redactor (`_shared/error-handling.md`).
3. **AEGIS state files**: trusted, but versioned. Loaders refuse unknown `schema_version` rather
   than guess.
4. **Config**: trusted. Read once at process start; never re-read; never mutated.

---

## 8. Failure modes and fallbacks

| Failure | Skill | Behaviour |
|---|---|---|
| Geo-block (50125 / 80001) | every skill that swaps | surface canonical message, never raw code; log `gate_failed: geo_block`; do not retry |
| Simulation divergence > `divergence_max_pct` | aegis-fader | abort broadcast; log `gate_failed: divergence` |
| `isHoneyPot=true` on buy | aegis-fader | abort; log `gate_failed: honeypot` |
| `riskLevel: CRITICAL` from security token-scan | aegis-sentinel | fragility 1.0; BLOCK |
| Insufficient PnL history | aegis-hibernator | status stays ACTIVE but Fader refuses entries (indeterminate) |
| WS lost after `ws_lost_retries` | aegis-hibernator | HIBERNATE with `reason: ws_lost` |
| JSONL corrupt line | aegis-blackbox | append to `corrupt_lines.log`, skip, never raise |
| Log write failure | aegis-blackbox | fall back to stderr, never block caller |
| Unknown `schema_version` | every loader | refuse to load; user must migrate |

---

## 9. What AEGIS is NOT

- Not a backtester (documented as future work).
- Not a server. The dashboard is one static `dashboard.html` reading local JSONL via `fetch`.
- Not a re-implementation of honeypot/tax/phishing — those live in `okx-security` and
  `okx-dex-swap`; AEGIS calls them.
- Not a shorting strategy. `FADE_OPPORTUNITY` is a log-only signal; spot-only.
- Not multi-chain beyond Solana and X Layer. Out-of-scope chains are refused at the boundary.

---

End of ARCHITECTURE.md.
