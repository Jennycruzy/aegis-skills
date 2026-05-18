"""Integration test for the WS-driven hibernation trigger.

Synthesises a WebSocket payload, feeds it through ws_watcher.match_trigger, and verifies the
hibernator engages with the expected reason. Does not require sandbox creds.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests._loader import load_script

drawdown = load_script("aegis-hibernator", "drawdown")
ws_watcher = load_script("aegis-hibernator", "ws_watcher")

_NOW = 1_750_000_000_000


def test_dev_sell_trigger_engages_hibernation(
    aegis_tmp_home: Path, aegis_config: Path,
) -> None:
    from skills._shared._aegis_common import blackbox_dir

    payload = {
        "channel": "address-tracker-activity",
        "txType": "sell",
        "walletAddress": "DEV_WALLET_1",
        "amount": "1000",
    }
    reason = ws_watcher.match_trigger(payload)
    assert reason == "dev_sell"

    # Trigger engagement directly through the helper used in production
    ws_watcher._engage_via_drawdown(reason, "sha256:test", "address-tracker-activity")

    state = drawdown.load_state()
    assert state["status"] == "HIBERNATED"
    assert state["reason"] == "dev_sell"

    log = (blackbox_dir() / "decisions.jsonl").read_text(encoding="utf-8")
    assert "ws_trigger" in log
    assert "dev_sell" in log


def test_migrating_trigger_engages_hibernation(
    aegis_tmp_home: Path, aegis_config: Path,
) -> None:
    payload = {
        "channel": "dex-market-memepump-new-token-openapi",
        "stage": "MIGRATED",
        "tokenAddress": "FAKE_CA",
    }
    reason = ws_watcher.match_trigger(payload)
    assert reason == "migrating"

    ws_watcher._engage_via_drawdown(reason, "sha256:test", payload["channel"])
    state = drawdown.load_state()
    assert state["status"] == "HIBERNATED"
    assert state["reason"] == "migrating"


def test_cluster_shift_trigger(aegis_tmp_home: Path, aegis_config: Path) -> None:
    payload = {
        "channel": "dex-market-memepump-update-metrics-openapi",
        "top10PercentChangePct": "0.12",
    }
    reason = ws_watcher.match_trigger(payload)
    assert reason == "cluster_shift_gt_10pct"


def test_buy_event_does_not_trigger() -> None:
    payload = {
        "channel": "address-tracker-activity",
        "txType": "buy",
        "walletAddress": "DEV_WALLET_1",
    }
    assert ws_watcher.match_trigger(payload) is None


def test_unknown_channel_does_not_trigger() -> None:
    assert ws_watcher.match_trigger({"channel": "other"}) is None
    assert ws_watcher.match_trigger({}) is None


def test_engagement_records_payload_digest_not_payload(
    aegis_tmp_home: Path, aegis_config: Path,
) -> None:
    from skills._shared._aegis_common import blackbox_dir

    digest = "sha256:abcdef0123456789"
    ws_watcher._engage_via_drawdown("dev_sell", digest, "address-tracker-activity")
    line = (blackbox_dir() / "decisions.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    body = json.loads(line)
    assert body["payload_digest"] == digest
    # ensure we never log a literal "txType" key (would imply raw payload leakage)
    assert "txType" not in line
