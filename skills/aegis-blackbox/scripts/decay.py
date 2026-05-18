"""aegis-blackbox decay metric.

Reads signal_performance.jsonl, classifies each distinct signal source as RETIRE / MONITOR /
ACTIVE per references/decay-metric.md, writes decay_report.json atomically.

Pure math: takes pre-computed forward returns from signal_performance.jsonl. The forward-return
collection step is performed by aegis-fader after each entry decision (see attribution flow).
This file does not call any onchainos CLI directly; the optional `--recompute-returns` flag is
left as future work.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[3]))

from skills._shared._aegis_common import (  # noqa: E402
    append_jsonl,
    atomic_write_json,
    blackbox_dir,
    load_config,
    now_ms,
)


def _read_signal_performance(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.rstrip("\n")
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except Exception:
        return None


def _classify(decay_score: float | None, cfg: dict[str, Any]) -> str:
    if decay_score is None:
        return "INSUFFICIENT_DATA"
    if decay_score >= float(cfg["retire_threshold"]):
        return "RETIRE"
    if decay_score >= float(cfg["monitor_threshold"]):
        return "MONITOR"
    return "ACTIVE"


def compute_decay(
    rows: Iterable[dict[str, Any]],
    *,
    long_term_ms: int,
    recent_ms: int,
    now_ts: int,
    cfg: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    long_cutoff = now_ts - long_term_ms
    recent_cutoff = now_ts - recent_ms
    bucket_long: dict[str, list[float]] = defaultdict(list)
    bucket_recent: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        source = row.get("source_id")
        if not isinstance(source, str):
            continue
        ts = int(row.get("ts_ms", 0))
        if ts < long_cutoff:
            continue
        value = _to_float(row.get("forward_return_1h"))
        if value is None:
            continue
        bucket_long[source].append(value)
        if ts >= recent_cutoff:
            bucket_recent[source].append(value)
    out: dict[str, dict[str, Any]] = {}
    for source, long_vals in bucket_long.items():
        recent_vals = bucket_recent.get(source, [])
        long_n = len(long_vals)
        recent_n = len(recent_vals)
        long_mean = statistics.fmean(long_vals) if long_vals else 0.0
        recent_mean = statistics.fmean(recent_vals) if recent_vals else None
        long_std = statistics.pstdev(long_vals) if long_n >= 2 else 0.0
        if long_n < 5 or recent_n < 3 or recent_mean is None:
            score: float | None = None
        else:
            denom = max(0.001, long_std)
            raw = (long_mean - recent_mean) / denom
            score = max(0.0, raw)
            if math.isnan(score) or math.isinf(score):
                score = None
        out[source] = {
            "long_term_n": long_n,
            "recent_n": recent_n,
            "long_term_mean": f"{long_mean:.6f}",
            "recent_mean": f"{recent_mean:.6f}" if recent_mean is not None else None,
            "long_term_std": f"{long_std:.6f}",
            "decay_score": f"{score:.4f}" if score is not None else None,
            "band": _classify(score, cfg),
        }
    return out


def cmd_recompute(args: argparse.Namespace) -> int:
    config = load_config()
    bb = config["blackbox"]
    rows = _read_signal_performance(blackbox_dir() / "signal_performance.jsonl")
    report = compute_decay(
        rows,
        long_term_ms=int(bb["decay_long_term_days"]) * 86_400_000,
        recent_ms=int(bb["decay_recent_days"]) * 86_400_000,
        now_ts=now_ms(),
        cfg=bb,
    )
    body = {
        "schema_version": 1,
        "computed_ts_ms": now_ms(),
        "config": {
            "long_term_days": int(bb["decay_long_term_days"]),
            "recent_days": int(bb["decay_recent_days"]),
            "retire_threshold": float(bb["retire_threshold"]),
            "monitor_threshold": float(bb["monitor_threshold"]),
        },
        "sources": report,
    }
    atomic_write_json(blackbox_dir() / "decay_report.json", body)
    counts = {"RETIRE": 0, "MONITOR": 0, "ACTIVE": 0, "INSUFFICIENT_DATA": 0}
    for src in report.values():
        counts[src["band"]] = counts.get(src["band"], 0) + 1
    append_jsonl(
        blackbox_dir() / "meta.jsonl",
        {
            "schema_version": 1,
            "ts_ms": now_ms(),
            "skill": "aegis-blackbox",
            "event": "decay_recomputed",
            "sources_scanned": len(report),
            "retired": counts["RETIRE"],
            "monitor": counts["MONITOR"],
            "active": counts["ACTIVE"],
        },
    )
    sys.stdout.write(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    report_path = blackbox_dir() / "decay_report.json"
    if not report_path.is_file():
        sys.stdout.write('{"error":"decay_report.json not found — run recompute first"}\n')
        return 1
    body = json.loads(report_path.read_text(encoding="utf-8"))
    src = body.get("sources", {}).get(args.source)
    if src is None:
        sys.stdout.write('{"error":"source not found"}\n')
        return 1
    sys.stdout.write(json.dumps(src, indent=2, ensure_ascii=False) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-blackbox decay")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_re = sub.add_parser("recompute", help="rebuild decay_report.json")
    p_re.add_argument("--chain", default="solana")
    p_re.set_defaults(func=cmd_recompute)
    p_cl = sub.add_parser("classify", help="show one source's decay band")
    p_cl.add_argument("--source", required=True)
    p_cl.set_defaults(func=cmd_classify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
