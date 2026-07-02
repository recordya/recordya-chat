"""Observability providers for transparent logging.

Plugin doesn't know about observability - Core handles it internally.
"""

from typing import Any, Protocol


class ObservabilityProvider(Protocol):
    """Interface for observability providers."""
    
    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> Any:
        """Start a new trace.
        
        Args:
            name: Name of the trace
            metadata: Optional metadata
            
        Returns:
            Trace object (provider-specific)
        """
        ...
    
    def log_llm_call(
        self,
        trace: Any,
        request: dict[str, Any],
        response: dict[str, Any],
        duration_ms: int,
    ) -> None:
        """Log an LLM call.
        
        Args:
            trace: Trace object from start_trace
            request: LLM request data
            response: LLM response data
            duration_ms: Call duration in milliseconds
        """
        ...
    
    def log_tool_call(
        self,
        trace: Any,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        success: bool,
        duration_ms: int,
    ) -> None:
        """Log a tool call.
        
        Args:
            trace: Trace object from start_trace
            tool_name: Name of the tool
            arguments: Tool arguments
            result: Tool result
            success: Whether the call was successful
            duration_ms: Call duration in milliseconds
        """
        ...
    
    def log_error(self, trace: Any, error: str) -> None:
        """Log an error.
        
        Args:
            trace: Trace object from start_trace
            error: Error message
        """
        ...
    
    def flush(self) -> None:
        """Flush any pending logs."""
        ...


class NoOpObservabilityProvider:
    """No-op implementation for when observability is disabled."""
    
    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> Any:
        return None
    
    def log_llm_call(
        self,
        trace: Any,
        request: dict[str, Any],
        response: dict[str, Any],
        duration_ms: int,
    ) -> None:
        pass
    
    def log_tool_call(
        self,
        trace: Any,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        success: bool,
        duration_ms: int,
    ) -> None:
        pass
    
    def log_error(self, trace: Any, error: str) -> None:
        pass
    
    def flush(self) -> None:
        pass
