"""aegis-sentinel — composite Fragility Score for a token.

Reads `onchainos token`, `onchainos memepump`, `onchainos security`. Pure-function
`compose_score` is unit-tested; CLI integration is exercised in integration tests.
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[3]))

from skills._shared._aegis_common import (  # noqa: E402
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

FACTORS: tuple[str, ...] = (
    "cluster_concentration",
    "bundle_sniper",
    "dev_rug_history",
    "holder_velocity",
    "lp_unlock_proximity",
)


def _clamp_dec(x: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _to_dec(v: Any, default: Decimal = Decimal("0")) -> Decimal:
    if v is None:
        return default
    try:
        return Decimal(str(v))
    except Exception:
        return default


def _validate_weights(weights: dict[str, float]) -> None:
    total = sum(Decimal(str(weights.get(k, 0))) for k in FACTORS)
    if abs(total - Decimal("1")) > Decimal("0.001"):
        raise ValueError(
            f"sentinel.weights must sum to 1.0; got {total} across {FACTORS}",
        )


def compose_score(
    factor_values: dict[str, Decimal | None],
    *,
    weights: dict[str, float],
    block_threshold: Decimal,
    size_down_threshold: Decimal,
    security_risk_level: str | None,
    chain: str,
    reasons_in: list[str] | None = None,
) -> dict[str, Any]:
    """Compose factor values into a fragility score + decision verb.

    `factor_values[k]` may be None (factor unavailable) → defaults to 0.5 with a reason. The
    function is total — never raises on missing data.
    """
    _validate_weights(weights)
    reasons: list[str] = list(reasons_in or [])
    detailed: dict[str, dict[str, Any]] = {}
    fragility = Decimal("0")
    for factor in FACTORS:
        weight = Decimal(str(weights[factor]))
        value = factor_values.get(factor)
        if value is None:
            value = Decimal("0.5")
            reasons.append(f"{factor}_unavailable")
        value = _clamp_dec(value, Decimal("0"), Decimal("1"))
        contribution = value * weight
        fragility += contribution
        detailed[factor] = {
            "value": f"{value:.4f}",
            "weight": f"{weight:.4f}",
            "contribution": f"{contribution:.4f}",
        }

    # off-Solana defaults for Solana-only factors
    if chain != "solana":
        for solana_only in ("bundle_sniper", "dev_rug_history"):
            if f"{solana_only}_unavailable" in reasons:
                # already handled above
                continue
            # If the caller didn't supply a value but it's Solana-only, ensure the marker exists.
            if factor_values.get(solana_only) is None and "bundle_na" not in reasons:
                reasons.append("bundle_na" if solana_only == "bundle_sniper" else "dev_info_na")

    decision: str
    if security_risk_level == "CRITICAL":
        fragility = Decimal("1")
        decision = "BLOCK"
        reasons.append("security_critical")
    elif fragility >= block_threshold:
        decision = "BLOCK"
    elif fragility >= size_down_threshold:
        decision = "SIZE_DOWN"
    else:
        decision = "ALLOW"

    seen: set[str] = set()
    deduped: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            deduped.append(r)
    return {
        "fragility": f"{fragility:.4f}",
        "decision": decision,
        "factors": detailed,
        "reasons": deduped,
        "security_token_scan": {"riskLevel": security_risk_level},
    }


# ---------------------------------------------------------------------------
# Factor extractors — each returns (value | None, reasons_appended)
# ---------------------------------------------------------------------------


def factor_cluster_concentration(
    chain: str, token: str
) -> tuple[Decimal | None, list[str]]:
    reasons: list[str] = []
    # Try memepump first (Solana richer signal), fall back to token holders.
    top10_pct: Decimal | None = None
    if chain == "solana":
        res = run_cli(["memepump", "token-details", "--address", token])
        if res.ok and isinstance(res.data, dict):
            top10_pct = _maybe_pct(res.data, ("top10HoldingsPercent",))
        elif res.code in {50125, 80001}:
            reasons.append("geo_block:cluster")
    if top10_pct is None:
        res = run_cli(["token", "holders", "--chain", chain, "--token", token])
        if res.ok and isinstance(res.data, dict):
            top10_pct = _maybe_pct(
                res.data, ("top10HoldingsPercent", "top10Concentration"),
            )
        elif res.code in {50125, 80001}:
            reasons.append("geo_block:cluster")
    if top10_pct is None:
        reasons.append("cluster_concentration_unavailable")
        return None, reasons
    normalised = _clamp_dec(
        (top10_pct - Decimal("0.20")) / Decimal("0.60"),
        Decimal("0"),
        Decimal("1"),
    )
    return normalised, reasons


def factor_bundle_sniper(
    chain: str, token: str
) -> tuple[Decimal | None, list[str]]:
    if chain != "solana":
        return None, ["bundle_na"]
    res = run_cli(["memepump", "token-bundle-info", "--address", token])
    if not res.ok or not isinstance(res.data, dict):
        if res.code in {50125, 80001}:
            return None, ["geo_block:bundle"]
        return None, ["bundle_sniper_unavailable"]
    bundler = _maybe_pct(res.data, ("bundlerHoldingsPercent",)) or Decimal("0")
    sniper = _maybe_pct(res.data, ("sniperHoldingsPercent",)) or Decimal("0")
    combined = bundler + sniper
    return _clamp_dec(combined / Decimal("0.20"), Decimal("0"), Decimal("1")), []


def factor_dev_rug_history(
    chain: str, token: str
) -> tuple[Decimal | None, list[str]]:
    if chain != "solana":
        return None, ["dev_info_na"]
    res = run_cli(["memepump", "token-dev-info", "--address", token])
    if not res.ok or not isinstance(res.data, dict):
        if res.code in {50125, 80001}:
            return None, ["geo_block:dev"]
        return None, ["dev_rug_history_unavailable"]
    rug_count = _to_dec(res.data.get("rugPullCount"), Decimal("0"))
    return _clamp_dec(rug_count / Decimal("3"), Decimal("0"), Decimal("1")), []


def factor_holder_velocity(
    chain: str, token: str
) -> tuple[Decimal | None, list[str]]:
    res_p = run_cli(["token", "price-info", "--chain", chain, "--token", token])
    res_h = run_cli(["token", "holders", "--chain", chain, "--token", token])
    if not res_p.ok or not res_h.ok:
        return None, ["holder_velocity_unavailable"]
    if not isinstance(res_p.data, dict) or not isinstance(res_h.data, dict):
        return None, ["holder_velocity_unavailable"]
    price_delta = _maybe_pct(res_p.data, ("change24hPct", "priceChange24h"))
    holder_delta = _maybe_pct(res_h.data, ("change24hPct", "holderChange24h"))
    if price_delta is None or holder_delta is None:
        return None, ["holder_velocity_unavailable"]
    divergence = abs(holder_delta - price_delta)
    return _clamp_dec(divergence / Decimal("0.50"), Decimal("0"), Decimal("1")), []


def factor_lp_unlock_proximity(
    chain: str, token: str
) -> tuple[Decimal | None, list[str]]:
    res = run_cli(["token", "advanced-info", "--chain", chain, "--token", token])
    if not res.ok or not isinstance(res.data, dict):
        if res.code in {50125, 80001}:
            return None, ["geo_block:lp"]
        return None, ["lp_unlock_proximity_unavailable"]
    unlock_ms = res.data.get("lpUnlockTimeMs") or res.data.get("lpLockUntilTimestamp")
    if unlock_ms is None:
        return None, ["lp_unlock_proximity_unavailable"]
    try:
        unlock = int(unlock_ms)
    except (TypeError, ValueError):
        return None, ["lp_unlock_proximity_unavailable"]
    delta_days = max(0, (unlock - now_ms()) // 86_400_000)
    proximity = Decimal("1") - _clamp_dec(
        Decimal(delta_days) / Decimal("30"), Decimal("0"), Decimal("1"),
    )
    return proximity, []


def security_risk_level(chain: str, token: str) -> tuple[str | None, list[str]]:
    res = run_cli(["security", "token-scan", "--chain", chain, "--token", token])
    if not res.ok or not isinstance(res.data, dict):
        if res.code in {50125, 80001}:
            return None, ["geo_block:security"]
        return None, ["security_unavailable"]
    level = res.data.get("riskLevel")
    if isinstance(level, str):
        return level.upper(), []
    return None, ["security_unavailable"]


def _maybe_pct(payload: dict[str, Any], keys: tuple[str, ...]) -> Decimal | None:
    for k in keys:
        v = payload.get(k)
        if v is None:
            continue
        try:
            d = Decimal(str(v))
        except Exception:
            continue
        # Heuristic: values >1 are percentages (e.g. 42 means 42 percent). Normalise to 0-1.
        if d > Decimal("1"):
            d = d / Decimal("100")
        return d
    return None


# ---------------------------------------------------------------------------
# Cache + orchestration
# ---------------------------------------------------------------------------


def _load_cache() -> dict[str, Any]:
    path = state_dir() / "sentinel_cache.json"
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    if not isinstance(body, dict) or body.get("schema_version") != SCHEMA_VERSION:
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    if not isinstance(body.get("entries"), dict):
        body["entries"] = {}
    return body


def _save_cache(cache: dict[str, Any]) -> None:
    atomic_write_json(state_dir() / "sentinel_cache.json", cache)


def _cache_key(chain: str, token: str) -> str:
    return f"{chain}:{token.lower() if chain == 'xlayer' else token}"


def collect_factors(
    chain: str, token: str
) -> tuple[dict[str, Decimal | None], list[str]]:
    reasons: list[str] = []
    values: dict[str, Decimal | None] = {}
    for factor, fn in (
        ("cluster_concentration", factor_cluster_concentration),
        ("bundle_sniper", factor_bundle_sniper),
        ("dev_rug_history", factor_dev_rug_history),
        ("holder_velocity", factor_holder_velocity),
        ("lp_unlock_proximity", factor_lp_unlock_proximity),
    ):
        value, factor_reasons = fn(chain, token)
        values[factor] = value
        reasons.extend(factor_reasons)
    return values, reasons


def cmd_score(args: argparse.Namespace) -> int:
    cfg = load_config()
    s_cfg = cfg["sentinel"]
    weights = s_cfg["weights"]
    cache = _load_cache()
    key = _cache_key(args.chain, args.token)
    now = now_ms()
    ttl_ms = int(s_cfg["cache_ttl_seconds"]) * 1000
    entry = cache["entries"].get(key)
    if entry and not args.refresh and now - int(entry.get("ts_ms", 0)) < ttl_ms:
        sys.stdout.write(json.dumps(entry, indent=2, ensure_ascii=False) + "\n")
        return 0
    values, reasons = collect_factors(args.chain, args.token)
    risk_level, sec_reasons = security_risk_level(args.chain, args.token)
    reasons.extend(sec_reasons)
    body = compose_score(
        values,
        weights=weights,
        block_threshold=Decimal(str(s_cfg["block_threshold"])),
        size_down_threshold=Decimal(str(s_cfg["size_down_threshold"])),
        security_risk_level=risk_level,
        chain=args.chain,
        reasons_in=reasons,
    )
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "ts_ms": now,
        "chain": args.chain,
        "token": args.token,
        **body,
    }
    cache["entries"][key] = envelope
    _save_cache(cache)
    append_jsonl(
        blackbox_dir() / "decisions.jsonl",
        {
            "schema_version": SCHEMA_VERSION,
            "ts_ms": now,
            "skill": "aegis-sentinel",
            "event": "fragility_computed",
            **envelope,
        },
    )
    sys.stdout.write(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    cache = _load_cache()
    key = _cache_key(args.chain, args.token)
    entry = cache["entries"].get(key)
    if entry is None:
        sys.stdout.write('{"error":"no cache entry"}\n')
        return 1
    sys.stdout.write(json.dumps(entry, indent=2, ensure_ascii=False) + "\n")
    return 0


def cmd_factors(args: argparse.Namespace) -> int:
    values, reasons = collect_factors(args.chain, args.token)
    out = {
        "chain": args.chain,
        "token": args.token,
        "factors": {
            k: (f"{v:.4f}" if v is not None else None) for k, v in values.items()
        },
        "reasons": reasons,
    }
    sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-sentinel fragility")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_score = sub.add_parser("score", help="compute + cache fragility for a token")
    p_score.add_argument("--chain", required=True)
    p_score.add_argument("--token", required=True)
    p_score.add_argument("--refresh", action="store_true")
    p_score.set_defaults(func=cmd_score)
    p_inspect = sub.add_parser("inspect", help="show cached fragility (no CLI calls)")
    p_inspect.add_argument("--chain", required=True)
    p_inspect.add_argument("--token", required=True)
    p_inspect.set_defaults(func=cmd_inspect)
    p_factors = sub.add_parser("factors", help="per-factor breakdown without decision verb")
    p_factors.add_argument("--chain", required=True)
    p_factors.add_argument("--token", required=True)
    p_factors.set_defaults(func=cmd_factors)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
