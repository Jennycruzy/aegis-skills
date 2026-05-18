"""aegis-blackbox logger CLI — tail, grep, stats over the JSONL ledgers.

Read-only against ~/.aegis/state/blackbox/*. Self-protecting: malformed lines are appended to
corrupt_lines.log and skipped, never raised.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# Make sibling _shared importable when run as a script.
_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[3]))

from skills._shared._aegis_common import (  # noqa: E402
    append_jsonl,
    blackbox_dir,
    now_ms,
    sanitize_external,
)


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        return
    corrupt_path = path.parent / "corrupt_lines.log"
    with path.open("r", encoding="utf-8") as fh:
        for offset, raw in enumerate(fh, start=1):
            raw = raw.rstrip("\n")
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                with corrupt_path.open("a", encoding="utf-8") as cf:
                    cf.write(f"{path.name}:{offset}\t{raw[:500]}\n")
                append_jsonl(
                    path.parent / "meta.jsonl",
                    {
                        "schema_version": 1,
                        "ts_ms": now_ms(),
                        "skill": "aegis-blackbox",
                        "event": "corrupt_line",
                        "file": path.name,
                        "line_no": offset,
                    },
                )
                continue
            if isinstance(obj, dict):
                yield obj


def _format_row(row: dict[str, Any]) -> str:
    ts = row.get("ts_ms", 0)
    skill = sanitize_external(str(row.get("skill", "?")), max_len=24)
    event = sanitize_external(str(row.get("event", "?")), max_len=32)
    extras = []
    for k in ("token", "decision", "gate", "reason", "size_usd", "fragility", "decision_id"):
        if k in row and row[k] is not None:
            extras.append(f"{k}={sanitize_external(str(row[k]), max_len=80)}")
    return f"{ts}  {skill:<20}  {event:<28}  {' '.join(extras)}"


def cmd_tail(args: argparse.Namespace) -> int:
    path = blackbox_dir() / args.file
    rows = list(_iter_jsonl(path))
    for row in rows[-args.limit :]:
        sys.stdout.write(_format_row(row) + "\n")
    return 0


def cmd_grep(args: argparse.Namespace) -> int:
    path = blackbox_dir() / args.file
    count = 0
    for row in _iter_jsonl(path):
        if args.event and row.get("event") != args.event:
            continue
        if args.skill and row.get("skill") != args.skill:
            continue
        if args.token and row.get("token") != args.token:
            continue
        sys.stdout.write(_format_row(row) + "\n")
        count += 1
        if count >= args.limit:
            break
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    path = blackbox_dir() / args.file
    by_event: Counter[str] = Counter()
    by_skill: Counter[str] = Counter()
    by_decision: Counter[str] = Counter()
    total = 0
    for row in _iter_jsonl(path):
        total += 1
        by_event[str(row.get("event", "?"))] += 1
        by_skill[str(row.get("skill", "?"))] += 1
        d = row.get("decision")
        if isinstance(d, str):
            by_decision[d] += 1
    report = {
        "file": args.file,
        "total_rows": total,
        "by_event": dict(by_event.most_common()),
        "by_skill": dict(by_skill.most_common()),
        "by_decision": dict(by_decision.most_common()),
    }
    sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-blackbox logger")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_tail = sub.add_parser("tail", help="tail recent rows")
    p_tail.add_argument("--file", default="decisions.jsonl")
    p_tail.add_argument("--limit", type=int, default=50)
    p_tail.set_defaults(func=cmd_tail)

    p_grep = sub.add_parser("grep", help="filter rows")
    p_grep.add_argument("--file", default="decisions.jsonl")
    p_grep.add_argument("--event")
    p_grep.add_argument("--skill")
    p_grep.add_argument("--token")
    p_grep.add_argument("--limit", type=int, default=200)
    p_grep.set_defaults(func=cmd_grep)

    p_stats = sub.add_parser("stats", help="event/skill/decision counts")
    p_stats.add_argument("--file", default="decisions.jsonl")
    p_stats.set_defaults(func=cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = args.func
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
