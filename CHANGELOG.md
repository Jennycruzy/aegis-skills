# Changelog

All notable changes to this project will be documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/) and this project adheres to
[Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-05-18

### Added
- Initial release of AEGIS — five composable OnchainOS Skills:
  - `aegis-fader` — counter-smart-money strategy.
  - `aegis-sentinel` — continuous fragility score per token.
  - `aegis-hibernator` — drawdown + WebSocket reactive kill switch.
  - `aegis-quartermaster` — Bayesian-shrunk fractional Kelly sizing.
  - `aegis-blackbox` — structured JSONL logs, decay metric, static dashboard.
- `aegis.config.example.json` with all thresholds.
- `_shared/` references (preflight, chain-support, sol-addresses, error-handling,
  state-schema, prompt-injection).
- Workflows: `full-trading-loop.md`, `dry-run.md`, `safe-shutdown.md`, `INDEX.md`.
- Unit + integration tests under `tests/`.
- CI via `.github/workflows/ci.yml` (ruff, mypy --ignore-missing-imports, pytest).
- Built for OKX Agentic Wallet Trading Competition — Skill Quality Award track.

### Substitutions
- `onchainos market signal-list` → `onchainos signal list` (real namespace).
- `onchainos wallet portfolio-pnl` → `onchainos market portfolio-overview` +
  `portfolio-recent-pnl` (closest realized-PnL surface).
