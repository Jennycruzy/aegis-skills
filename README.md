# AEGIS — Agentic Execution Guardrails & Intelligence Stack

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Built on OnchainOS](https://img.shields.io/badge/built%20on-OnchainOS-111.svg)](https://github.com/okx/onchainos-skills)
[![Skills](https://img.shields.io/badge/skills-5-success.svg)](skills/)
[![Tests](https://img.shields.io/badge/tests-63%20unit%20%2F%209%20integration-success.svg)](tests/)
[![Chains](https://img.shields.io/badge/chains-Solana%20%E2%80%A2%20X%20Layer-purple.svg)](skills/_shared/chain-support.md)

> Five composable OnchainOS Skills for safety-first agentic trading.
> Submitted to the **OKX Agentic Wallet Trading Competition — Skill Quality Award** track.

---

## TL;DR

AEGIS is a complete trading loop that fades crowded smart-money signals, follows lonely
high-quality ones, sizes via Bayesian-shrunk fractional Kelly, BLOCKS or SIZES_DOWN per
continuous token fragility, refuses entries during hibernation, and logs every gate, every
trade, every realized PnL pct into append-only JSONL ledgers that drive a static
single-file dashboard.

Every market read, swap, broadcast, simulation, signal feed, holder query, and security
check goes through the `onchainos` CLI. AEGIS adds zero new on-chain code.

---

## Why AEGIS

| Pain point | AEGIS layer |
|---|---|
| Smart-money "alpha" is contaminated by the late tape | `aegis-fader` measures **crowdedness** + **source diversity** |
| Risk is one-dimensional in most strategies | `aegis-sentinel` decomposes into 5 weighted factors |
| Drawdowns spiral without a hard stop | `aegis-hibernator` is sticky — never auto-clears |
| Bet sizing is intuition-driven | `aegis-quartermaster` Bayesian-shrunk fractional Kelly + binding-constraint audit trail |
| You can't see what the agent did | `aegis-blackbox` JSONL + static HTML dashboard |

---

## Architecture

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

Detailed schemas, data contracts, and event taxonomy: [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Quick start

```bash
# 1. Install
git clone https://github.com/aegis/aegis-skills
cd aegis-skills
cp .env.example .env
# (fill in OKX sandbox creds: OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE)

# 2. Verify OnchainOS CLI is on PATH
which onchainos || npx skills add okx/onchainos-skills

# 3. Run tests
python -m pip install ruff mypy pytest
ruff check .
mypy --strict skills/
pytest tests/unit -v
pytest tests/integration -v

# 4. Dry-run the strategy
python skills/aegis-fader/scripts/fade_score.py scan \
    --chain solana --window-minutes 60 --dry-run

# 5. Open the dashboard
#    Modern browsers block file:// fetch — serve the JSONL dir over HTTP.
mkdir -p ~/.aegis/state/blackbox
cp skills/aegis-blackbox/scripts/dashboard.html ~/.aegis/state/blackbox/
( cd ~/.aegis/state/blackbox && python -m http.server 8000 ) &
xdg-open http://localhost:8000/dashboard.html
```

For a 60-second judge-friendly walkthrough, see [docs/DEMO.md](docs/DEMO.md).

---

## The five Skills

| Skill | Slot | One-line |
|---|---|---|
| [`aegis-fader`](skills/aegis-fader/SKILL.md) | Strategy | Fades crowded SM/KOL/whale signals; follows lonely diverse ones. Spot-only. |
| [`aegis-sentinel`](skills/aegis-sentinel/SKILL.md) | Pre-flight | Continuous fragility score in [0,1] across 5 factors + OKX-security CRITICAL override. |
| [`aegis-hibernator`](skills/aegis-hibernator/SKILL.md) | Risk control | Sticky kill switch: realized rolling drawdown + WS triggers on dev sell, migration, cluster shift, ws lost. |
| [`aegis-quartermaster`](skills/aegis-quartermaster/SKILL.md) | Sizing | Bayesian-shrunk fractional Kelly with wallet, fragility, and minimum caps. Reports the **binding constraint** on every size. |
| [`aegis-blackbox`](skills/aegis-blackbox/SKILL.md) | Observability | Append-only JSONL ledgers, signal-source decay metric, single-file static dashboard. |

Each is independently useful and composes into the full loop in
[workflows/full-trading-loop.md](workflows/full-trading-loop.md).

---

## Composition: the full trading loop

```
Blackbox init → Hibernator status → Fader signal scan
  → for each candidate:
      → Sentinel score (fragility + decision)
      → Quartermaster size (binding constraint)
      → Fader decide (gate sequence)
      → quote → simulate → broadcast → track
      → log to Blackbox (decisions + trades)
  → Hibernator drawdown re-check
  → schedule attribution
```

The workflow file at [workflows/full-trading-loop.md](workflows/full-trading-loop.md)
contains the step-by-step CLI invocations. The pure-function decision tree lives in
`skills/aegis-fader/scripts/fade_score.py::decide_per_token` and is exhaustively
unit-tested.

---

## Configuration

A single [`aegis.config.example.json`](aegis.config.example.json) holds every threshold.
Copy to `aegis.config.json` and tune. No threshold is hardcoded in Python. Schema documented
inline in `ARCHITECTURE.md` §6.

Key knobs:

| Key | Default | Effect |
|---|---|---|
| `fader.crowd_threshold` | 0.70 | Above this, candidate is "crowded" → FADE_OPPORTUNITY |
| `fader.min_source_diversity` | 3 | Required distinct walletType count for FOLLOW_LONG |
| `fader.max_position_pct` | 0.05 | Wallet-pct cap on every entry |
| `fader.max_daily_entries` | 20 | Daily entry cap |
| `sentinel.block_threshold` | 0.50 | Fragility ≥ this → BLOCK |
| `sentinel.size_down_threshold` | 0.30 | Fragility in `[0.30, 0.50)` → SIZE_DOWN |
| `hibernator.max_rolling_drawdown_pct` | 0.15 | Engages hibernation on breach |
| `hibernator.cool_off_minutes` | 60 | Minimum elapsed time before `wake` works |
| `quartermaster.kelly_fraction` | 0.25 | Fractional Kelly multiplier |
| `quartermaster.shrinkage_alpha` / `beta` | 1 / 4 | Bayesian shrinkage prior |
| `blackbox.retire_threshold` / `monitor_threshold` | 1.0 / 0.5 | Decay-band cutoffs |

---

## Safety model

| Guarantee | Enforcement |
|---|---|
| Private keys never leave the OKX TEE | AEGIS calls `swap execute` and `gateway broadcast` only; never signs locally |
| No private-key path in logs | `skills/_shared/_aegis_common.py::redact` strips 64-hex, base58 ≥ 40, and `OKX_*` env values from every error surface |
| No interpretation of untrusted CLI strings | `sanitize_external` + dashboard renders via `textContent`, never `innerHTML` |
| Every trade simulated before broadcast | `gateway simulate` → divergence check → broadcast |
| No wash / circular / coordinated trading | Refused at the Fader boundary; documented in `aegis-fader/SKILL.md` §Safety Guarantees |
| Geo-block surfaced consistently | Codes 50125 / 80001 → canonical user-facing message |
| Sticky hibernation | Never auto-clears; cool-off + explicit `wake` |
| Atomic state writes | `<file>.tmp` → `fsync` → `os.replace` |
| Schema-versioned state | Unknown `schema_version` → refuse to load |

Detailed threat model: [SECURITY.md](SECURITY.md).

---

## Observability

Three append-only JSONL ledgers in `~/.aegis/state/blackbox/`:

- `decisions.jsonl` — every gate fired, decision made, skip recorded.
- `trades.jsonl` — every executed trade with full attribution.
- `signal_performance.jsonl` — per-source forward-return rows feeding the decay metric.

A static HTML dashboard reads them via `fetch()` over a one-line `python -m http.server` —
no build step, no framework, single file. Modern browsers block `file://` fetch, so the
Quickstart copies `dashboard.html` next to the JSONL files and serves on
`http://localhost:8000`.

Decay metric formula (`skills/aegis-blackbox/references/decay-metric.md`):

```
decay_score = max(0, (long_term_mean − recent_mean) / max(0.001, long_term_std))
```

Classification bands (configurable):
- `decay_score ≥ 1.0` → `RETIRE` — AEGIS-Fader excludes the source.
- `decay_score ≥ 0.5` → `MONITOR` — kept, flagged on the dashboard.
- otherwise → `ACTIVE`.

---

## Testing

```
tests/
├── unit/                                  # 63 tests
│   ├── test_decay.py
│   ├── test_drawdown.py
│   ├── test_fade_score.py
│   ├── test_fragility.py
│   └── test_kelly.py
├── integration/                           # 9 tests (CLI stub; no sandbox keys needed)
│   ├── test_full_loop_dry_run.py
│   └── test_hibernation_trigger.py
└── fixtures/
    ├── signals_crowded.json
    ├── signals_lonely.json
    ├── token_fragile.json
    └── token_clean.json
```

Each pure-function decision point is unit-tested. The dry-run integration test exercises
every AEGIS Python script end-to-end via a synthetic `onchainos` shell stub.

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs:
- `ruff check .`
- `mypy --strict skills/`
- `pytest tests/unit -v`
- `pytest tests/integration -v`
- No-secret audit + SKILL.md description-length budget.

---

## Demo

See [docs/DEMO.md](docs/DEMO.md) — a 60-second copy-paste sequence a judge can follow.

---

## Mapping to judging criteria

| Criterion | Where |
|---|---|
| Strategy completeness — 策略完整性 | `skills/aegis-fader/*`, `references/crowd-detection.md`, `fade-rules.md` |
| Risk-control framework — 风险控制框架 | `skills/aegis-sentinel/*`, `skills/aegis-hibernator/*`, `skills/aegis-quartermaster/*`, `aegis-fader/references/fade-rules.md` |
| Execution reliability — 执行可靠性 | `skills/_shared/_aegis_common.py`, `skills/_shared/error-handling.md`, simulate-before-broadcast in `workflows/full-trading-loop.md` |
| User-safety / onboarding — 用户安全引导体验 | `SECURITY.md`, `docs/DISCLAIMERS.md`, `docs/DEMO.md`, bilingual frontmatter in every `SKILL.md` |
| Observability — 可观测性 | `skills/aegis-blackbox/*`, `dashboard.html`, every `_shared/log-schema.md` row |

Detailed file:line map: [docs/JUDGES.md](docs/JUDGES.md).

---

## Limitations and non-goals

- AEGIS does **not** ship a backtester. See [docs/ROADMAP.md](docs/ROADMAP.md).
- AEGIS does **not** open short positions. FADE_OPPORTUNITY is a log-only signal.
- AEGIS runs **only** on Solana and X Layer per competition scope.
- AEGIS does **not** reimplement honeypot / tax / phishing detection — it calls
  `okx-security` and `okx-dex-swap`'s built-in gates.
- AEGIS is **not** a server. The dashboard is one static HTML file.
- AEGIS **realized PnL only** — per the competition rule, unrealized is ignored.

---

## Security

See [SECURITY.md](SECURITY.md). To report a vulnerability privately, open a private GitHub
issue or contact the maintainers listed in `package.json`.

---

## Disclaimers

[docs/DISCLAIMERS.md](docs/DISCLAIMERS.md). In short: AEGIS is software, not financial advice;
AI outputs can be wrong; crypto is volatile; you are responsible for your funds.

---

## License

[Apache-2.0](LICENSE). © 2026 AEGIS contributors.
