#!/usr/bin/env python3
"""Explicit one-shot P1 simulation canary for development worktrees only."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.config import get_config
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType
from src.investment.contracts.risk_policy import RiskPolicy
from src.investment.integration import LocalAthenaCanaryTransport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one explicit DSA -> Athena local simulation canary.",
    )
    parser.add_argument("--confirm-simulation-only", action="store_true")
    parser.add_argument("--athena-repo", type=Path, required=True)
    parser.add_argument("--journal-path", type=Path, required=True)
    parser.add_argument("--policy-json", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--cash", type=Decimal, required=True)
    parser.add_argument("--position-quantity", type=int, default=0)
    parser.add_argument("--avg-cost", type=Decimal, default=Decimal("0"))
    parser.add_argument("--last-price", type=Decimal, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.confirm_simulation_only is not True:
        raise SystemExit("--confirm-simulation-only is required")

    config = get_config()
    if config.investment_canary_enabled is not True:
        raise SystemExit("DSA_INVESTMENT_CANARY_ENABLED must be exactly true")
    if config.investment_canary_account_id != args.account_id:
        raise SystemExit("configured canary account does not match --account-id")
    if args.symbol not in config.investment_canary_symbols:
        raise SystemExit("symbol is not in DSA_INVESTMENT_CANARY_SYMBOLS")

    policy = RiskPolicy.model_validate_json(
        args.policy_json.read_text(encoding="utf-8")
    )
    if not policy.applies_to(args.account_id):
        raise SystemExit("RiskPolicy does not apply to the canary account")

    now = datetime.now(timezone.utc)
    with LocalAthenaCanaryTransport.for_athena_worktree(
        athena_root=args.athena_repo,
        journal_path=args.journal_path,
        account_id=args.account_id,
        symbol=args.symbol,
        allowed_symbols=tuple(config.investment_canary_symbols),
        cash=args.cash,
        position_quantity=args.position_quantity,
        avg_cost=args.avg_cost,
        last_price=args.last_price,
        now=now,
    ) as transport:
        pipeline = StockAnalysisPipeline(
            config=config,
            trace_id=f"p1-canary-{now.strftime('%Y%m%dT%H%M%SZ')}",
            query_source="p1_simulation_canary",
            investment_shadow_risk_policy=policy,
            investment_shadow_clock=lambda: now,
            investment_canary_transport=transport,
        )
        result = pipeline.analyze_stock(
            args.symbol,
            ReportType.SIMPLE,
            f"p1-canary-{now.strftime('%Y%m%dT%H%M%SZ')}",
            current_time=now,
        )

    artifacts = getattr(result, "_investment_canary_artifacts", None)
    if artifacts is None:
        raise SystemExit("P1 simulation canary failed closed without artifacts")
    execution = artifacts.execution_result
    snapshot_b = artifacts.portfolio_snapshot_b
    output = {
        "decision_id": artifacts.investment_decision.decision_id,
        "action": artifacts.investment_decision.action,
        "delta_quantity": artifacts.investment_decision.delta_quantity,
        "mandate_id": (
            None
            if artifacts.execution_mandate is None
            else artifacts.execution_mandate.mandate_id
        ),
        "execution_status": None if execution is None else execution.status,
        "submitted_quantity": (
            None if execution is None else execution.submitted_quantity
        ),
        "filled_quantity": None if execution is None else execution.filled_quantity,
        "snapshot_b_id": None if snapshot_b is None else snapshot_b.snapshot_id,
        "simulation_only": True,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
