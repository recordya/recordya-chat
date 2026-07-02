"""Base class for LLM providers."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers.
    
    Provides common functionality and defines the interface that all
    LLM providers must implement.
    """

    def __init__(
        self,
        name: str = "base",
        supports_tools: bool = True,
        supports_streaming: bool = True,
    ):
        """Initialize LLM provider.
        
        Args:
            name: Unique identifier for this provider instance
            supports_tools: Whether this provider supports tool/function calling
            supports_streaming: Whether this provider supports streaming responses
        """
        self.name = name
        self.supports_tools = supports_tools
        self.supports_streaming = supports_streaming

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a completion from the LLM.
        
        Args:
            messages: List of conversation messages
            model: Model identifier to use
            tools: Optional list of tool definitions
            tool_choice: How the model should choose tools
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters
            
        Returns:
            Dictionary with completion result containing:
            - content: Response text (or None if using tools)
            - tool_calls: List of tool calls (if any)
            - usage: Token usage statistics
        """
        pass

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a completion from the LLM.

        Default implementation delegates to ``complete`` and yields a single
        ``final`` chunk. Providers that natively support streaming should
        override this method to yield ``content`` deltas progressively.

        Yields:
            Dict chunks with one of the following shapes:
            - ``{"type": "content", "delta": str}`` — partial text token
            - ``{"type": "final", **complete_result}`` — same shape as
              :meth:`complete`'s return value, emitted exactly once at the end.
        """
        result = await self.complete(
            messages=messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        yield {"type": "final", **result}

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the LLM provider is available.

        Returns:
            True if provider is available, False otherwise
        """
        pass

    def format_tool_result(
        self,
        tool_call_id: str,
        result: Any,
    ) -> dict[str, Any]:
        """Format a tool result for the conversation.
        
        Args:
            tool_call_id: ID of the tool call
            result: Result from executing the tool
            
        Returns:
            Formatted message dict for the conversation
        """
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": str(result) if not isinstance(result, str) else result,
        }
