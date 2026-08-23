# -*- coding: utf-8 -*-
"""Backend-neutral Agent Chat orchestration and conversation persistence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from src.agent.agent_backend import AgentBackend, AgentRunRequest
from src.agent.conversation import conversation_manager
from src.agent.executor import (
    AGENT_DASHBOARD_OUTPUT_SCHEMA,
    AgentResult,
    PreparedAgentChat,
    parse_dashboard_json,
    prepare_agent_chat,
)
from src.agent.provider_trace import persist_provider_trace_turns


_CODEX_DASHBOARD_TOOL_NAMES = [
    "get_analysis_context",
    "get_skill_backtest_summary",
    "get_strategy_backtest_summary",
]


@dataclass(frozen=True)
class PreparedAgentChatTurn:
    """A persisted user turn that is ready for backend execution."""

    message: str
    session_id: str
    prepared: PreparedAgentChat
    baseline_len: int
    run_id: str
    user_message_id: int
    dashboard_mode: bool = False
    output_schema: Optional[Dict[str, Any]] = None
    tool_names: Optional[List[str]] = None


class AgentChatExecutor:
    """Prepare one DSA Chat request and delegate only execution to a backend."""

    def __init__(
        self,
        *,
        backend: AgentBackend,
        config: Any,
        context_llm_adapter: Any,
        skill_instructions: str = "",
        default_skill_policy: str = "",
        use_legacy_default_prompt: bool = False,
        max_steps: int = 10,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.backend = backend
        self.config = config
        self.context_llm_adapter = context_llm_adapter
        self.skill_instructions = skill_instructions
        self.default_skill_policy = default_skill_policy
        self.use_legacy_default_prompt = use_legacy_default_prompt
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds

    def chat(
        self,
        message: str,
        session_id: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        context: Optional[Dict[str, Any]] = None,
        cancel_event=None,
        selected_skill_ids: Optional[List[str]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        tool_names: Optional[List[str]] = None,
        system_prompt_suffix: str = "",
    ) -> AgentResult:
        turn = self.prepare_turn(
            message=message,
            session_id=session_id,
            context=context,
            selected_skill_ids=selected_skill_ids,
            output_schema=output_schema,
            tool_names=tool_names,
            system_prompt_suffix=system_prompt_suffix,
        )
        return self.execute_turn(
            turn,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    def prepare_turn(
        self,
        *,
        message: str,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
        selected_skill_ids: Optional[List[str]] = None,
        dashboard_mode: bool = False,
        output_schema: Optional[Dict[str, Any]] = None,
        tool_names: Optional[List[str]] = None,
        system_prompt_suffix: str = "",
    ) -> PreparedAgentChatTurn:
        """Prepare context and persist the user message without starting a backend."""
        conversation_manager.get_or_create(session_id)
        prepared = prepare_agent_chat(
            message=message,
            session_id=session_id,
            context=context,
            config=self.config,
            context_llm_adapter=self.context_llm_adapter,
            skill_instructions=self.skill_instructions,
            default_skill_policy=self.default_skill_policy,
            use_legacy_default_prompt=self.use_legacy_default_prompt,
            use_codex_prompt=self.backend.backend_id == "codex_app_server" and not dashboard_mode,
            include_provider_trace=not self.backend.runtime_owns_loop,
            strict_initial_stock_scope=self.backend.runtime_owns_loop,
            dashboard_mode=dashboard_mode,
        )
        if system_prompt_suffix:
            prepared = PreparedAgentChat(
                system_prompt=f"{prepared.system_prompt}\n\n{system_prompt_suffix.strip()}",
                history_messages=prepared.history_messages,
                stock_scope=prepared.stock_scope,
            )
        baseline_len = len(prepared.history_messages) + 2
        run_id = str(uuid.uuid4())
        user_message_id = conversation_manager.add_user_message(
            session_id,
            message,
            selected_skill_ids,
        )
        return PreparedAgentChatTurn(
            message=message,
            session_id=session_id,
            prepared=prepared,
            baseline_len=baseline_len,
            run_id=run_id,
            user_message_id=user_message_id,
            dashboard_mode=dashboard_mode,
            output_schema=output_schema,
            tool_names=tool_names,
        )

    def execute_turn(
        self,
        turn: PreparedAgentChatTurn,
        *,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        cancel_event=None,
    ) -> AgentResult:
        """Execute a previously accepted turn and persist its terminal result."""
        backend_result = self.backend.run(
            AgentRunRequest(
                system_prompt=turn.prepared.system_prompt,
                history_messages=turn.prepared.history_messages,
                user_message=turn.message,
                session_id=turn.session_id,
                stock_scope=turn.prepared.stock_scope,
                max_steps=self.max_steps,
                max_wall_clock_seconds=self.timeout_seconds,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
                output_schema=(
                    turn.output_schema
                    if turn.output_schema is not None
                    else AGENT_DASHBOARD_OUTPUT_SCHEMA if turn.dashboard_mode else None
                ),
                tool_names=turn.tool_names,
            )
        )
        total_tokens = 0
        if isinstance(backend_result.usage, dict):
            total_tokens = int(backend_result.usage.get("total_tokens") or 0)
        result = AgentResult(
            success=backend_result.success,
            content=backend_result.final_answer,
            dashboard=(parse_dashboard_json(backend_result.final_answer) if backend_result.success else None),
            tool_calls_log=backend_result.tool_calls_log,
            total_steps=backend_result.total_steps,
            total_tokens=total_tokens,
            provider=str(backend_result.diagnostics.get("provider") or backend_result.backend),
            model=backend_result.model,
            error=backend_result.error_message,
            messages=backend_result.messages,
            backend=backend_result.backend,
            error_code=backend_result.error_code,
            usage=backend_result.usage,
        )

        if result.success:
            assistant_message_id = conversation_manager.add_message(turn.session_id, "assistant", result.content)
            if not self.backend.runtime_owns_loop:
                persist_provider_trace_turns(
                    session_id=turn.session_id,
                    run_id=turn.run_id,
                    messages=result.messages,
                    baseline_len=turn.baseline_len,
                    user_message_id=turn.user_message_id,
                    assistant_message_id=assistant_message_id,
                )
        else:
            if not self.backend.runtime_owns_loop:
                failure_note = f"[分析失败] {result.error or '未知错误'}"
            elif result.error_code == "cancelled":
                failure_note = "[已停止] 本次分析已由用户停止。"
            elif result.error_code == "timeout":
                failure_note = "[已超时] 本次分析已在时间限制内结束。"
            else:
                failure_note = f"[分析失败] {result.error or '未知错误'}"
            conversation_manager.add_message(
                turn.session_id,
                "assistant",
                failure_note,
            )
        return result

    def run(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """Run one non-conversational turn for batch pipelines.

        This keeps batch Agent analysis on the same backend as Chat when the
        Codex App Server profile is selected, while preserving the existing
        ``AgentExecutor.run`` shape consumed by the DSA pipeline.
        """
        turn = self.prepare_turn(
            message=task,
            session_id=f"dsa-pipeline-{uuid.uuid4()}",
            context=context,
            dashboard_mode=True,
            tool_names=_CODEX_DASHBOARD_TOOL_NAMES,
        )
        return self.execute_turn(turn)
