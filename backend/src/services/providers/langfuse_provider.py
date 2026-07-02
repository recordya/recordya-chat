"""Langfuse observability provider."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LangfuseObservabilityProvider:
    """Langfuse implementation of ObservabilityProvider."""
    
    def __init__(
        self,
        public_key: str,
        secret_key: str,
        host: str | None = None,
        environment: str | None = None,
    ):
        """Initialize Langfuse provider.
        
        Args:
            public_key: Langfuse public key
            secret_key: Langfuse secret key
            host: Optional Langfuse host (defaults to cloud)
        """
        try:
            from langfuse import Langfuse
            
            kwargs: dict[str, Any] = {
                "public_key": public_key,
                "secret_key": secret_key,
            }
            if host:
                kwargs["host"] = host
            if environment:
                kwargs["environment"] = environment
            
            self._client = Langfuse(**kwargs)
            self._enabled = True
        except ImportError:
            logger.warning("Langfuse not installed, observability disabled")
            self._client = None
            self._enabled = False
        except Exception as e:
            logger.warning(f"Failed to initialize Langfuse: {e}")
            self._client = None
            self._enabled = False
    
    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> Any:
        """Start a new trace.
        
        Args:
            name: Name of the trace
            metadata: Optional metadata
            
        Returns:
            Langfuse trace object
        """
        if not self._enabled or not self._client:
            return None
        
        try:
            return self._client.trace(name=name, metadata=metadata or {})
        except Exception as e:
            logger.warning(f"Failed to start Langfuse trace: {e}")
            return None
    
    def log_llm_call(
        self,
        trace: Any,
        request: dict[str, Any],
        response: dict[str, Any],
        duration_ms: int,
    ) -> None:
        """Log an LLM call to Langfuse.
        
        Args:
            trace: Langfuse trace object
            request: LLM request data
            response: LLM response data
            duration_ms: Call duration in milliseconds
        """
        if not self._enabled or not trace:
            return
        
        try:
            trace.generation(
                name="llm_call",
                input=request.get("messages"),
                output=response.get("content"),
                model=request.get("model"),
                usage=response.get("usage"),
                metadata={"duration_ms": duration_ms},
            )
        except Exception as e:
            logger.warning(f"Failed to log LLM call to Langfuse: {e}")
    
    def log_tool_call(
        self,
        trace: Any,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        success: bool,
        duration_ms: int,
    ) -> None:
        """Log a tool call to Langfuse.
        
        Args:
            trace: Langfuse trace object
            tool_name: Name of the tool
            arguments: Tool arguments
            result: Tool result
            success: Whether the call was successful
            duration_ms: Call duration in milliseconds
        """
        if not self._enabled or not trace:
            return
        
        try:
            trace.span(
                name=f"tool:{tool_name}",
                input=arguments,
                output=result,
                metadata={"success": success, "duration_ms": duration_ms},
            )
        except Exception as e:
            logger.warning(f"Failed to log tool call to Langfuse: {e}")
    
    def log_error(self, trace: Any, error: str) -> None:
        """Log an error to Langfuse.
        
        Args:
            trace: Langfuse trace object
            error: Error message
        """
        if not self._enabled or not trace:
            return
        
        try:
            trace.event(name="error", metadata={"error": error})
        except Exception as e:
            logger.warning(f"Failed to log error to Langfuse: {e}")
    
    def flush(self) -> None:
        """Flush pending logs to Langfuse."""
        if not self._enabled or not self._client:
            return
        
        try:
            self._client.flush()
        except Exception as e:
            logger.warning(f"Failed to flush Langfuse: {e}")
