#!/usr/bin/env python3
"""One-shot, rate-safe observations for configured Tushare and Efinance paths.

Each provider is called once in a bounded child process. The command is an
observation tool only; it does not start a scheduler, alter provider order, or
submit anything.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _classify_failure(error: Any) -> str:
    text = str(error or "").lower()
    if "no module named" in text or "not installed" in text:
        return "NOT_INSTALLED"
    if "timeout" in text or "timed out" in text:
        return "TIMEOUT"
    if any(token in text for token in ("401", "403", "token", "auth", "permission")):
        return "AUTH_OR_PERMISSION"
    if any(token in text for token in ("quota", "rate limit", "频率", "限流", "积分")):
        return "QUOTA_OR_RATE_LIMIT"
    if any(token in text for token in ("connection", "connect", "remote", "http", "protocol")):
        return "TRANSPORT"
    if any(token in text for token in ("schema", "field", "column", "json")):
        return "SCHEMA"
    if "empty" in text or "no data" in text or "为空" in text:
        return "EMPTY_RESULT"
    return "UNKNOWN"


def _tushare_worker(conn: Any) -> None:
    try:
        from data_provider.tushare_fetcher import TushareFetcher

        fetcher = TushareFetcher(rate_limit_per_minute=80)
        if fetcher._api is None:
            conn.send({
                "configured": bool(os.getenv("TUSHARE_TOKEN", "").strip()),
                "reachable": False,
                "usable": False,
                "records": 0,
                "failure_class": "NOT_INITIALIZED",
            })
            return
        end_date = datetime.now(timezone.utc).strftime("%Y%m%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y%m%d")
        started = time.monotonic()
        frame = fetcher._call_api_with_rate_limit(
            "trade_cal",
            exchange="SSE",
            start_date=start_date,
            end_date=end_date,
        )
        required = {"cal_date", "is_open"}
        valid = frame is not None and required.issubset(set(frame.columns))
        records = int(len(frame)) if frame is not None else 0
        conn.send({
            "configured": True,
            "reachable": True,
            "usable": bool(valid and records > 0),
            "records": records,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "failure_class": None if valid and records > 0 else ("EMPTY_RESULT" if records == 0 else "SCHEMA"),
            "schema": sorted(str(item) for item in (frame.columns if frame is not None else ())),
        })
    except Exception as exc:  # noqa: BLE001 - preserve provider evidence
        conn.send({
            "configured": bool(os.getenv("TUSHARE_TOKEN", "").strip()),
            "reachable": False,
            "usable": False,
            "records": 0,
            "failure_class": _classify_failure(exc),
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
        })
    finally:
        conn.close()


def _efinance_worker(conn: Any) -> None:
    try:
        from data_provider.efinance_fetcher import EfinanceFetcher

        started = time.monotonic()
        fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)
        frame = fetcher.get_daily_data("600519", days=5)
        required = {"date", "close"}
        valid = frame is not None and required.issubset(set(frame.columns))
        records = int(len(frame)) if frame is not None else 0
        conn.send({
            "configured": True,
            "reachable": True,
            "usable": bool(valid and records > 0),
            "records": records,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "failure_class": None if valid and records > 0 else ("EMPTY_RESULT" if records == 0 else "SCHEMA"),
            "schema": sorted(str(item) for item in (frame.columns if frame is not None else ())),
        })
    except ImportError as exc:
        conn.send({
            "configured": True,
            "reachable": False,
            "usable": False,
            "records": 0,
            "failure_class": "NOT_INSTALLED",
            "error": type(exc).__name__,
        })
    except Exception as exc:  # noqa: BLE001 - preserve provider evidence
        conn.send({
            "configured": True,
            "reachable": False,
            "usable": False,
            "records": 0,
            "failure_class": _classify_failure(exc),
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
        })
    finally:
        conn.close()


def _bounded_call(worker: Any, timeout_seconds: float) -> Dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(child,), daemon=True)
    process.start()
    child.close()
    try:
        if not parent.poll(max(0.1, timeout_seconds)):
            if process.is_alive():
                process.terminate()
                process.join(1)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(1)
            return {"configured": True, "reachable": False, "usable": False, "records": 0, "failure_class": "TIMEOUT"}
        return parent.recv()
    finally:
        parent.close()
        process.join(1)


def run(*, timeout_seconds: float) -> Dict[str, Any]:
    observations = {
        "tushare": _bounded_call(_tushare_worker, timeout_seconds),
        "efinance": _bounded_call(_efinance_worker, timeout_seconds),
    }
    try:
        from src.services.dependency_health import get_dependency_health_store

        store = get_dependency_health_store()
        for dependency_id, item in observations.items():
            store.record_result(
                dependency_id,
                category="MARKET_DATA",
                role="PRIMARY" if dependency_id == "tushare" else "FALLBACK",
                priority=1 if dependency_id == "tushare" else 2,
                endpoint="https://api.tushare.pro" if dependency_id == "tushare" else "https://push2his.eastmoney.com",
                configured=bool(item.get("configured")),
                enabled=bool(item.get("configured")),
                success=bool(item.get("reachable")),
                reachable=bool(item.get("reachable")),
                usable=bool(item.get("usable")),
                records=int(item.get("records") or 0),
                latency_ms=item.get("latency_ms"),
                failure_class_name=item.get("failure_class"),
                error=item.get("error"),
                metadata={"schema": item.get("schema")},
            )
    except Exception:
        pass
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "providers": observations,
        "scope": "one trade-calendar request for Tushare; one 600519 daily-history request for Efinance",
        "simulation_only": True,
        "execution_authority": "ATHENA_ONLY",
        "proof_order": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=float, default=65.0)
    args = parser.parse_args()
    import json

    print(json.dumps(run(timeout_seconds=args.timeout_seconds), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
