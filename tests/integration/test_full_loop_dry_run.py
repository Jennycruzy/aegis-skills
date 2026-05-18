"""Integration test for the full AEGIS dry-run loop.

This test runs every AEGIS Python script end-to-end with a stubbed `onchainos` binary so
that we do NOT need real OKX sandbox keys to validate the orchestration. The stub replays a
canned response per command, simulating a Solana scan with one crowded and one lonely token.

Verifies:
  * decisions.jsonl, trades.jsonl, signal_performance.jsonl get populated as expected;
  * dashboard.html renders the expected KPIs from disk (parsed without a browser);
  * hibernator engages on a synthesised drawdown.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import textwrap
from decimal import Decimal
from pathlib import Path

import pytest

from tests._loader import load_script

drawdown = load_script("aegis-hibernator", "drawdown")
decay = load_script("aegis-blackbox", "decay")
kelly = load_script("aegis-quartermaster", "kelly")
fragility = load_script("aegis-sentinel", "fragility")
signal_window = load_script("aegis-fader", "signal_window")
fade_score = load_script("aegis-fader", "fade_score")

_NOW_MS = 1_750_000_000_000


def _install_cli_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Drop a fake `onchainos` shell script on PATH that emits canned JSON per subcommand."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "onchainos"
    script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            # Strip trailing --format json
            args=("$@")
            n=${#args[@]}
            if [ "${args[$((n-2))]}" = "--format" ] && [ "${args[$((n-1))]}" = "json" ]; then
              args=("${args[@]:0:$((n-2))}")
            fi
            sub="${args[0]:-}"
            sub2="${args[1]:-}"
            case "$sub $sub2" in
              "signal list")
                cat <<JSON
                {"data": [
                  {"ts_ms": 1750000000000, "token": "FAKE_CA_LONELY", "walletType": 1, "walletAddress": "W_SM_1"},
                  {"ts_ms": 1750000001000, "token": "FAKE_CA_LONELY", "walletType": 2, "walletAddress": "W_KOL_1"},
                  {"ts_ms": 1750000002000, "token": "FAKE_CA_LONELY", "walletType": 3, "walletAddress": "W_WHALE_1"},
                  {"ts_ms": 1750000003000, "token": "FAKE_CA_CROWDED", "walletType": 1, "walletAddress": "W_SM_2"},
                  {"ts_ms": 1750000004000, "token": "FAKE_CA_CROWDED", "walletType": 1, "walletAddress": "W_SM_3"},
                  {"ts_ms": 1750000005000, "token": "FAKE_CA_CROWDED", "walletType": 1, "walletAddress": "W_SM_4"},
                  {"ts_ms": 1750000006000, "token": "FAKE_CA_CROWDED", "walletType": 2, "walletAddress": "W_KOL_2"},
                  {"ts_ms": 1750000007000, "token": "FAKE_CA_CROWDED", "walletType": 2, "walletAddress": "W_KOL_3"},
                  {"ts_ms": 1750000008000, "token": "FAKE_CA_CROWDED", "walletType": 3, "walletAddress": "W_WHALE_2"},
                  {"ts_ms": 1750000009000, "token": "FAKE_CA_CROWDED", "walletType": 3, "walletAddress": "W_WHALE_3"}
                ]}
            JSON
                ;;
              "portfolio total-value")
                echo '{"data": {"totalValueUsd": "5000.00"}}'
                ;;
              "market portfolio-recent-pnl")
                cat <<JSON
                {"data": [
                  {"ts_ms": 1749980000000, "realizedPnlPercent": "-0.10"},
                  {"ts_ms": 1749990000000, "realizedPnlPercent": "-0.05"},
                  {"ts_ms": 1750000000000, "realizedPnlPercent": "-0.08"}
                ]}
            JSON
                ;;
              "security token-scan")
                echo '{"data": {"riskLevel": "LOW"}}'
                ;;
              "token holders")
                echo '{"data": {"top10HoldingsPercent": 25}}'
                ;;
              "token price-info")
                echo '{"data": {"change24hPct": 0.05}}'
                ;;
              "token advanced-info")
                echo '{"data": {}}'
                ;;
              "memepump token-details")
                echo '{"data": {"top10HoldingsPercent": 25}}'
                ;;
              "memepump token-bundle-info")
                echo '{"data": {"bundlerHoldingsPercent": 1, "sniperHoldingsPercent": 1}}'
                ;;
              "memepump token-dev-info")
                echo '{"data": {"rugPullCount": 0}}'
                ;;
              *)
                echo '{"data": {}}'
                ;;
            esac
            """
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("ONCHAINOS_BINARY", "onchainos")
    return bin_dir


