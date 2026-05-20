# JUDGES.md — criterion-by-criterion map to AEGIS files

AEGIS targets the **Skill Quality Award** (5 000 USDC pool, 10 winners × 500 USDC).
Judging criteria, verbatim: 策略完整性、风险控制框架、执行可靠性、用户安全引导体验、可观测性.

## 1. Strategy completeness — 策略完整性

AEGIS-Fader is a complete signal-to-trade strategy with a defined hypothesis, gate sequence,
attribution loop, and per-source learning via Blackbox decay.

| Element | File |
|---|---|
| Strategy hypothesis | `skills/aegis-fader/SKILL.md` §Skill Routing + `references/crowd-detection.md` |
| Signal aggregation | `skills/aegis-fader/scripts/signal_window.py` |
| Decision tree | `skills/aegis-fader/scripts/fade_score.py::decide_per_token` |
| Gate sequence | `skills/aegis-fader/references/fade-rules.md` |
| Attribution / learning | `skills/aegis-fader/SKILL.md` §Operation Flow Step 3 → 6; `skills/aegis-blackbox/references/decay-metric.md` |
| Sizing math | `skills/aegis-quartermaster/scripts/kelly.py::compute_size` |
| Spot-only, FADE_OPPORTUNITY is log-only | `skills/aegis-fader/references/fade-rules.md` §Side rule |

## 2. Risk-control framework — 风险控制框架

Five orthogonal layers: Sentinel (per-token pre-flight), Hibernator (global kill switch +
WS reactive), Quartermaster (sizing caps), Fader (per-trade gates), Blackbox (decay).

| Layer | File |
|---|---|
| Per-token fragility | `skills/aegis-sentinel/scripts/fragility.py::compose_score` |
| Drawdown freeze | `skills/aegis-hibernator/scripts/drawdown.py::engage` |
| WS reactive triggers | `skills/aegis-hibernator/scripts/ws_watcher.py::match_trigger` |
| Sizing caps + Kelly | `skills/aegis-quartermaster/scripts/kelly.py::compute_size` |
| Per-trade gate order | `skills/aegis-fader/references/fade-rules.md` |
| Refusals (wash/circular/coordinated) | `skills/aegis-fader/SKILL.md` §Safety Guarantees |
| Sticky hibernation | `skills/aegis-hibernator/scripts/drawdown.py::wake` |
| OKX security delegation | `skills/aegis-sentinel/scripts/fragility.py::security_risk_level` |

## 3. Execution reliability — 执行可靠性

| Property | File |
|---|---|
| Idempotent operation IDs | `skills/aegis-fader/scripts/fade_score.py::decision_id` |
| Atomic state writes | `skills/_shared/_aegis_common.py::atomic_write_json` |
| Simulation before broadcast | `skills/aegis-fader/SKILL.md` §Operation Flow Step 3-9; `workflows/full-trading-loop.md` §4c |
| Transport-only retries | `skills/_shared/_aegis_common.py::run_cli` |
| Geo-block convention | `skills/_shared/error-handling.md` §1 |
| Quote freshness | `skills/aegis-fader/SKILL.md` §Global Notes |
| Schema versioning | every state loader; refused on mismatch |
| Atomic JSON / fsync | `skills/_shared/_aegis_common.py::atomic_write_json` |

### Design note — read-only `scan` + explicit broadcast workflow

`aegis-fader scan` runs the **full gate chain end-to-end** (hibernator → signal-window →
per-token sentinel → quartermaster → fader-decision) and emits a structured
`scan_completed` envelope with the candidate list. It does **not** broadcast in any mode,
including `--dry-run`. The broadcast leg (quote → simulate → broadcast → track → attribute)
lives in `workflows/full-trading-loop.md` as a step-by-step operator-runnable sequence.

This split is deliberate:

1. **Judge safety.** Running `aegis-fader scan` is risk-free. A judge can repeatedly
   invoke `scan` against a real wallet without any chance of funds moving. Only the
   explicit workflow can spend.
2. **User-safety guidance.** The rubric's "user safety guidance experience" axis rewards
   making destructive operations explicit. Broadcast is a separate, named flow with
   pre-flight checks (`Step 0`), simulation gate, and operator confirmation — not a
   silent side-effect of the strategy command.
3. **Auditability.** Every gate result, including the SKIP / FOLLOW_LONG / FADE_OPPORTUNITY
   verdict, is logged to `decisions.jsonl` from `scan` alone. Judges can audit the
   strategy's decisions without ever running the broadcast workflow.

