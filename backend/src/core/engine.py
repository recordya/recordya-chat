"""Core Engine providing primitives for plugins.

The CoreEngine provides LOW-LEVEL primitives - NOT orchestration.
Plugin decides HOW to use these primitives.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, AsyncGenerator

from src.core.config import settings
from src.core.protocols import LLMRequest, LLMResponse, ToolCall, ToolResult

if TYPE_CHECKING:
    from src.services.observability import ObservabilityProvider

logger = logging.getLogger(__name__)


class CoreEngine:
    """Core engine providing primitives - NOT orchestration.
    
    Plugin doesn't know about observability, cache - Core handles them internally.
    """
    
    def __init__(
        self,
        llm_client: Any,
        tool_registry: dict[str, Any] | None = None,
        state_store: dict[str, Any] | None = None,
        observability: "ObservabilityProvider | None" = None,
    ):
        """Initialize CoreEngine.
        
        Args:
            llm_client: LLM facade/client for making LLM calls
            tool_registry: Optional registry of tool handlers
            state_store: Optional state storage for sessions
            observability: Optional observability provider (transparent to plugins)
        """
        self.llm = llm_client
        self.tools = tool_registry or {}
        self.state = state_store or {}
        self._observability = observability  # PRIVATE - plugin doesn't see this
        self._current_trace: Any = None
    
    # =========================================
    # Session Management (starts/ends trace)
    # =========================================
    
    async def start_session(
        self,
        session_id: str,
        plugin_name: str,
        question: str,
        user_id: str | None = None,
    ) -> None:
        """Called by Core before plugin.run() - starts trace.
        
        Args:
            session_id: Unique session ID
            plugin_name: Name of the plugin being executed
            question: User's question
        """
        if self._observability:
            try:
                self._current_trace = self._observability.start_trace(
                    name=f"{plugin_name}_session",
                    metadata={
                        "session_id": session_id,
                        "user_id": user_id,
                        "question": question,
                        "environment": settings.ENV,
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to start observability trace: {e}")
                self._current_trace = None
    
    async def end_session(self) -> None:
        """Called by Core after plugin.run() - ends trace."""
        if self._observability:
            try:
                self._observability.flush()
            except Exception as e:
                logger.warning(f"Failed to flush observability: {e}")
            finally:
                self._current_trace = None
    
    # =========================================
    # LLM Primitives
    # =========================================
    
    async def call_llm(self, request: LLMRequest) -> LLMResponse:
        """Single LLM call - AUTOMATICALLY logged to observability.
        
        Args:
            request: LLM request with messages, model, tools, etc.
            
        Returns:
            LLMResponse with content, tool_calls, usage
        """
        start = time.perf_counter()
        
        # Build kwargs for LLM call
        kwargs: dict[str, Any] = {}
        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        
        # Call LLM via facade
        response = await self.llm.complete(
            messages=request.messages,
            model=request.model,
            tools=request.tools,
            purpose="agent",
            **kwargs,
        )
        
        duration_ms = int((time.perf_counter() - start) * 1000)
        
        # Build LLMResponse
        llm_response = LLMResponse(
            content=response.get("content"),
            tool_calls=response.get("tool_calls"),
            usage=response.get("usage"),
            model=response.get("model"),
        )
        
        # === TRANSPARENT LOGGING ===
        if self._observability and self._current_trace:
            try:
                self._observability.log_llm_call(
                    trace=self._current_trace,
                    request={
                        "messages": request.messages,
                        "model": request.model,
                        "temperature": response.get("request_overrides", {}).get("temperature"),
                        "seed": response.get("request_overrides", {}).get("seed"),
                    },
                    response={
                        "content": llm_response.content,
                        "usage": llm_response.usage,
                        "model": llm_response.model or request.model,
                    },
                    duration_ms=duration_ms,
                )
            except Exception as e:
                logger.warning(f"Failed to log LLM call: {e}")
        
        return llm_response
    
    async def stream_llm(self, request: LLMRequest) -> AsyncGenerator[str, None]:
        """Streaming LLM call - AUTOMATICALLY logged via call_llm().

        NOTE: This is currently simulated streaming - it calls call_llm() and
        yields the complete response as a single chunk. True streaming requires
        implementing a stream() method in LLMProvider and LlmFacade.

        Observability logging is handled by call_llm() - no duplicate logging here.

        Args:
            request: LLM request

        Yields:
            String chunks from the LLM response (currently single chunk)
        """
        # TODO: Implement true streaming when LLMProvider.stream() is available
        # For now, delegate to call_llm() which handles logging
        response = await self.call_llm(request)
        if response.content:
            yield response.content
    
    # =========================================
    # Tool Primitives
    # =========================================
    
    async def execute_tool(
        self,
        call: ToolCall,
        handler: Any = None,
    ) -> ToolResult:
        """Execute a single tool - AUTOMATICALLY logged.
        
        Args:
            call: Tool call with name and arguments
            handler: Optional explicit handler, otherwise looks up in registry
            
        Returns:
            ToolResult with success status and data/error
        """
        start = time.perf_counter()
        
        # Get handler from registry if not provided
        if handler is None:
            handler = self.tools.get(call.name)
        
        if not handler:
            result = ToolResult(
                call_id=call.id,
                success=False,
                data=None,
                error=f"Unknown tool: {call.name}"
            )
        else:
            try:
                data = await handler(call.arguments)
                
                # Handle dict result from legacy plugins
                if isinstance(data, dict):
                    result = ToolResult(
                        call_id=call.id,
                        success=data.get("success", True),
                        data=data.get("result", data),
                        error=data.get("error"),
                        sql=data.get("sql"),
                        tool_type=data.get("tool_type"),
                        row_count=data.get("row_count"),
                    )
                else:
                    result = ToolResult(
                        call_id=call.id,
                        success=True,
                        data=data,
                    )
            except Exception as e:
                logger.error(f"Tool {call.name} failed: {e}")
                result = ToolResult(
                    call_id=call.id,
                    success=False,
                    data=None,
                    error=str(e)
                )
        
        duration_ms = int((time.perf_counter() - start) * 1000)
        
        # === TRANSPARENT LOGGING ===
        if self._observability and self._current_trace:
            try:
                self._observability.log_tool_call(
                    trace=self._current_trace,
                    tool_name=call.name,
                    arguments=call.arguments,
                    result=result.data if result.success else result.error,
                    success=result.success,
                    duration_ms=duration_ms,
                )
            except Exception as e:
                logger.warning(f"Failed to log tool call: {e}")
        
        return result
    
    async def execute_tools_parallel(
        self,
        calls: list[ToolCall],
        handlers: dict[str, Any] | None = None,
    ) -> list[ToolResult]:
        """Execute multiple tools in parallel.
        
        Args:
            calls: List of tool calls
            handlers: Optional dict of tool handlers
            
        Returns:
            List of ToolResults in same order as calls
        """
        import asyncio
        
        async def execute_one(call: ToolCall) -> ToolResult:
            handler = (handlers or {}).get(call.name) or self.tools.get(call.name)
            return await self.execute_tool(call, handler)
        
        results = await asyncio.gather(*[execute_one(call) for call in calls])
        return list(results)
    
    # =========================================
    # State Primitives
    # =========================================
    
    async def get_state(self, session_id: str, key: str) -> Any:
        """Get state value.
        
        Args:
            session_id: Session identifier
            key: State key
            
        Returns:
            State value or None
        """
        session_state = self.state.get(session_id, {})
        return session_state.get(key)
    
    async def set_state(self, session_id: str, key: str, value: Any) -> None:
        """Set state value.
        
        Args:
            session_id: Session identifier
            key: State key
            value: Value to store
        """
        if session_id not in self.state:
            self.state[session_id] = {}
        self.state[session_id][key] = value
    
    # =========================================
    # Output Events (helpers for plugins)
    # =========================================
    
    def emit_status(self, message: str, step: int = 0) -> dict[str, Any]:
        """Create status event for streaming.
        
        Args:
            message: Status message to display
            step: Current step number
            
        Returns:
            Event dict with type 'status'
        """
        return {"type": "status", "data": {"message": message, "step": step}}
    
    def emit_tool(self, name: str, duration_ms: int) -> dict[str, Any]:
        """Create tool event for streaming.
        
        Args:
            name: Tool name
            duration_ms: Execution time in milliseconds
            
        Returns:
            Event dict with type 'tool'
        """
        return {"type": "tool", "data": {"name": name, "duration_ms": duration_ms}}
    
    def emit_complete(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        tool_history: list[dict[str, Any]] | None = None,
        iterations: int = 1,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Create completion event.
        
        Args:
            content: Final response content
            metadata: Optional additional metadata
            tool_history: Optional list of tool executions
            iterations: Number of agentic loop iterations
            trace_id: Optional trace ID for observability
            
        Returns:
            Event dict with type 'complete'
        """
        data: dict[str, Any] = {
            "content": content,
            "tool_history": tool_history or [],
            "iterations": iterations,
        }
        if metadata:
            data.update(metadata)
        if trace_id:
            data["langfuse_trace_id"] = trace_id
        return {"type": "complete", "data": data}
    
    def emit_error(self, message: str, trace_id: str | None = None) -> dict[str, Any]:
        """Create error event.

        Args:
            message: Error message
            trace_id: Optional trace ID for observability

        Returns:
            Event dict with type 'error'
        """
        data: dict[str, Any] = {"message": message}
        if trace_id:
            data["langfuse_trace_id"] = trace_id
        return {"type": "error", "data": data}


