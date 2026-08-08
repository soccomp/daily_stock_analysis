"""Dependency guards that keep the P0 path inside the Single Brain boundary."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from src.investment.contracts.research_bundle import ResearchBundle
from src.investment.execution_projection import ExecutionMandateProjector


ROOT = Path(__file__).resolve().parents[1]


def _python_files(relative_directory: str) -> tuple[Path, ...]:
    return tuple(sorted((ROOT / relative_directory).rglob("*.py")))


def _imported_modules(paths: tuple[Path, ...]) -> set[str]:
    modules: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
    return modules


def _attribute_names(paths: tuple[Path, ...]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
    return names


def test_research_layer_has_no_broker_or_execution_dependency() -> None:
    paths = _python_files("src/investment/research")
    imports = _imported_modules(paths)
    names = _attribute_names(paths)
    forbidden_import_parts = {"broker", "gmtrade", "simulation_execution", "execution_projection"}
    assert not any(
        part in module.lower()
        for module in imports
        for part in forbidden_import_parts
    )
    assert "submit_order" not in names


def test_decision_layer_has_no_broker_submission_dependency() -> None:
    paths = _python_files("src/investment/decision")
    imports = _imported_modules(paths)
    names = _attribute_names(paths)
    forbidden_import_parts = {"broker", "gmtrade", "windows", "simulation_execution"}
    assert not any(
        part in module.lower()
        for module in imports
        for part in forbidden_import_parts
    )
    assert {"submit_order", "execute_order"}.isdisjoint(names)


def test_execution_projection_has_no_research_or_llm_decision_dependency() -> None:
    paths = _python_files("src/investment/execution_projection")
    imports = _imported_modules(paths)
    forbidden_import_parts = {
        "llm",
        "screening",
        "news",
        "decision_agent",
        "research_agent",
        "portfolio_manager",
    }
    assert not any(
        part in module.lower()
        for module in imports
        for part in forbidden_import_parts
    )


def test_research_contract_cannot_carry_final_allocation() -> None:
    forbidden_fields = {"target_quantity", "delta_quantity", "quantity", "target_weight", "action"}
    assert forbidden_fields.isdisjoint(ResearchBundle.model_fields)


def test_mandate_projector_has_no_quantity_override_parameter() -> None:
    parameters = inspect.signature(ExecutionMandateProjector.project).parameters
    assert tuple(parameters) == ("decision",)
