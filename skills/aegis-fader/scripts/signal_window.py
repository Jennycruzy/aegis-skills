"""aegis-fader signal_window.

Pure aggregation of an `onchainos signal list` response into per-token metrics. The CLI call
itself lives in fade_score.py; this module is the pure-function aggregator used by both the
CLI command and unit tests.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[3]))

from skills._shared._aegis_common import (  # noqa: E402
    SCHEMA_VERSION,
    blackbox_dir,
    now_ms,
    run_cli,
)

_WALLET_TYPE_NAMES: dict[int, str] = {1: "smart_money", 2: "kol", 3: "whale"}


def _wallet_type_name(value: Any) -> str:
    try:
        return _WALLET_TYPE_NAMES.get(int(value), "unknown")
    except (TypeError, ValueError):
        return "unknown"


def _source_id(signal: dict[str, Any]) -> str:
    wt = _wallet_type_name(signal.get("walletType"))
    addr = signal.get("walletAddress") or signal.get("wallet") or "unknown"
    return f"{wt}:{addr}"


def load_retire_set() -> set[str]:
    report_path = blackbox_dir() / "decay_report.json"
    if not report_path.is_file():
        return set()
    try:
        body = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    out: set[str] = set()
    for source_id, info in (body.get("sources") or {}).items():
        if isinstance(info, dict) and info.get("band") == "RETIRE":
            out.add(source_id)
    return out


def aggregate(
    signals: Iterable[dict[str, Any]],
    *,
    window_start_ms: int,
    window_end_ms: int,
    retire_sources: set[str] | None = None,
) -> dict[str, Any]:
    retire = retire_sources or set()
    by_token: dict[str, dict[str, Any]] = {}
    for s in signals:
        ts = int(s.get("ts_ms", 0))
        if ts < window_start_ms or ts > window_end_ms:
            continue
        sid = _source_id(s)
        if sid in retire:
            continue
        token = s.get("token") or s.get("tokenAddress")
        if not isinstance(token, str):
            continue
        entry = by_token.setdefault(
            token,
            {
                "token": token,
                "signal_count": 0,
                "wallet_types": set(),
                "source_ids": set(),
                "first_ts_ms": ts,
                "last_ts_ms": ts,
            },
        )
        entry["signal_count"] += 1
        entry["wallet_types"].add(_wallet_type_name(s.get("walletType")))
        entry["source_ids"].add(sid)
        entry["first_ts_ms"] = min(entry["first_ts_ms"], ts)
        entry["last_ts_ms"] = max(entry["last_ts_ms"], ts)
    if not by_token:
        return {
            "window_start_ms": window_start_ms,
            "window_end_ms": window_end_ms,
            "max_signal_count": 0,
            "tokens": [],
        }
    max_count = max(int(v["signal_count"]) for v in by_token.values())
    out_tokens: list[dict[str, Any]] = []
    for entry in by_token.values():
        signal_count = int(entry["signal_count"])
        crowdedness = (
            Decimal(signal_count) / Decimal(max(max_count, 1))
            if max_count
            else Decimal("0")
        )
        out_tokens.append(
            {
                "token": entry["token"],
                "signal_count": signal_count,
                "source_diversity": len(entry["wallet_types"]),
                "wallet_types": sorted(entry["wallet_types"]),
                "source_ids": sorted(entry["source_ids"]),
                "crowdedness": f"{crowdedness:.4f}",
                "first_ts_ms": entry["first_ts_ms"],
                "last_ts_ms": entry["last_ts_ms"],
            }
        )
    out_tokens.sort(key=lambda t: int(t["signal_count"]), reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "window_start_ms": window_start_ms,
        "window_end_ms": window_end_ms,
        "max_signal_count": max_count,
        "tokens": out_tokens,
    }


def cmd_snapshot(args: argparse.Namespace) -> int:
    now = now_ms()
    window_ms = int(args.window_minutes) * 60_000
    window_start = (now // 10_000) * 10_000 - window_ms
    window_end = now
    res = run_cli(
        ["signal", "list", "--chain", args.chain, "--wallet-type", "1,2,3"],
    )
    if not res.ok:
        sys.stdout.write(
            json.dumps({"ok": False, "msg": res.msg, "code": res.code}, indent=2) + "\n",
        )
        return 1
    rows = _extract_signal_rows(res.data)
    out = aggregate(
        rows,
        window_start_ms=window_start,
        window_end_ms=window_end,
        retire_sources=load_retire_set(),
    )
    sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return 0


def _extract_signal_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "items", "signals"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
        if "token" in payload:
            return [payload]
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-fader signal_window")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sn = sub.add_parser("snapshot", help="raw aggregation of the signal window")
    p_sn.add_argument("--chain", required=True, choices=["solana", "xlayer"])
    p_sn.add_argument("--window-minutes", type=int, default=60)
    p_sn.set_defaults(func=cmd_snapshot)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
