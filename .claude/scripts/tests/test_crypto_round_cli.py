from __future__ import annotations

import json
import sys
from pathlib import Path

from click.testing import CliRunner

CHAT_DIR = Path(__file__).resolve().parents[2] / "chat"
SCRIPTS_DIR = Path(__file__).resolve().parents[1]
for path in (CHAT_DIR, SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import cli as cli_module  # noqa: E402
from cli import main as cli_main  # noqa: E402

from lib.agentic_turn import (  # noqa: E402
    SCHEDULED_TOOL_ALLOWLIST,
    SCHEDULED_TOOL_DENYLIST,
)


def test_crypto_round_command_surface() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_main, ["crypto", "round", "--help"])
    assert result.exit_code == 0
    for command in ("status", "sources", "run", "paper", "promotion"):
        assert command in result.output


def test_crypto_round_status_quiet_json(monkeypatch) -> None:
    monkeypatch.setattr(
        cli_module,
        "_crypto_round_status_payload",
        lambda: {
            "success": True,
            "enabled": True,
            "config": {"cadence_hours": 2},
            "ledger": {"state_counts": {"complete": 1}},
        },
    )
    result = CliRunner().invoke(cli_main, ["crypto", "round", "status", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["ledger"]["state_counts"] == {"complete": 1}


def test_crypto_round_sources_never_emit_watermarks(monkeypatch) -> None:
    class FakeDB:
        def __init__(self, **kwargs):
            pass

        def source_status(self):
            return [
                {
                    "source": "discord:debauchery",
                    "status": "ok",
                    "evidence_count": 3,
                    "watermark": "private-platform-id",
                }
            ]

    import crypto_round.db

    monkeypatch.setattr(crypto_round.db, "CryptoRoundDB", FakeDB)
    result = CliRunner().invoke(cli_main, ["crypto", "round", "sources", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["sources"][0]["source"] == "discord:debauchery"
    assert "watermark" not in payload["sources"][0]
    assert "private-platform-id" not in result.output


def test_crypto_round_research_run_emits_metadata_not_raw_payload(monkeypatch) -> None:
    import crypto_round.last30days_adapter

    monkeypatch.setattr(
        crypto_round.last30days_adapter,
        "run",
        lambda: {
            "success": True,
            "sources_excluded": ["x"],
            "result": {"raw_private_signal": "never print me"},
        },
    )
    result = CliRunner().invoke(
        cli_main,
        ["crypto", "round", "run", "--stage", "research", "--json"],
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["sources_excluded"] == ["x"]
    assert "raw_private_signal" not in result.output


def test_crypto_round_promotion_is_read_only(monkeypatch) -> None:
    class FakeDB:
        def __init__(self, **kwargs):
            pass

        def promotion_readiness(self):
            return {
                "status": "NOT_ELIGIBLE",
                "proposal_only": True,
                "live_arm_allowed": False,
                "live_execute_allowed": False,
                "failed_gates": ["resolved_paper_calls"],
            }

    import crypto_round.db

    monkeypatch.setattr(crypto_round.db, "CryptoRoundDB", FakeDB)
    result = CliRunner().invoke(cli_main, ["crypto", "round", "promotion", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "NOT_ELIGIBLE"
    assert payload["live_arm_allowed"] is False
    assert payload["live_execute_allowed"] is False


def test_scheduled_scope_contains_zero_paid_reads_and_excludes_live_authority() -> None:
    assert {
        "crypto_last30days_read",
        "crypto_prediction_markets",
        "crypto_prediction_book",
    } <= SCHEDULED_TOOL_ALLOWLIST
    for denied in (
        "terminal",
        "process",
        "read_file",
        "write_file",
        "skill_manage",
        "x_search",
        "crypto_submit_bracket",
    ):
        assert denied in SCHEDULED_TOOL_DENYLIST
        assert denied not in SCHEDULED_TOOL_ALLOWLIST


def test_research_scheduler_shape_is_twice_daily_and_bounded() -> None:
    scripts = SCRIPTS_DIR
    setup = (scripts / "setup_crypto_research_scheduler.ps1").read_text(encoding="utf-8")
    runner = (scripts / "run_crypto_research.bat").read_text(encoding="utf-8")
    assert 'New-ScheduledTaskTrigger -Daily -At "07:45"' in setup
    assert 'New-ScheduledTaskTrigger -Daily -At "19:45"' in setup
    assert "MultipleInstances IgnoreNew" in setup
    assert "Minutes 10" in setup
    assert "crypto_round.research_runner --run" in runner
    assert "--no-browser-cookies" not in runner  # enforced inside the pinned adapter
