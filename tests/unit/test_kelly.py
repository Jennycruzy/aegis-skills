"""Unit tests for aegis-quartermaster Kelly sizer."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from tests._loader import load_script

kelly = load_script("aegis-quartermaster", "kelly")


def _cfg() -> dict[str, object]:
    return {
        "kelly_fraction": 0.25,
        "shrinkage_alpha": 1,
        "shrinkage_beta": 4,
        "min_position_usd": "5.00",
        "max_position_pct": 0.05,
        "fragility_curve": [[0.0, 1.0], [0.5, 0.2], [0.500001, 0.0]],
    }


def test_zero_history_is_negative_edge() -> None:
    out = kelly.compute_size(
        wins=0,
        losses=0,
        avg_win=Decimal("0.10"),
        avg_loss=Decimal("0.10"),
        fragility=Decimal("0.10"),
        wallet_balance_usd=Decimal("5000"),
        cfg=_cfg(),
    )
    assert out["size_usd"] == "0"
    assert out["reason"] == "negative_edge"
    assert out["binding_constraint"] == "negative_edge"


def test_all_loss_history() -> None:
    out = kelly.compute_size(
        wins=0,
        losses=10,
        avg_win=Decimal("0.10"),
        avg_loss=Decimal("0.10"),
        fragility=Decimal("0.10"),
        wallet_balance_usd=Decimal("5000"),
        cfg=_cfg(),
    )
    assert out["size_usd"] == "0"
    assert out["reason"] == "negative_edge"


def test_clean_history_wallet_cap_binds() -> None:
    out = kelly.compute_size(
        wins=50,
        losses=50,
        avg_win=Decimal("0.20"),
        avg_loss=Decimal("0.05"),
        fragility=Decimal("0.10"),
        wallet_balance_usd=Decimal("100000"),
        cfg=_cfg(),
    )
    # kelly_use ~ 8.9 % > 5 % cap -> wallet_cap binds initially; fragility 0.10 cuts further
    # but the wallet-pct cap is the *primary* bound. After fragility multiplier of ~0.84,
    # the size is ~0.05 * 100000 * 0.84 = $4200.
    assert Decimal(out["size_usd"]) > Decimal("3500")
    assert Decimal(out["size_usd"]) < Decimal("5000")
    assert out["reason"] == "ok"
    # binding could be wallet_cap; not fragility_curve because multiplier > 0.5
    assert out["binding_constraint"] in {"wallet_cap", "fragility_curve"}


def test_high_fragility_zero_size() -> None:
    out = kelly.compute_size(
        wins=20,
        losses=10,
        avg_win=Decimal("0.15"),
        avg_loss=Decimal("0.08"),
        fragility=Decimal("0.60"),
        wallet_balance_usd=Decimal("5000"),
        cfg=_cfg(),
    )
    assert out["size_usd"] == "0"
    assert out["reason"] == "below_minimum"
    assert out["binding_constraint"] == "fragility_curve"


def test_low_balance_min_position() -> None:
    out = kelly.compute_size(
        wins=10,
        losses=5,
        avg_win=Decimal("0.10"),
        avg_loss=Decimal("0.05"),
        fragility=Decimal("0.45"),
        wallet_balance_usd=Decimal("50"),
        cfg=_cfg(),
    )
    # wallet cap = 5 % * 50 = $2.50; below $5 floor
    assert out["size_usd"] == "0"
    assert out["reason"] == "below_minimum"


def test_single_win_clamped_payoff() -> None:
    out = kelly.compute_size(
        wins=1,
        losses=0,
        avg_win=Decimal("100"),  # absurd payoff
        avg_loss=Decimal("0.01"),
        fragility=Decimal("0.10"),
        wallet_balance_usd=Decimal("5000"),
        cfg=_cfg(),
    )
    # payoff clamps to 10; shrunk hit rate = 2/6 = 0.333
    # kelly_full = 0.333 - 0.667/10 = 0.267
    # kelly_use = 0.067 -> capped at 0.05 wallet pct
    assert out["reason"] == "ok"
    assert Decimal(out["payoff_ratio"]) == Decimal("10.000000")


def test_fragility_curve_piecewise() -> None:
    cfg = _cfg()
    curve = cfg["fragility_curve"]
    assert kelly.fragility_curve(Decimal("0.0"), curve) == Decimal("1.0")
    assert kelly.fragility_curve(Decimal("0.5"), curve) == Decimal("0.2")
    assert kelly.fragility_curve(Decimal("0.25"), curve) == Decimal("0.6")
    # discontinuity: anything strictly above 0.5 drops to 0
    assert kelly.fragility_curve(Decimal("0.51"), curve) == Decimal("0")
    assert kelly.fragility_curve(Decimal("0.75"), curve) == Decimal("0")
    assert kelly.fragility_curve(Decimal("1.0"), curve) == Decimal("0")
    assert kelly.fragility_curve(Decimal("1.5"), curve) == Decimal("0")
    assert kelly.fragility_curve(Decimal("-0.1"), curve) == Decimal("1.0")


def test_aggregate_history_skips_unattributed_rows() -> None:
    rows = [
        {"decision_id": "aegis-fader-1", "attribution": {"realized_pnl_pct": "0.10"}},
        {"decision_id": "aegis-fader-2", "attribution": {"realized_pnl_pct": "-0.05"}},
        # unattributed
        {"decision_id": "aegis-fader-3"},
        # wrong strategy
        {"decision_id": "other-1", "attribution": {"realized_pnl_pct": "0.50"}},
        # zero PnL -> neither win nor loss
        {"decision_id": "aegis-fader-4", "attribution": {"realized_pnl_pct": "0"}},
    ]
    hist = kelly.aggregate_history(rows, "aegis-fader")
    assert hist["wins"] == 1
    assert hist["losses"] == 1
    assert hist["avg_win"] == Decimal("0.10")
    assert hist["avg_loss"] == Decimal("0.05")


def test_cli_size_writes_envelope_to_blackbox(
    aegis_tmp_home: Path,
    aegis_config: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import argparse

    from skills._shared._aegis_common import blackbox_dir

    args = argparse.Namespace(
        strategy_id="aegis-fader",
        token="FAKE_CA",
        chain="solana",
        fragility="0.20",
        wallet_balance_usd="5000.00",
        wins=20,
        losses=10,
        avg_win="0.15",
        avg_loss="0.08",
    )
    rc = kelly.cmd_size(args)
    assert rc == 0
    out = capsys.readouterr().out
    body = json.loads(out)
    assert body["skill"] == "aegis-quartermaster"
    assert body["event"] == "size_computed"
    assert body["chain"] == "solana"
    decisions = (blackbox_dir() / "decisions.jsonl").read_text(encoding="utf-8")
    assert "aegis-quartermaster" in decisions
    assert "size_computed" in decisions
