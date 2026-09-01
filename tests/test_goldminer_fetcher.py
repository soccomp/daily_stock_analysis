# -*- coding: utf-8 -*-
"""Unit tests for the read-only Windows GoldMiner market-data adapter."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from data_provider.goldminer_fetcher import GoldMinerFetcher
from data_provider.base import DataFetchError
from data_provider.realtime_types import RealtimeSource
from src.config import Config


class _FakeGoldMinerFetcher(GoldMinerFetcher):
    def __init__(self, responses, **kwargs):
        super().__init__(
            base_url="http://127.0.0.1:7051",
            auth_token="test-token",
            now_fn=lambda: datetime(2026, 8, 31, 7, 10, tzinfo=timezone.utc),
            **kwargs,
        )
        self.responses = responses
        self.calls = []

    def _request_json(self, path, params):
        self.calls.append((path, dict(params)))
        key = (path, params.get("frequency"))
        value = self.responses.get(key, {"data": []})
        return value() if callable(value) else value


def _daily_rows(symbol="SHSE.600519"):
    return [
        {
            "symbol": symbol,
            "frequency": "1d",
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "pre_close": 99.0,
            "volume": 1000,
            "amount": 100000.0,
            "bob": "2026-08-26T16:00:00Z",
            "eob": "2026-08-26T16:00:00Z",
        },
        {
            "symbol": symbol,
            "frequency": "1d",
            "open": 101.0,
            "high": 104.0,
            "low": 100.0,
            "close": 103.0,
            "pre_close": 101.0,
            "volume": 1200,
            "amount": 123000.0,
            "bob": "2026-08-27T16:00:00Z",
            "eob": "2026-08-27T16:00:00Z",
        },
    ]


def _minute_row(symbol="SHSE.600519", *, price=103.5, previous=103.0):
    return {
        "symbol": symbol,
        "frequency": "60s",
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "pre_close": previous,
        "volume": 88,
        "amount": price * 88,
        "bob": "2026-08-31T06:59:00Z",
        "eob": "2026-08-31T07:00:00Z",
    }


def test_symbol_normalization_supports_explicit_exchanges_and_bare_a_shares():
    assert GoldMinerFetcher._to_goldminer_symbol("600519") == "SHSE.600519"
    assert GoldMinerFetcher._to_goldminer_symbol("600519.SH") == "SHSE.600519"
    assert GoldMinerFetcher._to_goldminer_symbol("SHSE.600519") == "SHSE.600519"
    assert GoldMinerFetcher._to_goldminer_symbol("000858") == "SZSE.000858"
    assert GoldMinerFetcher._to_goldminer_symbol("399001.SZ") == "SZSE.399001"
    assert GoldMinerFetcher._to_goldminer_symbol("not-a-symbol") is None


def test_daily_bars_are_normalized_to_project_schema_and_local_session_date():
    fetcher = _FakeGoldMinerFetcher({("/v3/data-history/bars", "1d"): {"data": _daily_rows()}})

    frame = fetcher.get_daily_data(
        "600519",
        start_date="2026-08-20",
        end_date="2026-08-31",
    )

    assert list(frame.columns[:8]) == ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]
    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-08-27", "2026-08-28"]
    assert frame["volume"].tolist() == [1000, 1200]
    assert frame["pct_chg"].round(4).tolist() == [2.0202, 1.9802]
    assert fetcher.calls[0][1]["symbols"] == "SHSE.600519"


def test_realtime_quote_uses_goldminer_source_and_provider_timestamp():
    fetcher = _FakeGoldMinerFetcher(
        {
            ("/v3/data-history/bars-n", "60s"): {"data": [_minute_row()]},
        },
        quote_cache_seconds=0,
    )

    quote = fetcher.get_realtime_quote("600519")

    assert quote is not None
    assert quote.source is RealtimeSource.GOLDMINER
    assert quote.code == "600519"
    assert quote.price == 103.5
    assert round(quote.change_pct, 4) == 0.4854
    assert quote.provider_timestamp == "2026-08-31T07:00:00Z"
    assert quote.volume == 88
    assert quote.amount == 9108.0


def test_realtime_quote_fills_previous_close_from_daily_bars_when_minute_row_omits_it():
    fetcher = _FakeGoldMinerFetcher(
        {
            ("/v3/data-history/bars-n", "60s"): {"data": [_minute_row(previous=None)]},
            ("/v3/data-history/bars", "1d"): {"data": _daily_rows()},
        },
        quote_cache_seconds=0,
    )
    row = _minute_row()
    row.pop("pre_close")
    fetcher.responses[("/v3/data-history/bars-n", "60s")] = {"data": [row]}

    quote = fetcher.get_realtime_quote("600519")

    assert quote is not None
    assert quote.pre_close == 103.0
    assert quote.data_quality == "ok"
    assert len(fetcher.calls) == 2
    assert fetcher.calls[1][1]["frequency"] == "1d"


def test_prefetch_batches_rows_and_followup_quote_uses_cache():
    rows = [
        _minute_row("SHSE.600519", price=103.5),
        {**_minute_row("SZSE.000858", price=71.2), "eob": "2026-08-31T06:58:00Z"},
    ]
    fetcher = _FakeGoldMinerFetcher(
        {
            ("/v3/data-history/bars", "60s"): {"data": rows},
            ("/v3/data-history/bars", "1d"): {"data": []},
        },
        quote_cache_seconds=30,
    )

    assert fetcher.prefetch_realtime_quotes(["600519", "000858"]) == 2
    quote = fetcher.get_realtime_quote("600519")

    assert quote is not None
    assert quote.price == 103.5
    assert [path for path, _params in fetcher.calls].count("/v3/data-history/bars-n") == 0
    assert fetcher.calls[0][1]["symbols"] == "SHSE.600519,SZSE.000858"


def test_main_indices_aggregate_intraday_rows_and_return_project_contract():
    rows = []
    for index, (symbol, _name) in enumerate(
        (
            ("SHSE.000001", "上证指数"),
            ("SZSE.399001", "深证成指"),
        )
    ):
        rows.extend(
            [
                {**_minute_row(symbol, price=100 + index), "open": 99 + index, "high": 101 + index, "low": 98 + index},
                {**_minute_row(symbol, price=101 + index), "open": 100 + index, "high": 102 + index, "low": 99 + index},
            ]
        )
    fetcher = _FakeGoldMinerFetcher(
        {
            ("/v3/data-history/bars", "60s"): {"data": rows},
            ("/v3/data-history/bars", "1d"): {"data": []},
        },
    )

    result = fetcher.get_main_indices("cn")

    assert result is not None
    assert [item["code"] for item in result] == ["000001", "399001"]
    assert result[0]["current"] == 101.0
    assert result[0]["open"] == 99.0
    assert result[0]["high"] == 102.0
    assert result[0]["low"] == 98.0
    assert result[0]["volume"] == 176.0


def test_ssh_script_does_not_embed_or_return_a_bearer_token():
    fetcher = GoldMinerFetcher(
        ssh_host="windows.example",
        ssh_user="Administrator",
        ssh_key="/tmp/key",
    )
    response = MagicMock(returncode=0, stdout=json.dumps({"data": []}), stderr="")
    with patch("data_provider.goldminer_fetcher.subprocess.run", return_value=response) as run:
        payload = fetcher._request_via_ssh("/v3/data-history/bars-n", {"symbol": "SHSE.600519", "count": 1})

    assert payload == {"data": []}
    command = run.call_args.args[0]
    script = run.call_args.kwargs["input"]
    assert "--token=(\\S+)" in script
    assert "Authorization=\"Bearer $token\"" in script
    assert all("test-token" not in str(part) for part in command)


def test_source_is_only_configured_when_explicitly_enabled():
    assert not GoldMinerFetcher.is_configured(SimpleNamespace(goldminer_market_enabled=False))
    assert GoldMinerFetcher.is_configured(
        SimpleNamespace(
            goldminer_market_enabled=True,
            goldminer_market_ssh_host="windows.example",
        )
    )


def test_config_loads_goldminer_transport_and_auto_priority():
    with patch("src.config.setup_env"), patch.object(Config, "_parse_litellm_yaml", return_value=[]):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "GOLDMINER_MARKET_ENABLED": "true",
                "GOLDMINER_MARKET_SSH_HOST": "windows.example",
                "GOLDMINER_MARKET_SSH_KEY": "/tmp/key",
                "GOLDMINER_MARKET_BATCH_SIZE": "17",
            },
            clear=True,
        ):
            config = Config._load_from_env()

    assert config.goldminer_market_enabled is True
    assert config.goldminer_market_ssh_host == "windows.example"
    assert config.goldminer_market_ssh_key == "/tmp/key"
    assert config.goldminer_market_batch_size == 17
    assert config.realtime_source_priority.startswith("goldminer,")


def test_explicit_realtime_priority_remains_authoritative_when_goldminer_enabled():
    with patch.dict(
        os.environ,
        {
            "GOLDMINER_MARKET_ENABLED": "true",
            "REALTIME_SOURCE_PRIORITY": "tencent,akshare_sina",
        },
        clear=True,
    ):
        assert Config._resolve_realtime_source_priority() == "tencent,akshare_sina"


def test_request_failure_is_reported_without_fabricating_a_quote():
    fetcher = _FakeGoldMinerFetcher({})

    def fail(_path, _params):
        raise DataFetchError("gateway_unavailable")

    fetcher._request_json = fail

    with pytest.raises(DataFetchError, match="gateway_unavailable"):
        fetcher.get_realtime_quote("600519")


def test_empty_provider_rows_return_no_quote_instead_of_zero_price():
    fetcher = _FakeGoldMinerFetcher(
        {("/v3/data-history/bars-n", "60s"): {"data": []}},
        quote_cache_seconds=0,
    )

    assert fetcher.get_realtime_quote("920066") is None
