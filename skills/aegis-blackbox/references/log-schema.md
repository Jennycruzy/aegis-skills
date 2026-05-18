# log-schema.md

Every JSONL row written by AEGIS skills conforms to one of the shapes below. `schema_version` is
mandatory. `ts_ms` is UTC milliseconds. `decision_id` is the deterministic identifier shared
across rows that belong to the same Fader candidate.

## Common envelope

```json
{
  "schema_version": 1,
  "ts_ms": 1747545600000,
  "skill": "aegis-fader | aegis-sentinel | aegis-hibernator | aegis-quartermaster | aegis-blackbox",
  "event": "<event type>",
  "decision_id": "fader-<chain>-<token>-<window_start_ms>"
}
```

## Event types and additional fields

### signal_window_scanned

```json
{"event": "signal_window_scanned", "chain": "solana", "window_minutes": 60,
 "candidates": 12, "max_signal_count": 14}
```

### candidate_evaluated

```json
{"event": "candidate_evaluated", "token": "<ca>", "chain": "solana",
 "signal_count": 7, "source_diversity": 3, "crowdedness": "0.78"}
```

### fragility_computed

```json
{"event": "fragility_computed", "token": "<ca>", "chain": "solana",
 "fragility": "0.42", "decision": "ALLOW", "factors": {...}}
```

### size_computed

```json
{"event": "size_computed", "token": "<ca>", "wallet_balance_usd": "5000.00",
 "kelly_full": "0.087", "size_usd": "39.13", "binding_constraint": "fragility_curve"}
```

### gate_passed / gate_failed

```json
{"event": "gate_failed", "gate": "honeypot | divergence | hibernated | geo_block | …",
 "token": "<ca>", "detail": {...}}
```

### swap_quoted / swap_simulated / swap_broadcast / swap_tracked

```json
{"event": "swap_broadcast", "token": "<ca>", "tx_hash": "…", "from_amount": "1.0",
 "to_amount": "0.99", "price_impact": "0.42"}
```

### attribution_recorded

```json
{"event": "attribution_recorded", "decision_id": "…", "realized_pnl_pct": "0.04",
 "horizon_minutes": 60}
```

### hibernation_engaged / hibernation_cleared

```json
{"event": "hibernation_engaged", "reason": "drawdown",
 "last_realized_pnl_pct": "-0.18"}
```

### ws_trigger

```json
{"event": "ws_trigger", "channel": "address-tracker-activity",
 "trigger": "dev_sell", "payload_digest": "sha256:…"}
```

### decay_recomputed

```json
{"event": "decay_recomputed", "sources_scanned": 14, "retired": 2,
 "monitor": 3, "active": 9}
```

### corrupt_line / rotation / schema_mismatch / prompt_injection_suspect

```json
{"event": "corrupt_line", "file": "decisions.jsonl", "byte_offset": 4823}
{"event": "rotation", "file": "decisions.jsonl",
 "archived_to": "decisions_archive_…jsonl", "bytes": 104857600}
{"event": "schema_mismatch", "file": "hibernator.json",
 "found_version": 0, "expected_version": 1}
{"event": "prompt_injection_suspect", "field": "tokenName",
 "reason": "zero_width_chars"}
```

## Trade row (`trades.jsonl`)

```json
{"schema_version": 1, "ts_ms": 1747545600000, "skill": "aegis-fader",
 "decision_id": "fader-solana-<ca>-…", "token": "<ca>", "chain": "solana",
 "side": "buy", "size_usd": "39.13", "from_token": "11111111111111111111111111111111",
 "to_token": "<ca>", "from_amount": "0.23", "to_amount": "12345.6",
 "price_impact": "0.42", "tx_hash": "…", "sim_ok": true,
 "attribution": {"realized_pnl_pct": "0.04", "horizon_minutes": 60}}
```

## Signal performance row (`signal_performance.jsonl`)

```json
{"schema_version": 1, "ts_ms": 1747545600000, "skill": "aegis-fader",
 "source_id": "smart_money:<wallet>", "token": "<ca>", "chain": "solana",
 "forward_return_1h": "0.012", "kline_basis": {"t0_price": "0.0001",
 "t1_price": "0.000101"}}
```
