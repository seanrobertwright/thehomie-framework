from __future__ import annotations

import hashlib
import json
from pathlib import Path

from crypto_round.config import DiscordSource, MarketRoundSettings
from crypto_round.db import CryptoRoundDB
from crypto_round.delivery import deliver_completed_round, render_round_recap
from crypto_round.models import CryptoRoundOutput
from discord_alpha.notify import DiscordAlphaTarget, DiscordMessageReceipt


def _settings(tmp_path: Path) -> MarketRoundSettings:
    return MarketRoundSettings(
        enabled=True,
        domain="crypto",
        debauchery_alias="Debauchery",
        approved_guild_id="999",
        discord_channels=(DiscordSource("1001", "war-room", "primary"),),
        x_feeds=("for_you",),
        every_hours=2,
        discord_minute=2,
        x_minute=32,
        research_prefetch_times=("07:45", "19:45"),
        rollup_times=("08:00", "20:00"),
        timezone="America/Los_Angeles",
        discord_messages_per_channel=250,
        x_items_per_feed=100,
        last30days_days=3,
        last30days_runs_per_day=2,
        max_evidence_chars=48000,
        model_tier="quality",
        judge_tier="quality",
        max_turns=6,
        delivery_enabled=True,
        delivery_binding_file=tmp_path / "bindings.json",
        delivery_ping_on_call=True,
    )


def _store(db: CryptoRoundDB, round_id: str, source: str, item_id: str, payload: dict) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    assert db.store_evidence(round_id, source, item_id, payload, digest)
    return f"{source}:{item_id}"


def _completed_round(tmp_path: Path) -> tuple[CryptoRoundDB, CryptoRoundOutput]:
    db = CryptoRoundDB(tmp_path / "rounds.db")
    round_id = "crypto-20260802T1200Z"
    db.ensure_round(round_id, "crypto", "2026-08-02T12:00:00+00:00")
    indicator_id = _store(
        db,
        round_id,
        "market:exchange",
        "crypto_indicators:1",
        {
            "tool": "crypto_indicators",
            "arguments": {"timeframes": "15m,1h,4h,1d"},
            "result": "\n".join(
                [
                    "| chart.at15min.rsi14.value | 44.10 |",
                    "| chart.at15min.macd12_26_9.hist | -12.00 |",
                    "| chart.at01hour.price.close | $63,250.00 |",
                    "| chart.at01hour.rsi14.value | 48.50 |",
                    "| chart.at01hour.macd12_26_9.hist | 18.25 |",
                    "| chart.at04hour.rsi14.value | 53.20 |",
                    "| chart.at04hour.macd12_26_9.hist | 42.00 |",
                    "| chart.at01day.rsi14.value | 57.00 |",
                    "| chart.at01day.macd12_26_9.hist | 105.00 |",
                ]
            ),
        },
    )
    level_id = _store(
        db,
        round_id,
        "market:exchange",
        "crypto_levels:2",
        {
            "tool": "crypto_levels",
            "arguments": {"timeframe": "4h"},
            "result": (
                "## Fib levels (4h)\n- 0.382: 62,900.00\n- 0.5: 62,400.00\n- 0.618: 61,900.00"
            ),
        },
    )
    db.record_source(round_id, "market:exchange", status="ok", evidence_count=2)
    db.record_source(round_id, "discord:debauchery", status="ok", evidence_count=3)
    db.record_source(round_id, "x:for_you", status="ok", evidence_count=5)
    assert db.claim_cognition(round_id, "sha256:test")
    output = CryptoRoundOutput.parse(
        {
            "round_id": round_id,
            "decision": "call",
            "generated_at": "2026-08-02T12:32:00+00:00",
            "source_health": [],
            "regime": "range breakout attempt",
            "levels": ["63,000 support", "64,200 trigger"],
            "catalysts": ["Polymarket confirms no extreme crowding"],
            "opportunities": [
                {
                    "opportunity_id": "mint-1",
                    "kind": "nft_mint",
                    "title": "Verified upcoming mint",
                    "asset": "COLLECTION",
                    "action": "Review official mint terms; do not connect a wallet yet.",
                    "thesis": "Official project and Debauchery timing agree.",
                    "timing": "next 24h",
                    "confidence": 0.66,
                    "evidence_ids": [indicator_id],
                    "risks": ["impersonator links"],
                }
            ],
            "signals": [
                {
                    "symbol": "BTC/USDT",
                    "direction": "long",
                    "thesis": "Momentum improves above support.",
                    "confidence": 0.64,
                    "evidence_ids": [indicator_id, level_id],
                    "invalidators": ["4h close below 62,900"],
                }
            ],
            "paper_calls": [
                {
                    "call_id": "paper-btc-1",
                    "instrument": "BTC/USDT",
                    "side": "buy",
                    "entry": 63250.0,
                    "stop": 62850.0,
                    "target": 64200.0,
                    "horizon": "4h",
                    "evidence_ids": [indicator_id, level_id],
                }
            ],
            "recap": "Wait for entry confirmation; do not chase.",
            "warnings": [],
        },
        expected_round_id=round_id,
    )
    db.complete(output)
    return db, output


def test_host_recap_contains_ta_and_actionable_paper_setup(tmp_path: Path) -> None:
    db, output = _completed_round(tmp_path)
    rendered = render_round_recap(output, db.round_evidence(output.round_id), _settings(tmp_path))
    assert "15m RSI 44.10 / MACD-h -12.00" in rendered
    assert "4h RSI 53.20 / MACD-h 42.00" in rendered
    assert "0.618 61,900.00" in rendered
    assert "BUY BTC/USDT @ 63,250" in rendered
    assert "stop 62,850" in rendered and "target 64,200" in rendered
    assert "Alpha 1 [nft_mint] Verified upcoming mint" in rendered
    assert "PAPER-ONLY" in rendered


def test_completed_round_posts_once_and_pings_only_for_call(tmp_path: Path) -> None:
    db, output = _completed_round(tmp_path)
    sent: list[tuple[str, bool]] = []
    target = DiscordAlphaTarget("secret", "999", "2001", ("3001",))

    def resolver(**kwargs):
        assert kwargs["bindings_path"] == _settings(tmp_path).delivery_binding_file
        return target

    def sender(actual_target, text, *, ping_operator=False):
        assert actual_target is target
        sent.append((text, ping_operator))
        return DiscordMessageReceipt("4001", "2001", "5001")

    first = deliver_completed_round(
        output.round_id,
        settings=_settings(tmp_path),
        ledger=db,
        target_resolver=resolver,
        sender=sender,
    )
    second = deliver_completed_round(
        output.round_id,
        settings=_settings(tmp_path),
        ledger=db,
        target_resolver=resolver,
        sender=sender,
    )
    assert first == {"status": "complete", "posted": True, "message_id": "4001"}
    assert second == {"status": "complete", "posted": False}
    assert len(sent) == 1 and sent[0][1] is True
    assert db.delivery_status(output.round_id)["message_id"] == "4001"


def test_target_gap_does_not_consume_delivery_claim(tmp_path: Path) -> None:
    db, output = _completed_round(tmp_path)
    result = deliver_completed_round(
        output.round_id,
        settings=_settings(tmp_path),
        ledger=db,
        target_resolver=lambda **kwargs: None,
    )
    assert result == {"status": "target_unavailable", "posted": False}
    assert db.delivery_status(output.round_id) is None
