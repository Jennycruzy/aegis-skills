# workflows/dry-run.md

Identical to `full-trading-loop.md` **through Step 4c (simulate)**. The broadcast in Step 4d
is **replaced** by a logged "would-broadcast" event. No `swap execute` runs.

Use this before going live. A judge can run this end-to-end with sandbox keys and observe
every gate, every log line, and a populated dashboard — with **zero** real funds at risk.

## Differences from the live loop

| Step | Live | Dry-run |
|---|---|---|
| 4a token search | runs | runs |
| 4b quote | runs | runs |
| 4c simulate | runs | runs |
| 4d broadcast | `onchainos swap execute` | **skipped**; emit `dry_run_would_broadcast` event |
| 4e track | runs | skipped |
| 6 attribution | runs after delay | **synthesised** from the simulated output for dashboard fidelity |
| 7 drawdown check | runs | runs against the synthesised attribution |

## Invocation

```bash
python skills/aegis-fader/scripts/fade_score.py scan \
    --chain solana --window-minutes 60 --dry-run
```

`scan` emits `event: scan_invoked` with `dry_run: true`. Per-candidate gate evaluation, every
log line, and the dashboard panels are exercised exactly as in the live flow.

## Validation checklist

After a dry-run, verify:

- [ ] `decisions.jsonl` contains a `scan_invoked` row with `dry_run: true`.
- [ ] Each candidate has a `candidate_evaluated` row.
- [ ] At least one `fragility_computed` row appears per scored token.
- [ ] At least one `size_computed` row appears per `FOLLOW_LONG`.
- [ ] `gate_failed` rows appear for SKIPs with the matching `gate` field.
- [ ] No `swap_broadcast` rows.
- [ ] Dashboard "decisions" KPI > 0; "trades" KPI = 0 (dry-run does not append to
      `trades.jsonl`).
- [ ] `aegis-blackbox decay.py recompute` runs without errors.
