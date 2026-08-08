"""Deterministic projections from the sole InvestmentDecision."""

from .decision_signal import DecisionSignalProjector
from .mandate import ExecutionMandateProjector

__all__ = ["DecisionSignalProjector", "ExecutionMandateProjector"]
