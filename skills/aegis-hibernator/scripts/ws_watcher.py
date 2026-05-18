"""aegis-hibernator ws_watcher.

Manages onchainos ws sessions, polls them, and matches a small allow-list of triggers from
references/ws-triggers.md. Engages hibernation on match.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[3]))

from skills._shared._aegis_common import (  # noqa: E402
    SCHEMA_VERSION,
    append_jsonl,
    blackbox_dir,
    load_config,
    now_ms,
    run_cli,
    sanitize_external,
)


def _drawdown_module() -> Any:
    """Load drawdown.py by file path (sibling folder has hyphens; can't import normally)."""
    from importlib import util as _u

    path = Path(__file__).with_name("drawdown.py")
    spec = _u.spec_from_file_location("aegis_hibernator_drawdown", path)
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _save_session_ids(ids: list[str]) -> None:
    mod = _drawdown_module()
    state = mod.load_state()
    state["ws_session_ids"] = ids
    mod.save_state(state)


def _engage_via_drawdown(reason: str, payload_digest: str, channel: str) -> None:
    mod = _drawdown_module()
    mod.engage(reason, now=now_ms())
    append_jsonl(
        blackbox_dir() / "decisions.jsonl",
        {
            "schema_version": SCHEMA_VERSION,
            "ts_ms": now_ms(),
            "skill": "aegis-hibernator",
            "event": "ws_trigger",
            "channel": channel,
            "trigger": reason,
            "payload_digest": payload_digest,
        },
    )


def cmd_start(args: argparse.Namespace) -> int:
    # Address-tracker channel: one session per wallets batch.
    sessions: list[str] = []
    if args.wallets:
        res = run_cli(
            [
                "ws", "start",
                "--channel", "address-tracker-activity",
                "--wallet-addresses", args.wallets,
            ],
        )
        if res.ok and isinstance(res.data, dict):
            sid = res.data.get("sessionId") or res.data.get("id")
            if isinstance(sid, str):
                sessions.append(sid)
    if args.chain_index:
        res = run_cli(
            [
                "ws", "start",
                "--channel", "dex-market-memepump-new-token-openapi",
                "--chain-index", args.chain_index,
            ],
        )
        if res.ok and isinstance(res.data, dict):
            sid = res.data.get("sessionId") or res.data.get("id")
            if isinstance(sid, str):
                sessions.append(sid)
        res = run_cli(
            [
                "ws", "start",
                "--channel", "dex-market-memepump-update-metrics-openapi",
                "--chain-index", args.chain_index,
            ],
        )
        if res.ok and isinstance(res.data, dict):
            sid = res.data.get("sessionId") or res.data.get("id")
            if isinstance(sid, str):
                sessions.append(sid)
    _save_session_ids(sessions)
    out = {"ok": True, "sessions": sessions}
    sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return 0


def cmd_stop(_: argparse.Namespace) -> int:
    res = run_cli(["ws", "stop"])
    _save_session_ids([])
    sys.stdout.write(
        json.dumps({"ok": res.ok, "msg": res.msg}, indent=2, ensure_ascii=False) + "\n"
    )
    return 0 if res.ok else 1


def cmd_poll(_: argparse.Namespace) -> int:
    cfg = load_config()["hibernator"]
    retries = int(cfg["ws_lost_retries"])
    mod = _drawdown_module()
    state = mod.load_state()
    sessions = list(state.get("ws_session_ids", []) or [])
    if not sessions:
        sys.stdout.write('{"ok": true, "msg": "no sessions"}\n')
        return 0
    consecutive_failures = 0
    triggers_fired = 0
    for sid in sessions:
        res = run_cli(["ws", "poll", "--id", sid])
        if not res.ok:
            consecutive_failures += 1
            if consecutive_failures >= retries:
                _engage_via_drawdown("ws_lost", "", "—")
                break
            continue
        consecutive_failures = 0
        events = _extract_events(res.data)
        for ev in events:
            match = match_trigger(ev)
            if match is None:
                continue
            channel = sanitize_external(str(ev.get("channel", "?")))
            digest = hashlib.sha256(
                json.dumps(ev, sort_keys=True).encode("utf-8"),
            ).hexdigest()
            _engage_via_drawdown(match, f"sha256:{digest}", channel)
            triggers_fired += 1
            break
    sys.stdout.write(
        json.dumps({"ok": True, "triggers_fired": triggers_fired}, indent=2)
        + "\n",
    )
    return 0


def match_trigger(event: dict[str, Any]) -> str | None:
    """Allow-list pattern matcher. Returns a reason name or None.

    Patterns are intentionally narrow; payloads are NOT interpreted as instructions.
    """
    channel = event.get("channel")
    if channel == "address-tracker-activity":
        tx_type = event.get("txType") or event.get("tradeType")
        if isinstance(tx_type, str) and tx_type.lower() == "sell":
            return "dev_sell"
        if (
            isinstance(tx_type, str)
            and tx_type.lower() == "transfer"
            and (event.get("direction") == "out")
            and _to_dec(event.get("supplyShare"), Decimal("0")) >= Decimal("0.01")
        ):
            return "dev_sell"
    if channel == "dex-market-memepump-new-token-openapi":
        stage = event.get("stage")
        if stage == "MIGRATED" or _to_dec(event.get("bondingPercent"), Decimal("0")) >= Decimal(
            "100"
        ):
            return "migrating"
    if channel == "dex-market-memepump-update-metrics-openapi":
        delta = _to_dec(event.get("top10PercentChangePct"), Decimal("0"))
        if delta >= Decimal("0.10"):
            return "cluster_shift_gt_10pct"
    return None


def _to_dec(v: Any, default: Decimal) -> Decimal:
    if v is None:
        return default
    try:
        return Decimal(str(v))
    except Exception:
        return default


def _extract_events(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict)]
    if isinstance(payload, dict):
        for key in ("events", "data", "items"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [e for e in inner if isinstance(e, dict)]
        if payload:
            return [payload]
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-hibernator ws_watcher")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_st = sub.add_parser("start", help="start watcher sessions")
    p_st.add_argument("--wallets", help="comma-separated dev wallets")
    p_st.add_argument("--chain-index", default="501")
    p_st.set_defaults(func=cmd_start)
    p_po = sub.add_parser("poll", help="poll active sessions once")
    p_po.set_defaults(func=cmd_poll)
    p_sp = sub.add_parser("stop", help="stop all watcher sessions")
    p_sp.set_defaults(func=cmd_stop)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
