# -*- coding: utf-8 -*-
"""Read-only market-data adapter for the Windows GoldMiner client.

GoldMiner exposes authenticated historical bars through its local HTTP
gateway.  Pallas normally runs on a different host, so this adapter supports
two transport modes:

* direct HTTP, when the gateway and bearer token are available on the local
  machine;
* an SSH one-shot PowerShell request, which discovers the current GoldMiner
  session token on Windows and never sends that token back to Pallas.

Only market-data endpoints are used.  No trading, account, or order API is
called here.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from threading import RLock
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urlencode

import pandas as pd
import requests

from .base import (
    BaseFetcher,
    DataFetchError,
    DataSourceUnavailableError,
    STANDARD_COLUMNS,
    is_bse_code,
    normalize_stock_code,
)
from .realtime_types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int

logger = logging.getLogger(__name__)

_DEFAULT_REMOTE_BASE_URL = "http://127.0.0.1:7051"
_DEFAULT_TIMEOUT_SECONDS = 8.0
_DEFAULT_SSH_CONNECT_TIMEOUT_SECONDS = 5
_DEFAULT_PRIORITY = 0
_DEFAULT_QUOTE_CACHE_SECONDS = 2.0
_DAILY_LOOKBACK_DAYS = 45
_DEFAULT_BATCH_SIZE = 50

_CN_MAIN_INDEXES: tuple[tuple[str, str], ...] = (
    ("SHSE.000001", "上证指数"),
    ("SZSE.399001", "深证成指"),
    ("SZSE.399006", "创业板指"),
    ("SHSE.000905", "中证500"),
    ("SHSE.000688", "科创50"),
    ("SHSE.000016", "上证50"),
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = _text(value).lower()
    if not normalized:
        return default
    return normalized not in {"0", "false", "no", "off"}


def _parse_int(value: Any, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _parse_float(value: Any, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        return default


def _empty_daily_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=STANDARD_COLUMNS)


def _local_session_date(value: Any) -> Optional[date]:
    """Convert a GoldMiner UTC bar timestamp to the Shanghai session date."""

    if value in (None, ""):
        return None
    try:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        return timestamp.tz_convert("Asia/Shanghai").date()
    except (TypeError, ValueError, OverflowError):
        return None


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _display_code(symbol: str) -> str:
    return symbol.rsplit(".", 1)[-1] if "." in symbol else symbol


class GoldMinerFetcher(BaseFetcher):
    """GoldMiner historical-bars adapter with read-only failover semantics."""

    name = "GoldMinerFetcher"
    priority = _DEFAULT_PRIORITY
    allow_empty_daily_data = True

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        ssh_host: Optional[str] = None,
        ssh_user: Optional[str] = None,
        ssh_key: Optional[str] = None,
        ssh_port: Optional[int] = None,
        remote_base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        priority: Optional[int] = None,
        quote_cache_seconds: Optional[float] = None,
        batch_size: Optional[int] = None,
        ssh_command: Optional[str] = None,
        remote_shell: Optional[str] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.base_url = _text(base_url or os.getenv("GOLDMINER_MARKET_BASE_URL")).rstrip("/")
        self.auth_token = _text(auth_token or os.getenv("GOLDMINER_MARKET_AUTH_TOKEN"))
        self.ssh_host = _text(ssh_host or os.getenv("GOLDMINER_MARKET_SSH_HOST"))
        self.ssh_user = _text(ssh_user or os.getenv("GOLDMINER_MARKET_SSH_USER") or "Administrator")
        self.ssh_key = _text(ssh_key or os.getenv("GOLDMINER_MARKET_SSH_KEY"))
        self.ssh_port = _parse_int(
            ssh_port if ssh_port is not None else os.getenv("GOLDMINER_MARKET_SSH_PORT"),
            22,
            minimum=1,
        )
        self.remote_base_url = (
            _text(remote_base_url or os.getenv("GOLDMINER_MARKET_REMOTE_BASE_URL"))
            or _DEFAULT_REMOTE_BASE_URL
        ).rstrip("/")
        self.timeout_seconds = _parse_float(
            timeout_seconds if timeout_seconds is not None else os.getenv("GOLDMINER_MARKET_TIMEOUT_SECONDS"),
            _DEFAULT_TIMEOUT_SECONDS,
            minimum=0.1,
        )
        self.priority = _parse_int(
            priority if priority is not None else os.getenv("GOLDMINER_MARKET_PRIORITY"),
            _DEFAULT_PRIORITY,
            minimum=0,
        )
        self.quote_cache_seconds = _parse_float(
            quote_cache_seconds
            if quote_cache_seconds is not None
            else os.getenv("GOLDMINER_MARKET_QUOTE_CACHE_SECONDS"),
            _DEFAULT_QUOTE_CACHE_SECONDS,
            minimum=0.0,
        )
        self.batch_size = _parse_int(
            batch_size if batch_size is not None else os.getenv("GOLDMINER_MARKET_BATCH_SIZE"),
            _DEFAULT_BATCH_SIZE,
            minimum=1,
        )
        self.ssh_command = _text(ssh_command or os.getenv("GOLDMINER_MARKET_SSH_COMMAND") or "ssh")
        self.remote_shell = _text(remote_shell or os.getenv("GOLDMINER_MARKET_REMOTE_SHELL") or "powershell")
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._quote_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._quote_cache_lock = RLock()
        self._previous_close_cache: Dict[str, tuple[float, Optional[float]]] = {}
        self._previous_close_cache_lock = RLock()

    @classmethod
    def is_configured(cls, config: Any = None) -> bool:
        """Return whether the source was explicitly enabled and has a transport."""

        if config is None:
            enabled = os.getenv("GOLDMINER_MARKET_ENABLED")
            base_url = _text(os.getenv("GOLDMINER_MARKET_BASE_URL"))
            auth_token = _text(os.getenv("GOLDMINER_MARKET_AUTH_TOKEN"))
            ssh_host = _text(os.getenv("GOLDMINER_MARKET_SSH_HOST"))
        else:
            # A supplied Config is authoritative.  In particular, test or
            # embedded Config objects must not accidentally inherit a process
            # .env transport just because an optional field is absent.
            enabled = getattr(config, "goldminer_market_enabled", False)
            base_url = _text(getattr(config, "goldminer_market_base_url", None))
            auth_token = _text(getattr(config, "goldminer_market_auth_token", None))
            ssh_host = _text(getattr(config, "goldminer_market_ssh_host", None))
        if not _parse_bool(enabled, False):
            return False

        return bool((base_url and auth_token) or (ssh_host and shutil.which("ssh")))

    @classmethod
    def from_config(cls, config: Any) -> "GoldMinerFetcher":
        return cls(
            base_url=getattr(config, "goldminer_market_base_url", None),
            auth_token=getattr(config, "goldminer_market_auth_token", None),
            ssh_host=getattr(config, "goldminer_market_ssh_host", None),
            ssh_user=getattr(config, "goldminer_market_ssh_user", None),
            ssh_key=getattr(config, "goldminer_market_ssh_key", None),
            ssh_port=getattr(config, "goldminer_market_ssh_port", None),
            remote_base_url=getattr(config, "goldminer_market_remote_base_url", None),
            timeout_seconds=getattr(config, "goldminer_market_timeout_seconds", None),
            priority=getattr(config, "goldminer_market_priority", None),
            quote_cache_seconds=getattr(config, "goldminer_market_quote_cache_seconds", None),
            batch_size=getattr(config, "goldminer_market_batch_size", None),
        )

    def is_available(self) -> bool:
        return bool((self.base_url and self.auth_token) or self.ssh_host)

    def is_available_for_request(self, capability: str = "") -> bool:
        return self.is_available()

    @staticmethod
    def _to_goldminer_symbol(stock_code: str) -> Optional[str]:
        """Normalize project symbols to GoldMiner ``SHSE/SZSE/BSE.code``."""

        raw = _text(stock_code).upper()
        if not raw:
            return None

        explicit_exchange: Optional[str] = None
        code = raw
        if "." in raw:
            left, right = raw.rsplit(".", 1)
            exchange_map = {
                "SH": "SHSE",
                "SS": "SHSE",
                "SHSE": "SHSE",
                "SZ": "SZSE",
                "SZSE": "SZSE",
                "BJ": "BSE",
                "BSE": "BSE",
                "BJSE": "BSE",
            }
            if left in exchange_map and right.isdigit():
                explicit_exchange = exchange_map[left]
                code = right
            elif right in exchange_map and left.isdigit():
                explicit_exchange = exchange_map[right]
                code = left
        else:
            code = normalize_stock_code(raw)

        if not (code.isdigit() and len(code) == 6):
            return None
        if explicit_exchange is None:
            if is_bse_code(code):
                explicit_exchange = "BSE"
            elif code.startswith(("6", "5", "9")):
                explicit_exchange = "SHSE"
            else:
                explicit_exchange = "SZSE"
        return f"{explicit_exchange}.{code}"

    def _build_url(self, path: str, params: Mapping[str, Any], *, remote: bool = False) -> str:
        base = self.remote_base_url if remote else self.base_url
        if not base:
            base = _DEFAULT_REMOTE_BASE_URL if remote else ""
        query = urlencode([(key, value) for key, value in params.items() if value not in (None, "")])
        return f"{base.rstrip('/')}/{path.lstrip('/')}" + (f"?{query}" if query else "")

    @staticmethod
    def _headers(token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Grpc-Metadata-mfp-modid": "termui",
            "Grpc-Metadata-X-ORGCODE": "myquant",
            "Grpc-Metadata-X-CODE": "666,999",
            "Accept": "application/json",
        }

    def _request_direct(self, path: str, params: Mapping[str, Any]) -> Dict[str, Any]:
        if not self.base_url or not self.auth_token:
            raise DataSourceUnavailableError("GoldMiner direct HTTP transport is not configured")
        response = requests.get(
            self._build_url(path, params),
            headers=self._headers(self.auth_token),
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DataFetchError(f"GoldMiner HTTP request failed: status={response.status_code}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataFetchError("GoldMiner HTTP response was not valid JSON") from exc
        return self._validate_payload(payload)

    def _build_remote_script(self, url: str) -> str:
        # URL is generated from fixed endpoint names and urlencode; still escape
        # PowerShell single quotes so future parameters cannot break the script.
        safe_url = url.replace("'", "''")
        timeout = max(1, int(round(self.timeout_seconds)))
        return (
            "$p=Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -in @(\"gmterm-serv.exe\",\"ds-proxy.exe\") } | "
            "Select-Object -First 1 -ExpandProperty CommandLine\n"
            "if (-not $p -or $p -notmatch \"--token=(\\S+)\") { "
            "[Console]::Error.WriteLine('GoldMiner session token unavailable'); exit 11 }\n"
            "$token=$matches[1]\n"
            "$headers=@{ Authorization=\"Bearer $token\"; "
            "\"Grpc-Metadata-mfp-modid\"=\"termui\"; "
            "\"Grpc-Metadata-X-ORGCODE\"=\"myquant\"; "
            "\"Grpc-Metadata-X-CODE\"=\"666,999\" }\n"
            f"try {{ $response=Invoke-WebRequest -UseBasicParsing -Uri '{safe_url}' "
            f"-Headers $headers -TimeoutSec {timeout}; "
            "if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) { exit 12 }; "
            "[Console]::Out.Write($response.Content) } catch { "
            "[Console]::Error.WriteLine('GoldMiner request failed'); exit 12 }\n"
        )

    def _request_via_ssh(self, path: str, params: Mapping[str, Any]) -> Dict[str, Any]:
        if not self.ssh_host:
            raise DataSourceUnavailableError("GoldMiner SSH transport is not configured")
        destination = f"{self.ssh_user}@{self.ssh_host}"
        command: List[str] = [
            self.ssh_command,
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={_DEFAULT_SSH_CONNECT_TIMEOUT_SECONDS}",
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]
        if self.ssh_key:
            command.extend(["-i", self.ssh_key])
        if self.ssh_port:
            command.extend(["-p", str(self.ssh_port)])
        command.extend([destination, self.remote_shell, "-NoProfile", "-NonInteractive", "-Command", "-"])
        script = self._build_remote_script(self._build_url(path, params, remote=True))
        try:
            completed = subprocess.run(
                command,
                input=script,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds + _DEFAULT_SSH_CONNECT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DataFetchError("GoldMiner SSH request failed before a response") from exc
        if completed.returncode != 0:
            # Do not include remote stderr: PowerShell/SSH diagnostics may
            # contain process command lines or other sensitive details.
            raise DataFetchError(f"GoldMiner SSH request failed: exit={completed.returncode}")
        try:
            payload = json.loads((completed.stdout or "").lstrip("\ufeff"))
        except (TypeError, json.JSONDecodeError) as exc:
            raise DataFetchError("GoldMiner SSH response was not valid JSON") from exc
        return self._validate_payload(payload)

    @staticmethod
    def _validate_payload(payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise DataFetchError("GoldMiner response must be a JSON object")
        if payload.get("error"):
            error_code = _text(payload.get("code")) or "provider_error"
            raise DataFetchError(f"GoldMiner provider error: {error_code}")
        return payload

    def _request_json(self, path: str, params: Mapping[str, Any]) -> Dict[str, Any]:
        if self.ssh_host:
            return self._request_via_ssh(path, params)
        return self._request_direct(path, params)

    def _rows(self, path: str, params: Mapping[str, Any], *, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        payload = self._request_json(path, params)
        raw_rows = payload.get("data")
        if isinstance(raw_rows, dict):
            flattened: List[Any] = []
            for value in raw_rows.values():
                flattened.extend(value if isinstance(value, list) else [value])
            raw_rows = flattened
        if not isinstance(raw_rows, list):
            return []
        rows = [row for row in raw_rows if isinstance(row, dict)]
        if symbol:
            rows = [row for row in rows if _text(row.get("symbol")).upper() == symbol.upper()]
        return rows

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = self._to_goldminer_symbol(stock_code)
        if not symbol:
            raise DataFetchError(f"GoldMinerFetcher unsupported stock code: {stock_code}")
        rows = self._rows(
            "/v3/data-history/bars",
            {
                "symbols": symbol,
                "frequency": "1d",
                "startTime": start_date,
                "endTime": end_date,
                "adjust": "0",
            },
            symbol=symbol,
        )
        return pd.DataFrame(rows) if rows else _empty_daily_frame()

    @staticmethod
    def _date_series(raw: pd.DataFrame) -> pd.Series:
        source = raw["eob"] if "eob" in raw.columns else raw.get("date")
        if source is None:
            source = raw.get("bob")
        if source is None:
            return pd.Series(pd.NaT, index=raw.index)
        return pd.to_datetime(source, errors="coerce", utc=True).dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        if df is None or df.empty:
            return _empty_daily_frame()
        raw = df.copy()
        normalized = pd.DataFrame(index=raw.index)
        normalized["date"] = self._date_series(raw)
        for column in ("open", "high", "low", "close", "volume", "amount"):
            normalized[column] = pd.to_numeric(
                raw[column] if column in raw.columns else pd.Series(index=raw.index),
                errors="coerce",
            )
        normalized["_pre_close"] = pd.to_numeric(
            raw["pre_close"] if "pre_close" in raw.columns else pd.Series(index=raw.index),
            errors="coerce",
        )
        normalized = normalized.dropna(subset=["date", "close", "volume"])
        if normalized.empty:
            return _empty_daily_frame()
        normalized = normalized.sort_values("date").reset_index(drop=True)
        close = normalized["close"]
        pre_close = normalized.pop("_pre_close")
        pct = (close - pre_close) / pre_close.replace(0, pd.NA) * 100.0
        normalized["pct_chg"] = pct.fillna(close.pct_change() * 100.0).fillna(0.0)
        return normalized[STANDARD_COLUMNS]

    def _today_utc_window(self) -> tuple[datetime, datetime, date]:
        now = self._now_fn()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        local_date = (pd.Timestamp(now).tz_convert("Asia/Shanghai")).date()
        start = datetime(local_date.year, local_date.month, local_date.day, tzinfo=timezone.utc)
        return start, now, local_date

    def _cache_get_row(self, symbol: str) -> Optional[Dict[str, Any]]:
        if self.quote_cache_seconds <= 0:
            return None
        with self._quote_cache_lock:
            cached = self._quote_cache.get(symbol)
            if cached is None or time.monotonic() - cached[0] > self.quote_cache_seconds:
                if cached is not None:
                    self._quote_cache.pop(symbol, None)
                return None
            return dict(cached[1])

    def _cache_rows(self, rows: Iterable[Mapping[str, Any]]) -> int:
        stored = 0
        now = time.monotonic()
        with self._quote_cache_lock:
            for row in rows:
                symbol = _text(row.get("symbol")).upper()
                if not symbol:
                    continue
                self._quote_cache[symbol] = (now, dict(row))
                stored += 1
        return stored

    def _previous_closes(self, symbols: Sequence[str], session_date: date) -> Dict[str, Optional[float]]:
        result: Dict[str, Optional[float]] = {}
        missing: List[str] = []
        cache_key_suffix = session_date.isoformat()
        now = time.monotonic()
        with self._previous_close_cache_lock:
            for symbol in symbols:
                key = f"{symbol}|{cache_key_suffix}"
                cached = self._previous_close_cache.get(key)
                if cached is not None and now - cached[0] <= 60.0:
                    result[symbol] = cached[1]
                else:
                    missing.append(symbol)
        if missing:
            start_date = (session_date - timedelta(days=_DAILY_LOOKBACK_DAYS)).isoformat()
            rows = self._rows(
                "/v3/data-history/bars",
                {
                    "symbols": ",".join(missing),
                    "frequency": "1d",
                    "startTime": start_date,
                    "endTime": session_date.isoformat(),
                    "adjust": "0",
                },
            )
            by_symbol: Dict[str, List[Dict[str, Any]]] = {}
            for row in rows:
                symbol = _text(row.get("symbol")).upper()
                if symbol in missing:
                    by_symbol.setdefault(symbol, []).append(row)
            with self._previous_close_cache_lock:
                for symbol in missing:
                    candidates = sorted(
                        by_symbol.get(symbol, []),
                        key=lambda row: _text(row.get("eob") or row.get("bob")),
                    )
                    previous: Optional[float] = None
                    for row in candidates:
                        row_date = _local_session_date(row.get("eob") or row.get("bob"))
                        if row_date is None or row_date > session_date:
                            continue
                        if row_date == session_date:
                            previous = safe_float(row.get("pre_close"))
                            if previous is not None:
                                break
                        else:
                            previous = safe_float(row.get("close"))
                    key = f"{symbol}|{cache_key_suffix}"
                    self._previous_close_cache[key] = (now, previous)
                    result[symbol] = previous
        return result

    def _row_to_quote(
        self,
        stock_code: str,
        row: Mapping[str, Any],
        *,
        previous_close: Optional[float] = None,
    ) -> Optional[UnifiedRealtimeQuote]:
        symbol = _text(row.get("symbol")) or self._to_goldminer_symbol(stock_code) or ""
        current = safe_float(row.get("close"))
        if current is None or current <= 0:
            return None
        provider_timestamp = _text(row.get("eob") or row.get("bob")) or None
        previous = safe_float(row.get("pre_close")) or previous_close
        change_amount = safe_float(row.get("change_amount"))
        change_pct = safe_float(row.get("change_pct"))
        if previous and previous > 0:
            if change_amount is None:
                change_amount = current - previous
            if change_pct is None:
                change_pct = (current - previous) / previous * 100.0
        missing_fields = []
        if previous is None:
            missing_fields.append("pre_close")
        return UnifiedRealtimeQuote(
            code=_display_code(symbol),
            name=_text(row.get("name")),
            source=RealtimeSource.GOLDMINER,
            provider_timestamp=provider_timestamp,
            market="cn",
            currency="CNY",
            data_quality="ok" if previous is not None else "partial",
            missing_fields=missing_fields or None,
            price=current,
            change_pct=change_pct,
            change_amount=change_amount,
            volume=safe_int(row.get("volume"), default=0),
            amount=safe_float(row.get("amount"), default=0.0),
            open_price=safe_float(row.get("open")),
            high=safe_float(row.get("high")),
            low=safe_float(row.get("low")),
            pre_close=previous,
        )

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        symbol = self._to_goldminer_symbol(stock_code)
        if not symbol:
            return None
        row = self._cache_get_row(symbol)
        if row is None:
            _start, end, _session_date = self._today_utc_window()
            rows = self._rows(
                "/v3/data-history/bars-n",
                {
                    "symbol": symbol,
                    "frequency": "60s",
                    "endTime": _format_utc(end),
                    "count": 1,
                    "adjust": "0",
                },
                symbol=symbol,
            )
            if not rows:
                return None
            row = rows[-1]
            self._cache_rows([row])
        session_date = _local_session_date(row.get("eob") or row.get("bob"))
        previous = None
        if session_date is not None and safe_float(row.get("pre_close")) is None:
            previous = self._previous_closes([symbol], session_date).get(symbol)
        return self._row_to_quote(stock_code, row, previous_close=previous)

    def prefetch_realtime_quotes(self, stock_codes: Iterable[str], *, batch_size: Optional[int] = None) -> int:
        symbols = []
        seen = set()
        for stock_code in stock_codes:
            symbol = self._to_goldminer_symbol(stock_code)
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)
        if not symbols:
            return 0
        start, end, session_date = self._today_utc_window()
        effective_batch_size = max(1, int(batch_size or self.batch_size))
        cached = 0
        for offset in range(0, len(symbols), effective_batch_size):
            batch = symbols[offset : offset + effective_batch_size]
            rows = self._rows(
                "/v3/data-history/bars",
                {
                    "symbols": ",".join(batch),
                    "frequency": "60s",
                    "startTime": _format_utc(start),
                    "endTime": _format_utc(end),
                    "adjust": "0",
                },
            )
            latest: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                symbol = _text(row.get("symbol")).upper()
                if symbol in batch:
                    previous = latest.get(symbol)
                    if previous is None or _text(row.get("eob")) > _text(previous.get("eob")):
                        latest[symbol] = row
            cached += self._cache_rows(latest.values())
        if symbols:
            self._previous_closes(symbols, session_date)
        return cached

    def get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        if region != "cn":
            return None
        start, end, session_date = self._today_utc_window()
        symbols = [symbol for symbol, _name in _CN_MAIN_INDEXES]
        rows = self._rows(
            "/v3/data-history/bars",
            {
                "symbols": ",".join(symbols),
                "frequency": "60s",
                "startTime": _format_utc(start),
                "endTime": _format_utc(end),
                "adjust": "0",
            },
        )
        if not rows:
            return None
        previous_closes = self._previous_closes(symbols, session_date)
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            symbol = _text(row.get("symbol")).upper()
            if symbol in symbols:
                grouped.setdefault(symbol, []).append(row)
        result: List[Dict[str, Any]] = []
        names = dict(_CN_MAIN_INDEXES)
        for symbol in symbols:
            symbol_rows = sorted(grouped.get(symbol, []), key=lambda row: _text(row.get("eob")))
            if not symbol_rows:
                continue
            latest = symbol_rows[-1]
            current = safe_float(latest.get("close"))
            if current is None:
                continue
            previous = safe_float(latest.get("pre_close")) or previous_closes.get(symbol)
            high_values = [safe_float(row.get("high")) for row in symbol_rows]
            low_values = [safe_float(row.get("low")) for row in symbol_rows]
            high_values = [value for value in high_values if value is not None]
            low_values = [value for value in low_values if value is not None]
            open_price = safe_float(symbol_rows[0].get("open")) or current
            high = max(high_values) if high_values else current
            low = min(low_values) if low_values else current
            change = current - previous if previous is not None else 0.0
            change_pct = change / previous * 100.0 if previous and previous > 0 else 0.0
            result.append(
                {
                    "code": _display_code(symbol),
                    "name": names[symbol],
                    "current": current,
                    "change": change,
                    "change_pct": change_pct,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "prev_close": previous or 0.0,
                    "volume": sum(safe_float(row.get("volume"), default=0.0) or 0.0 for row in symbol_rows),
                    "amount": sum(safe_float(row.get("amount"), default=0.0) or 0.0 for row in symbol_rows),
                    "amplitude": (high - low) / previous * 100.0 if previous and previous > 0 else 0.0,
                }
            )
        return result or None

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        # Historical bars do not reliably carry instrument names.  Let the
        # manager's static index and other providers resolve names instead.
        return None
