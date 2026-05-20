# tests/

Unit tests live under `tests/unit/`. Integration tests live under `tests/integration/` and call
real `onchainos` commands via the OKX sandbox; they are skipped automatically when
`OKX_API_KEY` is unset.

## Layout

```
tests/
├── _loader.py                 # path-based importer for hyphenated skill folders
├── conftest.py                # repo-root fixtures (aegis_tmp_home, aegis_config)
├── unit/
│   ├── test_decay.py          # aegis-blackbox decay metric
│   ├── test_kelly.py          # aegis-quartermaster Kelly + caps
│   ├── test_fragility.py      # aegis-sentinel fragility composition
│   ├── test_drawdown.py       # aegis-hibernator rolling drawdown
│   └── test_fade_score.py     # aegis-fader crowdedness + decision logic
├── integration/
│   ├── test_full_loop_dry_run.py
│   └── test_hibernation_trigger.py
└── fixtures/
    ├── signals_crowded.json
    ├── signals_lonely.json
    ├── token_fragile.json
    └── token_clean.json
```

## Running

```bash
pytest tests/unit -v
pytest tests/integration -v   # skipped without OKX_API_KEY / OKX_SECRET_KEY / OKX_PASSPHRASE
ruff check .
mypy skills/ --ignore-missing-imports
```

## Conventions

- Tests **must not** call real `onchainos` commands in `tests/unit`. Mock or import pure-math
  modules.
- Integration tests **must** check sandbox creds at module level and call `pytest.skip(...)`
  when missing.
- Tests construct deterministic UTC ms via the shared `_NOW` constant — they do not depend on
  wall-clock time.
