# workflows/INDEX.md

Natural-language intent → workflow file map for AEGIS.

| Intent | English | 中文 | Workflow |
|---|---|---|---|
| End-to-end trading loop | "run the AEGIS strategy", "start the loop", "trade end-to-end" | "跑一遍交易闭环", "执行AEGIS策略" | [full-trading-loop.md](./full-trading-loop.md) |
| Dry run | "dry-run", "simulate without broadcasting", "test the loop on sandbox" | "空跑", "不广播只模拟", "沙盒测试" | [dry-run.md](./dry-run.md) |
| Safe shutdown | "close all positions", "stop everything safely", "hard exit" | "全部平仓", "安全停机" | [safe-shutdown.md](./safe-shutdown.md) |

If the user request mentions a third-party DApp by name (Polymarket, Aave, Hyperliquid,
PancakeSwap, Raydium, Curve, …), route to `okx-dapp-discovery` per the OKX house rule. AEGIS
deliberately stays out of named-venue execution.

## Pre-loop checklist (every workflow runs this)

1. `which onchainos` — verify CLI is installed.
2. `OKX_API_KEY` / `OKX_SECRET_KEY` / `OKX_PASSPHRASE` set.
3. `python skills/aegis-blackbox/scripts/logger.py stats` — verify ledger directory.
4. `python skills/aegis-hibernator/scripts/drawdown.py status` — confirm ACTIVE before
   attempting entries.
5. `aegis.config.json` exists; otherwise fall back to `aegis.config.example.json`.

Failures at any step surface to the user; the workflow aborts.
