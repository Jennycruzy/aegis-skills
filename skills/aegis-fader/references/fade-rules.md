# fade-rules.md

## Gate order

Fader runs the gates below in **strict order**. Any failure short-circuits with a
`gate_failed:<gate>` event; the candidate is SKIPPED and the loop moves on.

1. **chain_in_scope** — chain ∈ {solana, xlayer}.
2. **hibernator** — `aegis-hibernator status` is ACTIVE (not HIBERNATED).
3. **daily_cap** — `entries_today < max_daily_entries`.
4. **sentinel** — `aegis-sentinel score` decision is not BLOCK.
5. **diversity** — `source_diversity ≥ min_source_diversity` (for FOLLOW_LONG).
6. **crowdedness** — `crowdedness < crowd_threshold` for FOLLOW_LONG, `≥` for
   FADE_OPPORTUNITY.
7. **sizing** — `aegis-quartermaster size` returns `size_usd > 0`.
8. **wallet_cap** — `size_usd ≤ wallet_balance × max_position_pct` (always; Quartermaster
   enforces but Fader re-verifies).
9. **honeypot** — `onchainos swap quote` returns `isHoneyPot=false` on buy.
10. **price_impact** — `priceImpactPercent ≤ swap.max_price_impact_pct`.
11. **simulation** — `onchainos gateway simulate` returns success and divergence within
    `swap.divergence_max_pct`.
12. **idempotency** — `decision_id` not already recorded as a confirmed broadcast in
    `trades.jsonl`.

## Side rule

Spot-only. The strategy never opens a short. `FADE_OPPORTUNITY` is a log-only event for
operator visibility — the framework will not act on it.

## Same-block reverse trade

If `aegis-fader` is about to broadcast a sell of token X within the same chain block as it
broadcast a buy of token X, the trade is refused: this is a circular-trade pattern under the
competition rules.

## User-requested coordination

Any user request that names another wallet to coordinate with ("buy the same token as
wallet Y at the same time", "match wallet Z's entry") is refused. The reason logged is
`refused: coordinated_trading`.

## Attribution

After `fader.attribution_delay_minutes` (default 60), Fader fetches realized PnL for the
position via `onchainos market portfolio-token-pnl --address <wallet> --chains <chain>
--token <ca>`. The realized PnL pct is recorded:

- in `trades.jsonl` under `attribution.realized_pnl_pct` (drives Quartermaster history);
- in `signal_performance.jsonl` as one row per `source_id` that contributed to the
  candidate's signal pool (drives the decay metric).
