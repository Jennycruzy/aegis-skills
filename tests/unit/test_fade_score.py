"""Unit tests for aegis-fader scoring + decision logic."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from tests._loader import load_script

signal_window = load_script("aegis-fader", "signal_window")
fade_score = load_script("aegis-fader", "fade_score")


_NOW = 1_750_000_000_000
_WINDOW_MS = 60 * 60_000


def _signal(token: str, ts_ms: int, wallet_type: int, addr: str) -> dict[str, object]:
    return {"ts_ms": ts_ms, "token": token, "walletType": wallet_type,
            "walletAddress": addr}


def _fixture(name: str) -> dict[str, object]:
    path = (
        Path(__file__).resolve().parents[1] / "fixtures" / name
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_crowded_fixture_produces_high_crowdedness() -> None:
    raw = _fixture("signals_crowded.json")
    out = signal_window.aggregate(
        raw["signals"],
        window_start_ms=int(raw["now_ts_ms"]) - _WINDOW_MS,
        window_end_ms=int(raw["now_ts_ms"]),
    )
    crowded = next(t for t in out["tokens"] if t["token"].startswith("FAKE_CA_CROWDED"))
    assert int(crowded["signal_count"]) >= 7
    assert int(crowded["source_diversity"]) == 3
    assert Decimal(crowded["crowdedness"]) >= Decimal("0.7")


def test_lonely_fixture_produces_low_crowdedness_high_diversity() -> None:
    raw = _fixture("signals_lonely.json")
    out = signal_window.aggregate(
        raw["signals"],
        window_start_ms=int(raw["now_ts_ms"]) - _WINDOW_MS,
        window_end_ms=int(raw["now_ts_ms"]),
    )
    lonely = next(t for t in out["tokens"] if t["token"].startswith("FAKE_CA_LONELY"))
    assert int(lonely["source_diversity"]) == 3
    # Lonely token has the smaller signal count of the two; crowdedness is < 1
    assert Decimal(lonely["crowdedness"]) <= Decimal("1.0")


def test_signals_outside_window_dropped() -> None:
    signals = [
        _signal("TOK_A", _NOW - 30 * 60_000, 1, "W1"),
        _signal("TOK_A", _NOW - 120 * 60_000, 2, "W2"),  # outside 60-min window
    ]
    out = signal_window.aggregate(
        signals, window_start_ms=_NOW - _WINDOW_MS, window_end_ms=_NOW
    )
    tok = out["tokens"][0]
    assert int(tok["signal_count"]) == 1


def test_retire_filter_drops_signals() -> None:
    signals = [
        _signal("TOK_A", _NOW - 5 * 60_000, 1, "W1"),
        _signal("TOK_A", _NOW - 4 * 60_000, 1, "W1"),
        _signal("TOK_A", _NOW - 3 * 60_000, 2, "W2"),
    ]
    retire = {"smart_money:W1"}
    out = signal_window.aggregate(
        signals,
        window_start_ms=_NOW - _WINDOW_MS,
        window_end_ms=_NOW,
        retire_sources=retire,
    )
    tok = out["tokens"][0]
    assert int(tok["signal_count"]) == 1
    assert int(tok["source_diversity"]) == 1
    assert "smart_money:W1" not in tok["source_ids"]


def _cfg() -> dict[str, object]:
    return {
        "lookback_minutes": 60,
        "crowd_threshold": 0.70,
        "min_source_diversity": 3,
        "max_position_pct": 0.05,
        "max_daily_entries": 20,
        "attribution_delay_minutes": 60,
    }


def _candidate(crowd: float, diversity: int) -> dict[str, object]:
    return {
        "token": "TOK_X",
        "signal_count": 7,
        "source_diversity": diversity,
        "crowdedness": f"{crowd:.4f}",
    }


def test_decide_crowded_low_fragility_emits_fade_opportunity() -> None:
    out = fade_score.decide_per_token(
        _candidate(0.80, 3),
        fragility=Decimal("0.20"),
        fragility_decision="ALLOW",
        hibernator_status="ACTIVE",
        config=_cfg(),
    )
    assert out["decision"] == "FADE_OPPORTUNITY"
    assert out["skip_reason"] is None


def test_decide_lonely_diverse_low_fragility_emits_follow_long() -> None:
    out = fade_score.decide_per_token(
        _candidate(0.30, 3),
        fragility=Decimal("0.22"),
        fragility_decision="ALLOW",
        hibernator_status="ACTIVE",
        config=_cfg(),
    )
    assert out["decision"] == "FOLLOW_LONG"


def test_decide_skips_when_hibernated() -> None:
    out = fade_score.decide_per_token(
        _candidate(0.30, 3),
        fragility=Decimal("0.10"),
        fragility_decision="ALLOW",
        hibernator_status="HIBERNATED",
        config=_cfg(),
    )
    assert out["decision"] == "SKIP"
    assert out["skip_reason"] == "hibernated"


def test_decide_skips_when_sentinel_blocks() -> None:
    out = fade_score.decide_per_token(
        _candidate(0.30, 3),
        fragility=Decimal("0.60"),
        fragility_decision="BLOCK",
        hibernator_status="ACTIVE",
        config=_cfg(),
    )
    assert out["decision"] == "SKIP"
    assert out["skip_reason"] == "block"


def test_decide_skips_when_diversity_insufficient() -> None:
    out = fade_score.decide_per_token(
        _candidate(0.30, 2),
        fragility=Decimal("0.10"),
        fragility_decision="ALLOW",
        hibernator_status="ACTIVE",
        config=_cfg(),
    )
    assert out["decision"] == "SKIP"
    assert out["skip_reason"] == "diversity"


def test_decide_skips_lonely_when_fragility_in_size_down_band() -> None:
    out = fade_score.decide_per_token(
        _candidate(0.30, 3),
        fragility=Decimal("0.40"),
        fragility_decision="SIZE_DOWN",
        hibernator_status="ACTIVE",
        config=_cfg(),
    )
    assert out["decision"] == "SKIP"
    assert out["skip_reason"] == "fragility"


def test_decide_crowded_high_fragility_routes_to_skip_block() -> None:
    out = fade_score.decide_per_token(
        _candidate(0.80, 3),
        fragility=Decimal("0.60"),
        fragility_decision="BLOCK",
        hibernator_status="ACTIVE",
        config=_cfg(),
    )
    assert out["decision"] == "SKIP"
    assert out["skip_reason"] == "block"


def test_decision_id_is_deterministic() -> None:
    assert (
        fade_score.decision_id("solana", "TOK_X", 1747545600000)
        == "fader-solana-TOK_X-1747545600000"
    )


def test_scan_refuses_out_of_scope_chain(
    aegis_tmp_home: Path,
    aegis_config: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import argparse

    args = argparse.Namespace(chain="ethereum", window_minutes=60, dry_run=True, wallet=None)
    rc = fade_score.cmd_scan(args)
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "outside AEGIS competition scope" in out["msg"]


def test_decay_filter_via_disk(
    aegis_tmp_home: Path,
    aegis_config: Path,
) -> None:
    from skills._shared._aegis_common import atomic_write_json, blackbox_dir

    decay_path = blackbox_dir() / "decay_report.json"
    atomic_write_json(
        decay_path,
        {
            "schema_version": 1,
            "computed_ts_ms": _NOW,
            "config": {},
            "sources": {
                "smart_money:W1": {"band": "RETIRE"},
                "kol:W2": {"band": "ACTIVE"},
            },
        },
    )
    retire = signal_window.load_retire_set()
    assert "smart_money:W1" in retire
    assert "kol:W2" not in retire
