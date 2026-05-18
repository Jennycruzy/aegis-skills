"""Unit tests for aegis-sentinel fragility composition.

The pure-function `compose_score` is exhaustively exercised. CLI-touching factor extractors
are covered in integration tests with mocked CLI output (out of scope for unit).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from tests._loader import load_script

fragility = load_script("aegis-sentinel", "fragility")


_WEIGHTS = {
    "cluster_concentration": 0.30,
    "bundle_sniper": 0.25,
    "dev_rug_history": 0.20,
    "holder_velocity": 0.15,
    "lp_unlock_proximity": 0.10,
}


def _compose(values: dict[str, float | None], *, chain: str = "solana",
             risk: str | None = None) -> dict[str, object]:
    decimal_values: dict[str, Decimal | None] = {
        k: (Decimal(str(v)) if v is not None else None) for k, v in values.items()
    }
    return fragility.compose_score(
        decimal_values,
        weights=_WEIGHTS,
        block_threshold=Decimal("0.50"),
        size_down_threshold=Decimal("0.30"),
        security_risk_level=risk,
        chain=chain,
    )


def test_clean_token_allows() -> None:
    out = _compose(
        {
            "cluster_concentration": 0.10,
            "bundle_sniper": 0.05,
            "dev_rug_history": 0.00,
            "holder_velocity": 0.10,
            "lp_unlock_proximity": 0.00,
        }
    )
    # 0.10*0.30 + 0.05*0.25 + 0*0.20 + 0.10*0.15 + 0*0.10 = 0.03+0.0125+0+0.015+0 = 0.0575
    assert out["decision"] == "ALLOW"
    assert Decimal(str(out["fragility"])) < Decimal("0.30")


def test_fragile_token_blocks() -> None:
    out = _compose(
        {
            "cluster_concentration": 0.85,
            "bundle_sniper": 0.70,
            "dev_rug_history": 0.60,
            "holder_velocity": 0.55,
            "lp_unlock_proximity": 0.40,
        }
    )
    # 0.85*0.30+0.70*0.25+0.60*0.20+0.55*0.15+0.40*0.10
    # = 0.255+0.175+0.120+0.0825+0.040 = 0.6725 -> BLOCK
    assert out["decision"] == "BLOCK"
    assert Decimal(str(out["fragility"])) >= Decimal("0.50")


def test_size_down_band() -> None:
    out = _compose(
        {
            "cluster_concentration": 0.50,
            "bundle_sniper": 0.30,
            "dev_rug_history": 0.20,
            "holder_velocity": 0.30,
            "lp_unlock_proximity": 0.20,
        }
    )
    # 0.50*0.30+0.30*0.25+0.20*0.20+0.30*0.15+0.20*0.10
    # = 0.15+0.075+0.040+0.045+0.020 = 0.330 -> SIZE_DOWN
    assert out["decision"] == "SIZE_DOWN"


def test_missing_factor_defaults_to_half_and_records_reason() -> None:
    out = _compose(
        {
            "cluster_concentration": None,
            "bundle_sniper": 0.0,
            "dev_rug_history": 0.0,
            "holder_velocity": 0.0,
            "lp_unlock_proximity": 0.0,
        }
    )
    # cluster default 0.5 * 0.30 = 0.15 → ALLOW band
    assert out["decision"] == "ALLOW"
    reasons = out["reasons"]
    assert isinstance(reasons, list)
    assert "cluster_concentration_unavailable" in reasons


def test_critical_security_forces_block() -> None:
    out = _compose(
        {
            "cluster_concentration": 0.0,
            "bundle_sniper": 0.0,
            "dev_rug_history": 0.0,
            "holder_velocity": 0.0,
            "lp_unlock_proximity": 0.0,
        },
        risk="CRITICAL",
    )
    assert out["decision"] == "BLOCK"
    assert Decimal(str(out["fragility"])) == Decimal("1.0000")
    assert "security_critical" in out["reasons"]


def test_non_solana_chain_defaults_solana_only_factors() -> None:
    # On X Layer, bundle_sniper and dev_rug_history should default to 0.5 with reasons
    out = _compose(
        {
            "cluster_concentration": 0.10,
            "bundle_sniper": None,
            "dev_rug_history": None,
            "holder_velocity": 0.10,
            "lp_unlock_proximity": 0.00,
        },
        chain="xlayer",
    )
    reasons = out["reasons"]
    assert "bundle_sniper_unavailable" in reasons
    assert "dev_rug_history_unavailable" in reasons
    # fragility includes the 0.5 defaults
    assert Decimal(str(out["fragility"])) > Decimal("0.15")


@pytest.mark.parametrize(
    ("frag_input", "expected_decision"),
    [
        (0.299, "ALLOW"),
        (0.30, "SIZE_DOWN"),
        (0.4999, "SIZE_DOWN"),
        (0.50, "BLOCK"),
    ],
)
def test_threshold_boundaries(frag_input: float, expected_decision: str) -> None:
    # Setting every factor to the same value produces fragility == that value, since the
    # weights sum to 1.0.
    out = _compose({k: frag_input for k in fragility.FACTORS})
    assert out["decision"] == expected_decision


def test_weights_must_sum_to_one() -> None:
    bad_weights = dict(_WEIGHTS)
    bad_weights["cluster_concentration"] = 0.50  # now sums to 1.20
    with pytest.raises(ValueError, match=r"must sum to 1\.0"):
        fragility.compose_score(
            {k: Decimal("0") for k in fragility.FACTORS},
            weights=bad_weights,
            block_threshold=Decimal("0.50"),
            size_down_threshold=Decimal("0.30"),
            security_risk_level=None,
            chain="solana",
        )


def test_factor_value_clamps_to_unit_interval() -> None:
    # value > 1 should clamp to 1; below 0 should clamp to 0
    out = _compose(
        {
            "cluster_concentration": 5.0,  # ridiculous; clamps to 1
            "bundle_sniper": -0.5,         # clamps to 0
            "dev_rug_history": 0.0,
            "holder_velocity": 0.0,
            "lp_unlock_proximity": 0.0,
        }
    )
    # cluster*0.30 = 0.30 -> SIZE_DOWN
    assert out["decision"] == "SIZE_DOWN"
    assert out["factors"]["cluster_concentration"]["value"] == "1.0000"
    assert out["factors"]["bundle_sniper"]["value"] == "0.0000"
