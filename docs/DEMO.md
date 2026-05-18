# DEMO.md — 60-second AEGIS walkthrough

Copy-paste in order. No edits required beyond the wallet address.

```bash
# 0. Install
git clone <this repo> && cd aegis-skills
cp .env.example .env
# (fill in OKX sandbox creds)
python -m pip install ruff mypy pytest
```

## Tick 1 (10 s) — Status check

```bash
python skills/aegis-hibernator/scripts/drawdown.py status
```

Expected: `"status": "ACTIVE"` and `"reason": null`.

## Tick 2 (20 s) — Dry run

```bash
python skills/aegis-fader/scripts/fade_score.py scan \
    --chain solana --window-minutes 60 --dry-run
```

Expected: a `scan_invoked` row in `~/.aegis/state/blackbox/decisions.jsonl` with
`"dry_run": true`. No swap executed.

## Tick 3 (10 s) — Open the dashboard

```bash
xdg-open skills/aegis-blackbox/scripts/dashboard.html   # Linux
open      skills/aegis-blackbox/scripts/dashboard.html  # macOS
```

Expected:

- header KPIs populated;
- "decisions" > 0;
- hibernation panel shows `ACTIVE`.

## Tick 4 (10 s) — Force a kill switch test

```bash
python skills/aegis-hibernator/scripts/drawdown.py sleep --reason manual
python skills/aegis-hibernator/scripts/drawdown.py status
```

Expected: `status: HIBERNATED, reason: manual, cool_off_until_ts_ms: <60 min from now>`.

## Tick 5 (5 s) — Confirm Fader refuses on hibernation

Re-run the dry-run scan. Inspect the latest `decisions.jsonl` row: subsequent invocations log
`scan_invoked` but any `candidate_evaluated` would show `skip_reason: hibernated` in a live
run (the dry-run command exits at scan log; the gate is exercised in the per-candidate path).

## Tick 6 (5 s) — Run all tests

```bash
pytest tests/unit -v
pytest tests/integration -v
```

Expected: all green.

## Tick 7 — Wake (do this last)

```bash
python skills/aegis-hibernator/scripts/drawdown.py wake
```

Expected: refused with cool-off message — *that's the whole point*. The kill switch is
sticky.
