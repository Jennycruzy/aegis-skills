"""Unit tests for aegis-blackbox decay metric."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from tests._loader import load_script

decay_module = load_script("aegis-blackbox", "decay")


def _config() -> dict[str, float | int]:
    return {
        "decay_long_term_days": 30,
        "decay_recent_days": 7,
        "retire_threshold": 1.0,
        "monitor_threshold": 0.5,
    }


def _row(source: str, ts_ms: int, ret: float) -> dict[str, object]:
    return {
        "schema_version": 1,
        "ts_ms": ts_ms,
        "skill": "aegis-fader",
        "source_id": source,
        "forward_return_1h": f"{ret:.6f}",
    }


_NOW = 1_750_000_000_000  # fixed UTC ms


def test_active_source_when_recent_matches_long_term() -> None:
    long_window = 30 * 86_400_000
    rows = []
    for i in range(30):
        rows.append(_row("smart_money:A", _NOW - long_window + i * 86_400_000, 0.01))
    for i in range(10):
        rows.append(_row("smart_money:A", _NOW - 6 * 86_400_000 + i * 3600_000, 0.01))
    out = decay_module.compute_decay(
        rows,
        long_term_ms=30 * 86_400_000,
        recent_ms=7 * 86_400_000,
        now_ts=_NOW,
        cfg=_config(),
    )
    assert out["smart_money:A"]["band"] == "ACTIVE"


def test_retire_source_when_recent_collapses() -> None:
    rows = []
    for i in range(50):
        rows.append(_row("kol:B", _NOW - 25 * 86_400_000 + i * 3600_000, 0.05))
    for i in range(10):
        rows.append(_row("kol:B", _NOW - 6 * 86_400_000 + i * 3600_000, -0.10))
    out = decay_module.compute_decay(
        rows,
        long_term_ms=30 * 86_400_000,
        recent_ms=7 * 86_400_000,
        now_ts=_NOW,
        cfg=_config(),
    )
    assert out["kol:B"]["band"] == "RETIRE"


def test_monitor_band_emerges_with_partial_drift() -> None:
    rows = []
    # spread long-term values to give nonzero std
    for i in range(30):
        rows.append(_row("whale:C", _NOW - 20 * 86_400_000 + i * 3600_000, 0.04 + (i % 5) * 0.005))
    for i in range(8):
        rows.append(_row("whale:C", _NOW - 5 * 86_400_000 + i * 3600_000, 0.005))
    out = decay_module.compute_decay(
        rows,
        long_term_ms=30 * 86_400_000,
        recent_ms=7 * 86_400_000,
        now_ts=_NOW,
        cfg=_config(),
    )
    info = out["whale:C"]
    assert info["band"] in {"MONITOR", "RETIRE"}
    assert info["decay_score"] is not None and float(info["decay_score"]) > 0


def test_insufficient_data_band() -> None:
    rows = [_row("kol:D", _NOW - 86_400_000, 0.0)]
    out = decay_module.compute_decay(
        rows,
        long_term_ms=30 * 86_400_000,
        recent_ms=7 * 86_400_000,
        now_ts=_NOW,
        cfg=_config(),
    )
    info = out["kol:D"]
    assert info["band"] == "INSUFFICIENT_DATA"
    assert info["decay_score"] is None


def test_std_near_zero_does_not_explode() -> None:
    rows = []
    for i in range(40):
        rows.append(_row("kol:E", _NOW - 20 * 86_400_000 + i * 3600_000, 0.05))
    for i in range(8):
        rows.append(_row("kol:E", _NOW - 5 * 86_400_000 + i * 3600_000, 0.045))
    out = decay_module.compute_decay(
        rows,
        long_term_ms=30 * 86_400_000,
        recent_ms=7 * 86_400_000,
        now_ts=_NOW,
        cfg=_config(),
    )
    info = out["kol:E"]
    assert info["decay_score"] is not None
    # diff = 0.005 ; denom = max(0.001, 0) = 0.001 -> score = 5 -> RETIRE
    assert info["band"] == "RETIRE"


def test_recompute_writes_decay_report(
    aegis_tmp_home: Path,
    aegis_config: Path,
) -> None:
    from skills._shared._aegis_common import blackbox_dir

    bb = blackbox_dir()
    (bb / "signal_performance.jsonl").write_text("", encoding="utf-8")

    rc = decay_module.cmd_recompute(argparse.Namespace(chain="solana"))
    assert rc == 0
    out_path = bb / "decay_report.json"
    body = json.loads(out_path.read_text(encoding="utf-8"))
    assert body["schema_version"] == 1
    assert isinstance(body["sources"], dict)


@pytest.mark.parametrize(
    ("decay_score", "band"),
    [
        (None, "INSUFFICIENT_DATA"),
        (0.0, "ACTIVE"),
        (0.49, "ACTIVE"),
        (0.5, "MONITOR"),
        (0.99, "MONITOR"),
        (1.0, "RETIRE"),
        (5.0, "RETIRE"),
    ],
)
def test_classify_thresholds(decay_score: float | None, band: str) -> None:
    out = decay_module._classify(decay_score, _config())
    assert out == band
