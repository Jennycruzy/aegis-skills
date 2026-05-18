# CONTRIBUTING.md

AEGIS is a five-Skill OnchainOS framework. Contributions are welcome via PR.

## Ground rules

1. **OnchainOS only.** Every market read, swap, broadcast, simulation, holder query, signal feed,
   security check, and WebSocket subscription MUST go through the `onchainos` CLI. No external
   HTTP, no scraping.
2. **Match the OKX house style.** Every SKILL.md follows the section order in
   `NOTES_FROM_REPO.md` §2. New commands referenced in a SKILL.md MUST exist in the OKX reference
   repo and be added to `NOTES_FROM_REPO.md` §3.
3. **No hardcoded thresholds.** Every numeric risk threshold lives in `aegis.config.json`.
4. **Schema-versioned state.** Bump `schema_version` whenever a state file shape changes.
5. **Decimal not float** for any value that flows into sizing.
6. **No new top-level dependencies** without justification. AEGIS is pure stdlib +
   `structlog` + `pytest`/`ruff`/`mypy`.

## Local checks

```bash
ruff check .
mypy --strict skills/
pytest tests/unit -v
pytest tests/integration -v   # requires OKX sandbox env vars
```

CI runs the same on every push (`.github/workflows/ci.yml`).

## SKILL.md description budget

Frontmatter `description` ≤ **900 chars**. Bilingual EN/中文 trigger phrases. Names sibling
Skills the agent must not re-implement.

## PR checklist

- [ ] All new CLI invocations exist in `NOTES_FROM_REPO.md` (else add a substitution row to
      `docs/SUBSTITUTIONS.md`).
- [ ] All new config keys appear in `aegis.config.example.json` with a sensible default.
- [ ] All new state-file paths match `~/.aegis/state/<file>.json`.
- [ ] Unit tests cover the new behaviour (zero / boundary / negative paths).
- [ ] `ruff`, `mypy --strict`, `pytest` are green locally.
- [ ] No secrets in the diff (`OKX_*`, base58, 64-hex).
