"""Unit tests for aegis-hibernator drawdown math + state transitions."""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tests._loader import load_script

drawdown = load_script("aegis-hibernator", "drawdown")
ws_watcher = load_script("aegis-hibernator", "ws_watcher")


_NOW = 1_750_000_000_000


def _row(ts_ms: int, pct: float) -> dict[str, object]:
    return {"ts_ms": ts_ms, "realizedPnlPercent": f"{pct:.6f}"}


def test_rolling_window_insufficient_history() -> None:
    rows = [_row(_NOW - 3600_000, -0.02)]
    summed, n = drawdown.rolling_pnl_pct(
        rows, now_ts=_NOW, window_hours=24, window_trades=10
    )
    assert summed is None
    assert n == 1


def test_rolling_window_exactly_at_threshold(
    aegis_tmp_home: Path, aegis_config: Path
) -> None:
    # Eight trades summing to exactly -0.15
    rows = [
        _row(_NOW - i * 3600_000, -0.15 / 8) for i in range(8)
    ]
    summed, n = drawdown.rolling_pnl_pct(
        rows, now_ts=_NOW, window_hours=24, window_trades=10
    )
    assert summed is not None
    assert n == 8
    assert abs(summed - Decimal("-0.15")) < Decimal("0.0001")


def test_rolling_window_deep_drawdown(
    aegis_tmp_home: Path, aegis_config: Path
) -> None:
    rows = [
        _row(_NOW - 12 * 3600_000, -0.10),
        _row(_NOW - 11 * 3600_000, -0.05),
        _row(_NOW - 10 * 3600_000, -0.08),
        _row(_NOW - 9 * 3600_000, +0.01),
        _row(_NOW - 8 * 3600_000, -0.04),
    ]
    summed, n = drawdown.rolling_pnl_pct(
        rows, now_ts=_NOW, window_hours=24, window_trades=10
    )
    assert summed is not None
    assert n == 5
    assert summed < Decimal("-0.15")


def test_window_uses_larger_bound(aegis_tmp_home: Path, aegis_config: Path) -> None:
    # 20 trades in the last 24 h, but window_trades=10. The hour window has more rows;
    # function should prefer it.
    rows = [_row(_NOW - i * 3_600_000, -0.01) for i in range(20)]
    summed, n = drawdown.rolling_pnl_pct(
        rows, now_ts=_NOW, window_hours=24, window_trades=10
    )
    assert summed is not None
    assert n == 20
    assert abs(summed - Decimal("-0.20")) < Decimal("0.0001")


def test_engage_writes_state_and_logs(
    aegis_tmp_home: Path, aegis_config: Path
) -> None:
    from skills._shared._aegis_common import blackbox_dir, state_dir

    state = drawdown.engage(
        "drawdown",
        now=_NOW,
        extra={"last_realized_pnl_pct": "-0.18"},
    )
    assert state["status"] == "HIBERNATED"
    assert state["reason"] == "drawdown"
    assert state["since_ts_ms"] == _NOW
    cool_off_ms = 60 * 60 * 1000
    assert state["cool_off_until_ts_ms"] == _NOW + cool_off_ms

    on_disk = json.loads((state_dir() / "hibernator.json").read_text())
    assert on_disk["status"] == "HIBERNATED"
    log = (blackbox_dir() / "decisions.jsonl").read_text(encoding="utf-8")
    assert "hibernation_engaged" in log


def test_wake_blocked_during_cool_off(
    aegis_tmp_home: Path, aegis_config: Path
) -> None:
    drawdown.engage("drawdown", now=_NOW)
    ok, msg, state = drawdown.wake(now=_NOW + 5)  # before cool-off
    assert ok is False
    assert "Cool-off active" in msg
    assert state["status"] == "HIBERNATED"


def test_wake_allowed_after_cool_off(
    aegis_tmp_home: Path, aegis_config: Path
) -> None:
    drawdown.engage("drawdown", now=_NOW)
    ok, _msg, state = drawdown.wake(now=_NOW + 90 * 60_000)  # 90 min later
    assert ok is True
    assert state["status"] == "ACTIVE"
    assert state["reason"] is None


def test_wake_idempotent_when_active(
    aegis_tmp_home: Path, aegis_config: Path
) -> None:
    ok, msg, state = drawdown.wake(now=_NOW)
    assert ok is True
    assert state["status"] == "ACTIVE"
    assert "already" in msg.lower()


def test_unknown_reason_rejected(aegis_tmp_home: Path, aegis_config: Path) -> None:
    with pytest.raises(ValueError, match="unknown reason"):
        drawdown.engage("rogue_reason", now=_NOW)


def test_extract_pnl_rows_handles_shapes() -> None:
    # list payload
    payload_list = [{"ts_ms": 1, "realizedPnlPercent": "0.01"}]
    assert drawdown._extract_pnl_rows(payload_list) == payload_list  # type: ignore[arg-type]
    # nested under "data"
    payload_nested = {"data": [{"ts_ms": 1, "realizedPnlPercent": "0.01"}]}
    out = drawdown._extract_pnl_rows(payload_nested)
    assert out == payload_nested["data"]
    # single object with the field
    payload_obj = {"ts_ms": 1, "realizedPnlPercent": "0.01"}
    out2 = drawdown._extract_pnl_rows(payload_obj)
    assert out2 == [payload_obj]


def test_status_cmd_prints_json(
    aegis_tmp_home: Path, aegis_config: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = drawdown.cmd_status(argparse.Namespace())
    assert rc == 0
    body = json.loads(capsys.readouterr().out)
    assert body["status"] == "ACTIVE"
    assert body["schema_version"] == 1


def test_ws_match_trigger_dev_sell() -> None:
    out = ws_watcher.match_trigger(
        {
            "channel": "address-tracker-activity",
            "txType": "sell",
            "walletAddress": "DEV_WALLET_1",
        }
    )
    assert out == "dev_sell"


def test_ws_match_trigger_migrating() -> None:
    out = ws_watcher.match_trigger(
        {"channel": "dex-market-memepump-new-token-openapi", "stage": "MIGRATED"}
    )
    assert out == "migrating"


def test_ws_match_trigger_cluster_shift() -> None:
    out = ws_watcher.match_trigger(
        {
            "channel": "dex-market-memepump-update-metrics-openapi",
            "top10PercentChangePct": "0.12",
        }
    )
    assert out == "cluster_shift_gt_10pct"


def test_ws_match_trigger_returns_none_on_unmatched() -> None:
    out = ws_watcher.match_trigger({"channel": "address-tracker-activity", "txType": "buy"})
    assert out is None
    out = ws_watcher.match_trigger({"channel": "some-other-channel"})
    assert out is None
