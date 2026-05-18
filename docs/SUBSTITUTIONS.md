# SUBSTITUTIONS.md

Every place AEGIS substitutes a real OnchainOS CLI command for one named in the original build
prompt that did not exist in the reference repo. Audited against
[okx/onchainos-skills](https://github.com/okx/onchainos-skills) as of 2026-05-18.

- Wanted: `onchainos market signal-list <chain> --wallet-type "1,2,3"`
  Substituted with: `onchainos signal list --chain <chain> --wallet-type 1,2,3`
  Reason: command lives under the `signal` namespace, not `market`. Confirmed in
  `skills/okx-dex-signal/SKILL.md`.

- Wanted: `onchainos wallet portfolio-pnl`
  Substituted with: `onchainos market portfolio-overview` and `onchainos market
  portfolio-recent-pnl`
  Reason: no `wallet portfolio-pnl` command exists. Realized PnL surface is in `okx-dex-market`
  under `portfolio-*` commands. `portfolio-overview` returns rolling realized PnL + win rate;
  `portfolio-recent-pnl` returns per-token recent realized PnL.

- Wanted: bundler/sniper proxy
  Used: `onchainos memepump token-bundle-info --address <address>`
  Reason: this is the canonical bundle/sniper analytics endpoint
  (`skills/okx-dex-trenches/SKILL.md`). Combined with `token-details` (`top10HoldingsPercent`)
  for the cluster concentration factor.

- Wanted: LP unlock fields
  Used: `onchainos token advanced-info`
  Reason: advanced LP-lock fields surface here (per `okx-dex-token/SKILL.md` "advanced risk
  indicators including developer statistics and holder concentration").

- Wanted: official-skill BLOCK signal in fragility
  Used: `onchainos security token-scan`
  Reason: `riskLevel: CRITICAL` collapses to fragility 1.0 / BLOCK in `aegis-sentinel`. This is
  the documented OKX security decision verb.
