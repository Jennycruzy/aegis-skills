# recovery-rules.md

## Wake protocol

Hibernation is sticky. Clearing it requires:

1. The cool-off window has elapsed: `now ≥ cool_off_until_ts_ms`.
2. The operator runs `drawdown.py wake` explicitly. The framework will NOT auto-wake on any
   schedule or signal.

`cool_off_until_ts_ms` is set to `since_ts_ms + hibernator.cool_off_minutes * 60_000` when
hibernation is engaged. Default `cool_off_minutes = 60`.

## After wake

- `status` flips to `ACTIVE`.
- `reason` is set to `null`.
- `ws_session_ids` are preserved so the watcher can resume.
- `aegis-fader scan` may now find entries again.

If the user attempts `wake` before cool-off, the command fails with:

```
Cool-off active. Wake available at <ISO-8601 of cool_off_until_ts_ms>.
```

## Auto-close on hibernate

When `auto_close_on_hibernate=true`, hibernation engagement triggers a sequential close of
every open position before the status is reported back to the operator. The close honours:

- Honeypot WARN on sell — Hibernator proceeds anyway to exit risk, with a `gate_warned`
  event for transparency.
- Simulation divergence — abort the single close, log `close_failed`, continue with next.
- Geo-block — abort all closes (cannot exit safely); set a `close_unavailable` flag.

Auto-close is OFF by default. Operators should turn it on only after testing the close-all
flow on the OKX sandbox.

## Manual override

`drawdown.py sleep --reason <r>` and `drawdown.py wake` are the operator overrides. They are
the only paths that flip status without going through the automatic triggers. Both emit
audit events.
