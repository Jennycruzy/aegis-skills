"""aegis-quartermaster — Bayesian-shrunk fractional Kelly sizer.

Pure math except for the optional `from-portfolio` subcommand, which calls
`onchainos portfolio total-value`. Emits a `size_computed` event to aegis-blackbox.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections.abc import Iterable
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[3]))

from skills._shared._aegis_common import (  # noqa: E402
    GEO_BLOCK_MESSAGE,
    SCHEMA_VERSION,
    append_jsonl,
    blackbox_dir,
    load_config,
    now_ms,
    run_cli,
)

getcontext().prec = 28


def _to_decimal(x: Any) -> Decimal:
    return Decimal(str(x))


def _clamp(value: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def fragility_curve(fragility: Decimal, curve: list[list[float]]) -> Decimal:
    """Piecewise-linear multiplier; configurable.

    Default: [(0.0, 1.0), (0.5, 0.2), (1.0, 0.0)].
    """
    pts = [(Decimal(str(x)), Decimal(str(y))) for x, y in curve]
    pts.sort(key=lambda p: p[0])
    if fragility <= pts[0][0]:
        return pts[0][1]
    if fragility >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in itertools.pairwise(pts):
        if x0 <= fragility <= x1:
            if x1 == x0:
                return y0
            frac = (fragility - x0) / (x1 - x0)
            return y0 + (y1 - y0) * frac
    return Decimal("0")


def aggregate_history(
    rows: Iterable[dict[str, Any]], strategy_id: str
) -> dict[str, Any]:
    wins = 0
    losses = 0
    win_sum = Decimal("0")
    loss_sum = Decimal("0")
    for row in rows:
        sid = row.get("decision_id") or ""
        if not isinstance(sid, str) or not sid.startswith(f"{strategy_id}-"):
            continue
        attr = row.get("attribution")
        if not isinstance(attr, dict):
            continue
        pnl = attr.get("realized_pnl_pct")
        if pnl is None:
            continue
        try:
            value = Decimal(str(pnl))
        except Exception:
            continue
        if value > 0:
            wins += 1
            win_sum += value
        elif value < 0:
            losses += 1
            loss_sum += -value
    avg_win = (win_sum / wins) if wins else Decimal("0.10")
    avg_loss = (loss_sum / losses) if losses else Decimal("0.10")
    return {
        "wins": wins,
        "losses": losses,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    }


def _read_trades(path: Path) -> list[dict[str, Any]]:
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


def compute_size(
    *,
    wins: int,
    losses: int,
    avg_win: Decimal,
    avg_loss: Decimal,
    fragility: Decimal,
    wallet_balance_usd: Decimal,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    alpha = Decimal(str(cfg["shrinkage_alpha"]))
    beta = Decimal(str(cfg["shrinkage_beta"]))
    kelly_fraction = Decimal(str(cfg["kelly_fraction"]))
    max_position_pct = Decimal(str(cfg["max_position_pct"]))
    min_position_usd = Decimal(str(cfg["min_position_usd"]))
    curve = list(cfg["fragility_curve"])

    denom = Decimal(wins + losses) + alpha + beta
    hit_rate_shrunk = (Decimal(wins) + alpha) / denom

    if avg_loss == 0:
        avg_loss = Decimal("0.01")
    payoff_ratio = _clamp(avg_win / avg_loss, Decimal("0.1"), Decimal("10.0"))

    kelly_full = hit_rate_shrunk - (Decimal(1) - hit_rate_shrunk) / payoff_ratio

    if kelly_full <= 0:
        return {
            "wins": wins,
            "losses": losses,
            "avg_win": f"{avg_win:.6f}",
            "avg_loss": f"{avg_loss:.6f}",
            "hit_rate_shrunk": f"{hit_rate_shrunk:.6f}",
            "payoff_ratio": f"{payoff_ratio:.6f}",
            "kelly_full": f"{kelly_full:.6f}",
            "kelly_use": "0",
            "fragility": f"{fragility:.6f}",
            "fragility_multiplier": "0",
            "wallet_balance_usd": f"{wallet_balance_usd:.2f}",
            "size_usd": "0",
            "binding_constraint": "negative_edge",
            "reason": "negative_edge",
        }

    kelly_use = max(Decimal("0"), kelly_full) * kelly_fraction
    pct_after_wallet_cap = min(kelly_use, max_position_pct)
    size_wallet_cap = pct_after_wallet_cap * wallet_balance_usd
    multiplier = fragility_curve(fragility, curve)
    size_after_frag = size_wallet_cap * multiplier

    binding = _binding(
        kelly_use=kelly_use,
        max_position_pct=max_position_pct,
        multiplier=multiplier,
        size_after_frag=size_after_frag,
        min_position_usd=min_position_usd,
    )

    if size_after_frag < min_position_usd:
        return {
            "wins": wins,
            "losses": losses,
            "avg_win": f"{avg_win:.6f}",
            "avg_loss": f"{avg_loss:.6f}",
            "hit_rate_shrunk": f"{hit_rate_shrunk:.6f}",
            "payoff_ratio": f"{payoff_ratio:.6f}",
            "kelly_full": f"{kelly_full:.6f}",
            "kelly_use": f"{kelly_use:.6f}",
            "fragility": f"{fragility:.6f}",
            "fragility_multiplier": f"{multiplier:.6f}",
            "wallet_balance_usd": f"{wallet_balance_usd:.2f}",
            "size_usd": "0",
            "binding_constraint": "min_position" if multiplier > 0 else "fragility_curve",
            "reason": "below_minimum",
        }

    return {
        "wins": wins,
        "losses": losses,
        "avg_win": f"{avg_win:.6f}",
        "avg_loss": f"{avg_loss:.6f}",
        "hit_rate_shrunk": f"{hit_rate_shrunk:.6f}",
        "payoff_ratio": f"{payoff_ratio:.6f}",
        "kelly_full": f"{kelly_full:.6f}",
        "kelly_use": f"{kelly_use:.6f}",
        "fragility": f"{fragility:.6f}",
        "fragility_multiplier": f"{multiplier:.6f}",
        "wallet_balance_usd": f"{wallet_balance_usd:.2f}",
        "size_usd": f"{size_after_frag:.2f}",
        "binding_constraint": binding,
        "reason": "ok",
    }


def _binding(
    *,
    kelly_use: Decimal,
    max_position_pct: Decimal,
    multiplier: Decimal,
    size_after_frag: Decimal,
    min_position_usd: Decimal,
) -> str:
    if size_after_frag < min_position_usd:
        return "min_position"
    if multiplier < Decimal("1"):
        return "fragility_curve"
    if kelly_use > max_position_pct:
        return "wallet_cap"
    return "kelly_fraction"


def cmd_size(args: argparse.Namespace, *, wallet_balance: Decimal | None = None) -> int:
    cfg = load_config()["quartermaster"]
    if wallet_balance is None:
        wallet_balance = _to_decimal(args.wallet_balance_usd)
    wins: int
    losses: int
    avg_win_d: Decimal
    avg_loss_d: Decimal
    if args.wins is not None and args.losses is not None:
        wins = int(args.wins)
        losses = int(args.losses)
        avg_win_d = _to_decimal(args.avg_win or "0.10")
        avg_loss_d = _to_decimal(args.avg_loss or "0.10")
    else:
        hist = aggregate_history(
            _read_trades(blackbox_dir() / "trades.jsonl"),
            args.strategy_id,
        )
        wins = int(hist["wins"])
        losses = int(hist["losses"])
        avg_win_d = hist["avg_win"]
        avg_loss_d = hist["avg_loss"]
    result = compute_size(
        wins=wins,
        losses=losses,
        avg_win=avg_win_d,
        avg_loss=avg_loss_d,
        fragility=_to_decimal(args.fragility),
        wallet_balance_usd=wallet_balance,
        cfg=cfg,
    )
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now_ms(),
        "skill": "aegis-quartermaster",
        "event": "size_computed",
        "strategy_id": args.strategy_id,
        "token": args.token,
        "chain": args.chain,
    }
    envelope.update(result)
    append_jsonl(blackbox_dir() / "decisions.jsonl", envelope)
    sys.stdout.write(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    rows = _read_trades(blackbox_dir() / "trades.jsonl")
    hist = aggregate_history(rows, args.strategy_id)
    out = {
        "strategy_id": args.strategy_id,
        "wins": hist["wins"],
        "losses": hist["losses"],
        "avg_win": f"{hist['avg_win']:.6f}",
        "avg_loss": f"{hist['avg_loss']:.6f}",
    }
    sys.stdout.write(json.dumps(out, indent=2) + "\n")
    return 0


def cmd_from_portfolio(args: argparse.Namespace) -> int:
    res = run_cli(
        ["portfolio", "total-value", "--address", args.wallet, "--chains", args.chain],
    )
    if not res.ok:
        sys.stdout.write(
            json.dumps(
                {
                    "size_usd": "0",
                    "reason": "portfolio_unavailable",
                    "binding_constraint": "portfolio",
                    "detail": res.msg or GEO_BLOCK_MESSAGE,
                },
                indent=2,
            )
            + "\n"
        )
        return 1
    balance = _extract_balance(res.data)
    return cmd_size(args, wallet_balance=balance)


def _extract_balance(payload: Any) -> Decimal:
    """Best-effort extraction of total USD value from portfolio total-value output."""
    if isinstance(payload, dict):
        for key in ("totalValueUsd", "total_value_usd", "totalValue", "value"):
            if key in payload:
                try:
                    return _to_decimal(payload[key])
                except Exception:
                    continue
        for nested in ("data", "result"):
            inner = payload.get(nested)
            if isinstance(inner, dict):
                v = _extract_balance(inner)
                if v > 0:
                    return v
    return Decimal("0")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-quartermaster")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--strategy-id", required=True)
        p.add_argument("--token", required=True)
        p.add_argument("--chain", required=True, choices=["solana", "xlayer"])
        p.add_argument("--fragility", required=True)
        p.add_argument("--wins", type=int, default=None)
        p.add_argument("--losses", type=int, default=None)
        p.add_argument("--avg-win")
        p.add_argument("--avg-loss")

    p_size = sub.add_parser("size", help="Compute size from --wallet-balance-usd")
    add_common(p_size)
    p_size.add_argument("--wallet-balance-usd", required=True)
    p_size.set_defaults(func=cmd_size)

    p_hist = sub.add_parser("history", help="Summarise hit-rate / payoff for a strategy")
    p_hist.add_argument("--strategy-id", required=True)
    p_hist.set_defaults(func=cmd_history)

    p_fp = sub.add_parser("from-portfolio", help="Fetch wallet balance from onchainos")
    add_common(p_fp)
    p_fp.add_argument("--wallet", required=True)
    p_fp.set_defaults(func=cmd_from_portfolio)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
