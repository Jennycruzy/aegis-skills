"""aegis-fader fade_score.

Strategy orchestrator. Pure-function `decide_per_token` is unit-tested; the `scan` command
wires the full Sentinel / Quartermaster / Hibernator gate chain and is exercised through
integration tests with a stubbed CLI. Quote / simulate / broadcast for FOLLOW_LONG
candidates is documented step-by-step in `workflows/full-trading-loop.md`.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
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
)


def _load_sibling(skill: str, script: str) -> ModuleType:
    """Load `skills/<skill>/scripts/<script>.py` by path.

    Skill folders use hyphens so they aren't importable as Python packages. This mirrors
    the loader used by the test suite and keeps `cmd_scan` self-contained.
    """
    repo_root = _HERE.parents[3]
    path = repo_root / "skills" / skill / "scripts" / f"{script}.py"
    mod_name = f"_aegis_{skill.replace('-', '_')}_{script}"
    cached = sys.modules.get(mod_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def decide_per_token(
    candidate: dict[str, Any],
    *,
    fragility: Decimal,
    fragility_decision: str,
    hibernator_status: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Apply the Fader decision tree to a single candidate.

    Pure function — no CLI calls. Inputs are the candidate from `signal_window.aggregate`
    plus pre-computed Sentinel + Hibernator answers.
    """
    crowd_threshold = Decimal(str(config["crowd_threshold"]))
    min_diversity = int(config["min_source_diversity"])
    crowdedness = Decimal(candidate["crowdedness"])
    source_diversity = int(candidate["source_diversity"])

    skip_reason: str | None = None
    decision: str = "SKIP"

    if hibernator_status == "HIBERNATED":
        skip_reason = "hibernated"
        return _bundle(candidate, decision, skip_reason, fragility, fragility_decision)

    if fragility_decision == "BLOCK":
        skip_reason = "block"
        return _bundle(candidate, decision, skip_reason, fragility, fragility_decision)

    if crowdedness >= crowd_threshold:
        decision = "FADE_OPPORTUNITY"
        skip_reason = None
        return _bundle(candidate, decision, skip_reason, fragility, fragility_decision)

    if source_diversity < min_diversity:
        skip_reason = "diversity"
        return _bundle(candidate, decision, skip_reason, fragility, fragility_decision)

    if fragility >= Decimal("0.30"):
        skip_reason = "fragility"
        return _bundle(candidate, decision, skip_reason, fragility, fragility_decision)

    decision = "FOLLOW_LONG"
    skip_reason = None
    return _bundle(candidate, decision, skip_reason, fragility, fragility_decision)


def _bundle(
    candidate: dict[str, Any],
    decision: str,
    skip_reason: str | None,
    fragility: Decimal,
    fragility_decision: str,
) -> dict[str, Any]:
    return {
        "token": candidate["token"],
        "signal_count": candidate["signal_count"],
        "source_diversity": candidate["source_diversity"],
        "crowdedness": candidate["crowdedness"],
        "fragility": f"{fragility:.4f}",
        "fragility_decision": fragility_decision,
        "decision": decision,
        "skip_reason": skip_reason,
    }


def decision_id(chain: str, token: str, window_start_ms: int) -> str:
    return f"fader-{chain}-{token}-{window_start_ms}"


