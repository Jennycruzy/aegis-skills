# ROADMAP.md

Future work explicitly out of scope for v1.0.0.

- **Backtester.** A historical replay engine that feeds `signal_performance.jsonl` rows from
  a frozen window into the same pure-function decision tree. Important for tuning
  `crowd_threshold` and the fragility weights.
- **Per-source weighting.** Replace the global decay band (RETIRE / MONITOR / ACTIVE) with a
  per-source weight in [0, 1] that smoothly attenuates `signal_count` contributions. Better
  for slow-decay sources.
- **Burn / mint / vesting exclusion** in the cluster factor. Right now
  `top10HoldingsPercent` is taken at face value; a proper version would filter known
  burn addresses, mint authorities, and vesting contracts before computing concentration.
- **X Layer memepump parity.** The reference repo currently exposes memepump endpoints on
  Solana only. If/when X Layer parity ships, AEGIS-Sentinel can drop the `bundle_na` /
  `dev_info_na` defaults on X Layer.
- **Self-tuning Kelly fraction.** A simple controller that nudges `kelly_fraction` up after
  a stretch of green trades and down after a stretch of red — bounded by user-configurable
  hard caps.
- **WS persistence on crash.** Today the watcher loses session state if the host crashes
  mid-poll. A small inotify-based supervisor would re-start the sessions.
- **Multi-strategy support.** Quartermaster aggregates by `decision_id` prefix; the strategy
  catalogue is currently `aegis-fader` only. A second strategy (e.g., a mean-reversion
  module) could be added without changes to the math.
- **Granular geo-block surfacing.** Distinguish between "this endpoint is geo-blocked" and
  "this account is geo-blocked" — useful for travelling operators.
- **Live attribution refinement.** Today attribution is one-shot at
  `attribution_delay_minutes`. A more honest version would track open-position MTM until the
  position closes for real, then record the realized PnL.

If a contributor wants to take any of these on, see `CONTRIBUTING.md` for the ground rules.
