"""aegis-hibernator drawdown CLI.

Reads realized PnL via onchainos market portfolio-overview / portfolio-recent-pnl, computes a
rolling-window sum, and engages or surfaces hibernation. State is `hibernator.json` (atomic).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[3]))

from skills._shared._aegis_common import (  # noqa: E402
    GEO_BLOCK_MESSAGE,
    SCHEMA_VERSION,
    append_jsonl,
    atomic_write_json,
    blackbox_dir,
    load_config,
    now_ms,
    run_cli,
    state_dir,
)

getcontext().prec = 28

DEFAULT_STATE: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "status": "ACTIVE",
    "since_ts_ms": 0,
    "reason": None,
    "ws_session_ids": [],
    "last_drawdown_check_ts_ms": 0,
    "last_realized_pnl_pct": "0",
    "cool_off_until_ts_ms": 0,
}

_VALID_REASONS: frozenset[str] = frozenset(
    {"drawdown", "dev_sell", "migrating", "ws_lost", "manual", "cluster_shift_gt_10pct"},
)


def load_state() -> dict[str, Any]:
    path = state_dir() / "hibernator.json"
    if not path.is_file():
        return dict(DEFAULT_STATE)
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_STATE)
    if not isinstance(body, dict) or body.get("schema_version") != SCHEMA_VERSION:
        append_jsonl(
            blackbox_dir() / "meta.jsonl",
            {
                "schema_version": SCHEMA_VERSION,
                "ts_ms": now_ms(),
                "skill": "aegis-hibernator",
                "event": "schema_mismatch",
                "file": "hibernator.json",
                "found_version": body.get("schema_version") if isinstance(body, dict) else None,
                "expected_version": SCHEMA_VERSION,
            },
        )
        return dict(DEFAULT_STATE)
    merged = dict(DEFAULT_STATE)
    merged.update(body)
    return merged


def save_state(state: dict[str, Any]) -> None:
    atomic_write_json(state_dir() / "hibernator.json", state)


def rolling_pnl_pct(
    rows: Iterable[dict[str, Any]],
    *,
    now_ts: int,
    window_hours: int,
    window_trades: int,
) -> tuple[Decimal | None, int]:
    """Return (summed realized PnL pct, count) over the window.

    Uses the larger of: trades in the last `window_hours`, or the last `window_trades` rows.
    """
    cutoff_ms = now_ts - window_hours * 3_600_000
    cleaned: list[tuple[int, Decimal]] = []
    for row in rows:
        ts = int(row.get("ts_ms", 0))
        pnl = row.get("realizedPnlPercent")
        if pnl is None:
            pnl = row.get("realized_pnl_pct")
        if pnl is None:
            continue
        try:
            value = Decimal(str(pnl))
        except Exception:
            continue
        cleaned.append((ts, value))
    cleaned.sort(key=lambda t: t[0])
    by_hours = [v for ts, v in cleaned if ts >= cutoff_ms]
    by_trades = [v for _, v in cleaned[-window_trades:]]
    use = by_hours if len(by_hours) >= len(by_trades) else by_trades
    if len(use) < 3:
        return None, len(use)
    total = sum(use, Decimal("0"))
    return total, len(use)


def engage(reason: str, *, now: int, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_config()["hibernator"]
    state = load_state()
    if reason not in _VALID_REASONS:
        raise ValueError(f"unknown reason: {reason}")
    cool_off_minutes = int(cfg["cool_off_minutes"])
    state["status"] = "HIBERNATED"
    state["since_ts_ms"] = now
    state["reason"] = reason
    state["cool_off_until_ts_ms"] = now + cool_off_minutes * 60_000
    if extra:
        for k in ("last_realized_pnl_pct",):
            if k in extra:
                state[k] = extra[k]
    save_state(state)
    append_jsonl(
        blackbox_dir() / "decisions.jsonl",
        {
            "schema_version": SCHEMA_VERSION,
            "ts_ms": now,
            "skill": "aegis-hibernator",
            "event": "hibernation_engaged",
            "reason": reason,
            "cool_off_until_ts_ms": state["cool_off_until_ts_ms"],
            "last_realized_pnl_pct": state.get("last_realized_pnl_pct"),
        },
    )
    return state


def wake(*, now: int) -> tuple[bool, str, dict[str, Any]]:
    state = load_state()
    if state["status"] == "ACTIVE":
        return True, "already ACTIVE", state
    if now < int(state.get("cool_off_until_ts_ms", 0)):
        iso = datetime.fromtimestamp(
            state["cool_off_until_ts_ms"] / 1000, tz=UTC,
        ).isoformat()
        return (
            False,
            f"Cool-off active. Wake available at {iso}.",
            state,
        )
    state["status"] = "ACTIVE"
    state["reason"] = None
    save_state(state)
    append_jsonl(
        blackbox_dir() / "decisions.jsonl",
        {
            "schema_version": SCHEMA_VERSION,
            "ts_ms": now,
            "skill": "aegis-hibernator",
            "event": "hibernation_cleared",
            "after_cool_off_ts_ms": state.get("cool_off_until_ts_ms"),
        },
    )
    return True, "woken", state


def cmd_status(_: argparse.Namespace) -> int:
    state = load_state()
    sys.stdout.write(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    return 0


def cmd_sleep(args: argparse.Namespace) -> int:
    state = engage(args.reason, now=now_ms())
    sys.stdout.write(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    return 0


def cmd_wake(_: argparse.Namespace) -> int:
    ok, msg, state = wake(now=now_ms())
    out = {"ok": ok, "msg": msg, "state": state}
    sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return 0 if ok else 1


def cmd_check(args: argparse.Namespace) -> int:
    cfg = load_config()["hibernator"]
    res = run_cli(
        [
            "market", "portfolio-recent-pnl",
            "--address", args.wallet,
            "--chains", args.chain,
        ],
    )
    if not res.ok:
        # geo-block or transport — surface canonical msg, leave status alone
        state = load_state()
        state["last_drawdown_check_ts_ms"] = now_ms()
        save_state(state)
        out = {
            "ok": False,
            "msg": res.msg or GEO_BLOCK_MESSAGE,
            "indeterminate": True,
            "status": state["status"],
        }
        sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
        return 1
    rows = _extract_pnl_rows(res.data)
    summed, n = rolling_pnl_pct(
        rows,
        now_ts=now_ms(),
        window_hours=int(cfg["rolling_window_hours"]),
        window_trades=int(cfg["rolling_window_trades"]),
    )
    if summed is None:
        state = load_state()
        state["last_drawdown_check_ts_ms"] = now_ms()
        save_state(state)
        out = {
            "ok": True,
            "indeterminate": True,
            "rows_in_window": n,
            "status": state["status"],
        }
        sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
        return 0
    threshold = -Decimal(str(cfg["max_rolling_drawdown_pct"]))
    state = load_state()
    state["last_drawdown_check_ts_ms"] = now_ms()
    state["last_realized_pnl_pct"] = f"{summed:.6f}"
    save_state(state)
    if summed <= threshold and state["status"] == "ACTIVE":
        state = engage(
            "drawdown",
            now=now_ms(),
            extra={"last_realized_pnl_pct": f"{summed:.6f}"},
        )
    out = {
        "ok": True,
        "summed_pnl_pct": f"{summed:.6f}",
        "rows_in_window": n,
        "threshold": f"{threshold:.6f}",
        "status": state["status"],
        "reason": state.get("reason"),
    }
    sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return 0


def _extract_pnl_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "items", "result"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
        # Sometimes a single object — wrap it
        if any(k in payload for k in ("realizedPnlPercent", "realized_pnl_pct")):
            return [payload]
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-hibernator drawdown")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_st = sub.add_parser("status", help="show hibernation status")
    p_st.set_defaults(func=cmd_status)
    p_ch = sub.add_parser("check", help="recompute drawdown and engage if breached")
    p_ch.add_argument("--wallet", required=True)
    p_ch.add_argument("--chain", required=True, choices=["solana", "xlayer"])
    p_ch.set_defaults(func=cmd_check)
    p_sl = sub.add_parser("sleep", help="manually engage hibernation")
    p_sl.add_argument("--reason", required=True, choices=sorted(_VALID_REASONS))
    p_sl.set_defaults(func=cmd_sleep)
    p_wk = sub.add_parser("wake", help="clear hibernation after cool-off")
    p_wk.set_defaults(func=cmd_wake)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