def cmd_score(args: argparse.Namespace) -> int:
    """Score a single token's signal context, no execution."""
    # We don't fetch signals here — the user gives us the per-token snapshot inline. This is
    # primarily a wrapper for the pure decide_per_token function so it's reachable from a
    # CLI; the full scan command exercises the real CLI integration.
    candidate = {
        "token": args.token,
        "signal_count": int(args.signal_count),
        "source_diversity": int(args.source_diversity),
        "crowdedness": str(args.crowdedness),
    }
    cfg = load_config()["fader"]
    out = decide_per_token(
        candidate,
        fragility=Decimal(args.fragility),
        fragility_decision=args.fragility_decision,
        hibernator_status=args.hibernator_status,
        config=cfg,
    )
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now_ms(),
        "skill": "aegis-fader",
        "event": "candidate_evaluated",
        "chain": args.chain,
        **out,
    }
    append_jsonl(blackbox_dir() / "decisions.jsonl", envelope)
    sys.stdout.write(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """End-to-end gate scan: hibernator → signals → per-token (sentinel → quartermaster → fader).

    Runs every read-only gate and produces a per-candidate decision table plus a summary.
    Does NOT broadcast in any mode — broadcast / track / attribution live in
    `workflows/full-trading-loop.md`. The `--dry-run` flag is informational; the scan never
    moves funds regardless.
    """
    if args.chain not in {"solana", "xlayer"}:
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "msg": "Chain outside AEGIS competition scope (solana, xlayer).",
                },
                indent=2,
            )
            + "\n"
        )
        return 1

    dry_run = bool(getattr(args, "dry_run", False))
    window_minutes = int(getattr(args, "window_minutes", 60) or 60)
    wallet = getattr(args, "wallet", None)
    wallet_balance_str = getattr(args, "wallet_balance_usd", None)

    cfg = load_config()
    fader_cfg = cfg["fader"]
    sentinel_cfg = cfg["sentinel"]
    qm_cfg = cfg["quartermaster"]

    decisions_path = blackbox_dir() / "decisions.jsonl"

    scan_invoked = {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now_ms(),
        "skill": "aegis-fader",
        "event": "scan_invoked",
        "chain": args.chain,
        "window_minutes": window_minutes,
        "dry_run": dry_run,
    }
    append_jsonl(decisions_path, scan_invoked)

    # 1. Hibernator pre-check — short-circuit if HIBERNATED.
    drawdown_mod = _load_sibling("aegis-hibernator", "drawdown")
    hib_state = drawdown_mod.load_state()
    hib_status = hib_state.get("status", "ACTIVE")
    if hib_status == "HIBERNATED":
        summary = {
            "schema_version": SCHEMA_VERSION,
            "ts_ms": now_ms(),
            "skill": "aegis-fader",
            "event": "scan_completed",
            "chain": args.chain,
            "window_minutes": window_minutes,
            "dry_run": dry_run,
            "status": "skipped",
            "skip_reason": "hibernated",
            "hibernator_reason": hib_state.get("reason"),
            "candidates_total": 0,
            "follow_long": 0,
            "fade_opportunity": 0,
            "skipped": 0,
            "candidates": [],
        }
        append_jsonl(decisions_path, summary)
        sys.stdout.write(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        return 0

    # 2. Snapshot the signal window.
    signal_window_mod = _load_sibling("aegis-fader", "signal_window")
    now = now_ms()
    window_ms_total = window_minutes * 60_000
    window_start = (now // 10_000) * 10_000 - window_ms_total
    window_end = now
    sig_res = run_cli(
        ["signal", "list", "--chain", args.chain, "--wallet-type", "1,2,3"],
    )
    if not sig_res.ok:
        summary = {
            "schema_version": SCHEMA_VERSION,
            "ts_ms": now_ms(),
            "skill": "aegis-fader",
            "event": "scan_completed",
            "chain": args.chain,
            "window_minutes": window_minutes,
            "dry_run": dry_run,
            "status": "failed",
            "skip_reason": "signal_window_unavailable",
            "msg": sig_res.msg,
            "code": sig_res.code,
            "candidates_total": 0,
            "follow_long": 0,
            "fade_opportunity": 0,
            "skipped": 0,
            "candidates": [],
        }
        append_jsonl(decisions_path, summary)
        sys.stdout.write(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        return 1
    rows = signal_window_mod._extract_signal_rows(sig_res.data)
    window = signal_window_mod.aggregate(
        rows,
        window_start_ms=window_start,
        window_end_ms=window_end,
        retire_sources=signal_window_mod.load_retire_set(),
    )

    # 3. Resolve wallet balance once (if either input given).
    wallet_balance: Decimal | None = None
    kelly_mod = _load_sibling("aegis-quartermaster", "kelly")
    if wallet_balance_str is not None:
        try:
            wallet_balance = Decimal(str(wallet_balance_str))
        except Exception:
            wallet_balance = None
    elif wallet:
        bal_res = run_cli(
            ["portfolio", "total-value", "--address", wallet, "--chains", args.chain],
        )
        if bal_res.ok:
            wallet_balance = kelly_mod._extract_balance(bal_res.data)

    # 4. Per-token loop.
    fragility_mod = _load_sibling("aegis-sentinel", "fragility")
    block_threshold = Decimal(str(sentinel_cfg["block_threshold"]))
    size_down_threshold = Decimal(str(sentinel_cfg["size_down_threshold"]))

    candidates_out: list[dict[str, Any]] = []
    for token_entry in window.get("tokens", []):
        token = token_entry["token"]

        # 4a. Sentinel
        values, reasons = fragility_mod.collect_factors(args.chain, token)
        risk_level, sec_reasons = fragility_mod.security_risk_level(args.chain, token)
        reasons.extend(sec_reasons)
        sentinel = fragility_mod.compose_score(
            values,
            weights=sentinel_cfg["weights"],
            block_threshold=block_threshold,
            size_down_threshold=size_down_threshold,
            security_risk_level=risk_level,
            chain=args.chain,
            reasons_in=reasons,
        )
        sentinel_decision = sentinel["decision"]
        fragility_val = Decimal(sentinel["fragility"])
        append_jsonl(decisions_path, {
            "schema_version": SCHEMA_VERSION,
            "ts_ms": now_ms(),
            "skill": "aegis-sentinel",
            "event": "fragility_computed",
            "chain": args.chain,
            "token": token,
            "fragility": sentinel["fragility"],
            "decision": sentinel_decision,
            "factors": sentinel["factors"],
            "reasons": sentinel["reasons"],
            "security_token_scan": sentinel["security_token_scan"],
        })

        # 4b. Quartermaster sizing — only if Sentinel didn't BLOCK and we have a balance.
        kelly_result: dict[str, Any] = {}
        if sentinel_decision != "BLOCK" and wallet_balance is not None:
            history = kelly_mod.aggregate_history(
                kelly_mod._read_trades(blackbox_dir() / "trades.jsonl"),
                "aegis-fader",
            )
            kelly_result = kelly_mod.compute_size(
                wins=int(history["wins"]),
                losses=int(history["losses"]),
                avg_win=history["avg_win"],
                avg_loss=history["avg_loss"],
                fragility=fragility_val,
                wallet_balance_usd=wallet_balance,
                cfg=qm_cfg,
            )
            append_jsonl(decisions_path, {
                "schema_version": SCHEMA_VERSION,
                "ts_ms": now_ms(),
                "skill": "aegis-quartermaster",
                "event": "size_computed",
                "strategy_id": "aegis-fader",
                "token": token,
                "chain": args.chain,
                **kelly_result,
            })

        # 4c. Fader per-token decision (pure function).
        fader_out = decide_per_token(
            token_entry,
            fragility=fragility_val,
            fragility_decision=sentinel_decision,
            hibernator_status=hib_status,
            config=fader_cfg,
        )

        if kelly_result:
            size_usd = kelly_result["size_usd"]
            binding = kelly_result["binding_constraint"]
        elif sentinel_decision == "BLOCK":
            size_usd = "0"
            binding = "sentinel_block"
        else:
            size_usd = "0"
            binding = "no_wallet_balance"

        candidate = {
            "token": token,
            "signal_count": token_entry["signal_count"],
            "source_diversity": token_entry["source_diversity"],
            "crowdedness": token_entry["crowdedness"],
            "fragility": sentinel["fragility"],
            "sentinel_decision": sentinel_decision,
            "sentinel_reasons": sentinel["reasons"],
            "size_usd": size_usd,
            "binding_constraint": binding,
            "fader_decision": fader_out["decision"],
            "skip_reason": fader_out["skip_reason"],
            "decision_id": decision_id(args.chain, token, window_start),
        }
        candidates_out.append(candidate)
        append_jsonl(decisions_path, {
            "schema_version": SCHEMA_VERSION,
            "ts_ms": now_ms(),
            "skill": "aegis-fader",
            "event": "candidate_evaluated",
            "chain": args.chain,
            **candidate,
        })

    # 5. Summary.
    summary = {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now_ms(),
        "skill": "aegis-fader",
        "event": "scan_completed",
        "chain": args.chain,
        "window_minutes": window_minutes,
        "dry_run": dry_run,
        "wallet": wallet,
        "wallet_balance_usd": f"{wallet_balance:.2f}" if wallet_balance is not None else None,
        "candidates_total": len(candidates_out),
        "follow_long": sum(1 for c in candidates_out if c["fader_decision"] == "FOLLOW_LONG"),
        "fade_opportunity": sum(1 for c in candidates_out if c["fader_decision"] == "FADE_OPPORTUNITY"),
        "skipped": sum(1 for c in candidates_out if c["fader_decision"] == "SKIP"),
        "candidates": candidates_out,
        "note": (
            "Gate scan only. Quote/simulate/broadcast/track for FOLLOW_LONG candidates is "
            "documented in workflows/full-trading-loop.md and stays out of this command for "
            "judge-safety — no funds move regardless of --dry-run."
        ),
    }
    append_jsonl(decisions_path, summary)
    sys.stdout.write(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-fader fade_score")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_score = sub.add_parser("score", help="Score one token's signal context")
    p_score.add_argument("--chain", required=True, choices=["solana", "xlayer"])
    p_score.add_argument("--token", required=True)
    p_score.add_argument("--signal-count", type=int, required=True)
    p_score.add_argument("--source-diversity", type=int, required=True)
    p_score.add_argument("--crowdedness", required=True)
    p_score.add_argument("--fragility", required=True)
    p_score.add_argument(
        "--fragility-decision",
        required=True,
        choices=["ALLOW", "SIZE_DOWN", "BLOCK"],
    )
    p_score.add_argument(
        "--hibernator-status",
        required=True,
        choices=["ACTIVE", "HIBERNATED"],
    )
    p_score.set_defaults(func=cmd_score)

    p_scan = sub.add_parser("scan", help="Full strategy gate scan")
    p_scan.add_argument("--chain", required=True)
    p_scan.add_argument("--window-minutes", type=int, default=60)
    p_scan.add_argument(
        "--wallet",
        help="Wallet address. If --wallet-balance-usd is omitted, balance is fetched via "
             "`onchainos portfolio total-value`.",
    )
    p_scan.add_argument(
        "--wallet-balance-usd",
        help="Override wallet balance (USD, decimal string). Skips the portfolio CLI call.",
    )
    p_scan.add_argument("--dry-run", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