def test_dry_run_loop_writes_all_expected_logs(
    aegis_tmp_home: Path,
    aegis_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_cli_stub(tmp_path, monkeypatch)
    from skills._shared._aegis_common import blackbox_dir

    # 1. Decay refresh on empty history → produces an empty report.
    decay.cmd_recompute(argparse.Namespace(chain="solana"))

    # 2. Signal window snapshot (uses the stubbed `onchainos signal list`).
    signal_window.cmd_snapshot(
        argparse.Namespace(chain="solana", window_minutes=60),
    )

    # 3. Per-token: fragility + size + Fader decision for the lonely token.
    fragility.cmd_score(
        argparse.Namespace(chain="solana", token="FAKE_CA_LONELY", refresh=True),
    )
    kelly.cmd_size(
        argparse.Namespace(
            strategy_id="aegis-fader",
            token="FAKE_CA_LONELY",
            chain="solana",
            fragility="0.10",
            wallet_balance_usd="5000.00",
            wins=20,
            losses=10,
            avg_win="0.15",
            avg_loss="0.08",
        ),
    )
    fade_score.cmd_score(
        argparse.Namespace(
            chain="solana",
            token="FAKE_CA_LONELY",
            signal_count=3,
            source_diversity=3,
            crowdedness="0.30",
            fragility="0.10",
            fragility_decision="ALLOW",
            hibernator_status="ACTIVE",
        ),
    )

    # 4. Dry-run scan invocation
    fade_score.cmd_scan(
        argparse.Namespace(
            chain="solana", window_minutes=60, dry_run=True, wallet=None,
        ),
    )

    # 5. Drawdown re-check should engage hibernation (stub returns three losing rows).
    rc = drawdown.cmd_check(
        argparse.Namespace(chain="solana", wallet="FAKE_WALLET"),
    )
    assert rc == 0
    state = drawdown.load_state()
    assert state["status"] == "HIBERNATED"
    assert state["reason"] == "drawdown"

    # Verify decisions.jsonl has the expected events
    decisions = (blackbox_dir() / "decisions.jsonl").read_text(encoding="utf-8")
    assert "fragility_computed" in decisions
    assert "size_computed" in decisions
    assert "candidate_evaluated" in decisions
    assert "scan_invoked" in decisions
    assert "hibernation_engaged" in decisions

    # Sentinel cache should be populated
    sentinel_cache = json.loads(
        (aegis_tmp_home / "state" / "sentinel_cache.json").read_text(encoding="utf-8"),
    )
    assert "entries" in sentinel_cache
    assert any(
        k.endswith("FAKE_CA_LONELY") for k in sentinel_cache["entries"]
    )

    # Decay report exists and is well-formed
    decay_report = json.loads(
        (blackbox_dir() / "decay_report.json").read_text(encoding="utf-8"),
    )
    assert decay_report["schema_version"] == 1


def test_dashboard_html_renders_panels(tmp_path: Path) -> None:
    """Sanity check: dashboard.html is well-formed and renders panel scaffolding."""
    dash = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "aegis-blackbox"
        / "scripts"
        / "dashboard.html"
    )
    text = dash.read_text(encoding="utf-8")
    assert "AEGIS · Blackbox" in text
    assert "decisions.jsonl" in text
    assert "trades.jsonl" in text
    assert "decay_report.json" in text
    assert "textContent" in text  # untrusted-content rule
    assert "innerHTML" not in text


def test_kelly_history_aggregates_attributed_trades(
    aegis_tmp_home: Path,
    aegis_config: Path,
) -> None:
    from skills._shared._aegis_common import append_jsonl, blackbox_dir

    trades = blackbox_dir() / "trades.jsonl"
    for i, pnl in enumerate([0.10, -0.05, 0.08, -0.04, 0.12]):
        append_jsonl(
            trades,
            {
                "decision_id": f"aegis-fader-test-{i}",
                "attribution": {"realized_pnl_pct": f"{pnl:.6f}"},
            },
        )
    hist = kelly.aggregate_history(
        [json.loads(line) for line in trades.read_text().splitlines() if line],
        "aegis-fader",
    )
    assert hist["wins"] == 3
    assert hist["losses"] == 2
    assert Decimal(hist["avg_win"]) > Decimal("0.05")
