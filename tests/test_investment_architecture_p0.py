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


def test_p1_transport_stays_outside_research_and_decision_internals() -> None:
    protected = _python_files("src/investment/research") + _python_files(
        "src/investment/decision"
    )
    imports = _imported_modules(protected)
    assert not any(
        module.startswith("src.investment.integration")
        or module.startswith("src.trading_spine")
        or module.startswith("athena")
        for module in imports
    )


def test_m2_runtime_path_has_no_execution_or_broker_dependency() -> None:
    paths = (
        ROOT / "src/investment/m2/orchestration.py",
        ROOT / "src/investment/integration/runtime_snapshot_ingress.py",
        ROOT / "src/services/single_brain_m2_readiness_service.py",
        ROOT / "api/v1/endpoints/single_brain_m2.py",
    )
    imports = _imported_modules(paths)
    forbidden_imports = (
        "src.investment.canary",
        "src.investment.execution_projection",
        "src.investment.contracts.execution_mandate",
        "src.investment.contracts.execution_result",
        "src.brokers",
        "src.trading_spine",
        "athena",
        "gmtrade",
    )
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imports
        for prefix in forbidden_imports
    )

    called = set()
    referenced = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)
            if isinstance(node, ast.Name):
                referenced.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced.add(node.attr)
    forbidden_calls = {
        "execute",
        "submit",
        "submit_order",
        "dispatch",
        "enqueue",
        "retry",
        "reconcile",
        "cancel",
        "cancel_order",
        "order_volume",
        "project",
    }
    assert called.isdisjoint(forbidden_calls)
    assert {"ExecutionMandate", "ExecutionResult"}.isdisjoint(referenced)


def test_m3_keeps_athena_and_broker_dependencies_outside_dsa_brain() -> None:
    protected = _python_files("src/investment/research") + _python_files(
        "src/investment/decision"
    )
    protected_imports = _imported_modules(protected)
    assert not any(
        "m3" in module
        or "execution_transport" in module
        or "athena" in module.lower()
        or "broker" in module.lower()
        for module in protected_imports
    )

    m3_paths = _python_files("src/investment/m3")
    m3_imports = _imported_modules(m3_paths)
    assert not any(
        module.startswith("athena")
        or module.startswith("gmtrade")
        or module.startswith("src.brokers")
        for module in m3_imports
    )

    transport_source = (
        ROOT / "src/investment/integration/execution_transport.py"
    ).read_text(encoding="utf-8")
    assert "for attempt" not in transport_source
    assert "while " not in transport_source