`workflows/full-trading-loop.md` walks through the broadcast leg explicitly:
- Step 4a — `onchainos token search` resolves token CAs
- Step 4b — `onchainos swap quote` with honeypot/price-impact gate
- Step 4c — `onchainos gateway simulate` with divergence gate
- Step 4d — `onchainos swap execute` (the only fund-spending command)
- Step 4e — `onchainos gateway orders` for tracking
- Step 6 — `onchainos market portfolio-token-pnl` for attribution after delay

Each step emits the matching event to Blackbox so the same JSONL ledger covers both the
gate-scan and the broadcast leg uniformly.

## 4. User-safety / onboarding — 用户安全引导体验

| Property | File |
|---|---|
| TEE-only signing (never read keys) | `SECURITY.md` |
| Secret redaction | `skills/_shared/_aegis_common.py::redact` |
| Untrusted-content sanitisation | `skills/_shared/prompt-injection.md`; `skills/_shared/_aegis_common.py::sanitize_external` |
| Geo-block surfacing | `skills/_shared/error-handling.md` |
| Bilingual EN/中文 description triggers | every `SKILL.md` frontmatter |
| Pre-flight check | `skills/_shared/preflight.md` |
| Disclaimers | `docs/DISCLAIMERS.md` |
| 60-s demo a judge can run | `docs/DEMO.md` |
| Wake cool-off refusal | `skills/aegis-hibernator/scripts/drawdown.py::wake` |

## 5. Observability — 可观测性

| Surface | File |
|---|---|
| Decision ledger (append-only JSONL) | `skills/aegis-blackbox/references/log-schema.md` |
| Trades ledger | same |
| Signal performance ledger | same |
| Meta ledger (self-instrumentation) | `skills/aegis-blackbox/SKILL.md` §Observability Hooks |
| Decay metric | `skills/aegis-blackbox/scripts/decay.py::compute_decay` |
| Static dashboard | `skills/aegis-blackbox/scripts/dashboard.html` |
| Binding constraint on every size | `skills/aegis-quartermaster/scripts/kelly.py::_binding` |
| Payload digest (not payload) on WS triggers | `skills/aegis-hibernator/scripts/ws_watcher.py::cmd_poll` |
| Corrupt-line handling | `skills/aegis-blackbox/scripts/logger.py::_iter_jsonl` |
| Audit hook for prompt-injection suspects | `skills/_shared/prompt-injection.md` |

## Mapping to repo metadata

- `package.json` declares author, version, keywords (`onchainos`, `solana`, `xlayer`,
  `risk-management`, `kill-switch`).
- `CHANGELOG.md` records the v1.0.0 release and substitutions.
- `LICENSE` is Apache-2.0.
- `.github/workflows/ci.yml` runs `ruff`, `mypy --ignore-missing-imports`, `pytest tests/unit`,
  `pytest tests/integration` and a no-secret audit on every push.

## Reproducing the dry-run

See `docs/DEMO.md`. A judge runs `pytest tests/integration -v` and gets a green report
end-to-end without any OKX credentials (the integration tests use a stubbed `onchainos`
binary). For a real sandbox run, set `OKX_API_KEY` / `OKX_SECRET_KEY` / `OKX_PASSPHRASE`
and run `workflows/dry-run.md` step-by-step.

## Tooling notes

Two tooling/runtime points worth knowing about when reviewing this submission:

**SKILL.md frontmatter `agent:` key.** The master build prompt mandates an
`agent.requires.bins: ["onchainos"]` block in every SKILL.md frontmatter (§6). The OKX
OnchainOS framework honours this key (verified locally — all 22 OKX skills load with the
same key). VS Code's built-in skills extension uses a stricter schema that flags
`agent:` as unknown; this is an IDE-only warning and does not affect the OKX runtime
or the loading behaviour. Judges viewing SKILL.md on GitHub will see no warning.

**Region-dependent live data.** Many `onchainos market/token/memepump/signal` endpoints
return `code=53015` ("DEX not available in your region") when called from
geo-restricted environments. AEGIS handles this everywhere via the canonical
geo-block path in `skills/_shared/error-handling.md`: factor values default to 0.5 in
Sentinel (`reasons: ["geo_block:<factor>"]`), drawdown checks return `indeterminate`
in Hibernator, scan emits `scan_completed` with `status: failed, skip_reason:
signal_window_unavailable` in Fader. The integration test suite (`tests/integration/`)
uses a stubbed `onchainos` binary so the gate logic is exercised without needing
region-unrestricted live data — judges in any region can run the full suite green.
