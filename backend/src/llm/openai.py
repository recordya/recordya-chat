"""OpenAI-compatible LLM provider (works with OpenRouter, Fireworks, llama.cpp, etc.)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from langfuse.openai import AsyncOpenAI  # Drop-in replacement with auto-logging

from src.core.config import settings
from src.core.exceptions import LLMError
from src.core.registry import llm_providers

from .base import BaseLLMProvider

# Providers that use standard OpenAI API (no reasoning_effort, max_completion_tokens)
STANDARD_API_PROVIDERS = ["fireworks", "llama", "together", "anyscale", "groq", "ollama"]

# Models that reject `reasoning_effort` combined with function tools on
# /v1/chat/completions (OpenAI requires /v1/responses for that combination).
# For these we drop reasoning_effort when tools are present and let the model
# use its default reasoning level instead.
REASONING_EFFORT_TOOLS_UNSUPPORTED = {
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
}


@llm_providers.register("openai")
class OpenAIProvider(BaseLLMProvider):
    """OpenAI-compatible LLM provider.
    
    Works with OpenAI API, OpenRouter, Fireworks.ai, llama.cpp, and other compatible endpoints.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        name: str = "openai",
    ):
        """Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key (defaults to settings)
            base_url: Base URL for API (defaults to settings, allows OpenRouter)
            name: Provider instance name
        """
        super().__init__(
            name=name,
            supports_tools=True,
            supports_streaming=True,
        )

        self._api_key = api_key or settings.OPENAI_API_KEY
        self._base_url = base_url or settings.OPENAI_BASE_URL

        self._client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url if self._base_url else None,
        )

    def _build_request_params(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any] | None,
        temperature: float | None,
        max_tokens: int | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the request payload, handling provider/model quirks."""
        request_params: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }

        # Detect if using external provider (Fireworks, llama.cpp, etc.)
        base_url_lower = (self._base_url or "").lower()
        is_external_provider = any(p in base_url_lower for p in STANDARD_API_PROVIDERS)

        # Add tools if provided
        if tools:
            # Remove custom fields not supported by external providers
            if is_external_provider:
                cleaned_tools = []
                for tool in tools:
                    clean_tool = {k: v for k, v in tool.items() if k != "status_hint"}
                    cleaned_tools.append(clean_tool)
                request_params["tools"] = cleaned_tools
            else:
                request_params["tools"] = tools
            if tool_choice:
                request_params["tool_choice"] = tool_choice

        # Handle model-specific parameters
        is_openai_model = model.startswith("openai/") or model.startswith("gpt-")

        # Check for reasoning models (o1, o3, gpt-5) that need special parameters
        model_lower = model.lower()
        is_o_series = bool(re.search(r'(^|/)o[134](-|$|[a-z])', model_lower))
        is_gpt5_series = "gpt-5" in model_lower or "gpt-4.1" in model_lower
        uses_reasoning_api = is_o_series or is_gpt5_series

        if is_openai_model and uses_reasoning_api and not is_external_provider:
            # OpenAI o-series and GPT-5 models use max_completion_tokens
            # Default to 8000 to allow for reasoning tokens + output
            request_params["max_completion_tokens"] = max_tokens or 8000
            # Set reasoning_effort only when explicitly provided by policy/caller.
            # Some models reject tools + reasoning_effort on chat/completions; for
            # those we skip it when tools are present (model uses its default level).
            reasoning_effort = kwargs.get("reasoning_effort")
            model_name = model.split("/")[-1].lower()
            tools_block_reasoning = (
                bool(tools) and model_name in REASONING_EFFORT_TOOLS_UNSUPPORTED
            )
            if reasoning_effort is not None and not tools_block_reasoning:
                request_params["reasoning_effort"] = reasoning_effort
        else:
            # Standard models (GPT-4o, Fireworks, llama.cpp, etc.)
            if temperature is not None:
                request_params["temperature"] = temperature
            if max_tokens:
                request_params["max_tokens"] = max_tokens

        # Add any extra kwargs
        for key, value in kwargs.items():
            if key not in request_params and key != "reasoning_effort":
                request_params[key] = value

        return request_params

    @staticmethod
    def _extract_request_overrides(request_params: dict[str, Any]) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        if "temperature" in request_params:
            overrides["temperature"] = request_params["temperature"]
        if "seed" in request_params:
            overrides["seed"] = request_params["seed"]
        return overrides

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
        """Generate a completion using OpenAI API.

        Handles differences between OpenAI and other providers (like Gemini via OpenRouter).
        """
        try:
            request_params = self._build_request_params(
                messages, model, tools, tool_choice, temperature, max_tokens, kwargs,
            )

            response = await self._client.chat.completions.create(**request_params)

            message = response.choices[0].message
            result: dict[str, Any] = {
                "content": message.content,
                "tool_calls": None,
                "usage": None,
                "model": getattr(response, "model", None) or model,
            }

            if message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ]

            if response.usage:
                result["usage"] = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            request_overrides = self._extract_request_overrides(request_params)
            if request_overrides:
                result["request_overrides"] = request_overrides

            return result

        except Exception as e:
            raise LLMError(f"OpenAI API error: {e}") from e

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
        """Stream a completion using OpenAI API."""
        try:
            request_params = self._build_request_params(
                messages, model, tools, tool_choice, temperature, max_tokens, kwargs,
            )
            request_params["stream"] = True
            # Ask for token usage on the final chunk where supported.
            request_params.setdefault("stream_options", {"include_usage": True})

            content_parts: list[str] = []
            tool_calls_acc: dict[int, dict[str, Any]] = {}
            final_model: str | None = None
            usage: dict[str, int] | None = None

            stream = await self._client.chat.completions.create(**request_params)

            async for chunk in stream:
                final_model = getattr(chunk, "model", None) or final_model
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = {
                        "prompt_tokens": chunk_usage.prompt_tokens,
                        "completion_tokens": chunk_usage.completion_tokens,
                        "total_tokens": chunk_usage.total_tokens,
                    }

                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue

                delta_content = getattr(delta, "content", None)
                if delta_content:
                    content_parts.append(delta_content)
                    yield {"type": "content", "delta": delta_content}

                delta_tool_calls = getattr(delta, "tool_calls", None) or []
                for tc in delta_tool_calls:
                    idx = getattr(tc, "index", 0) or 0
                    if idx not in tool_calls_acc:
                        # First time we see this tool call — signal callers so
                        # they can stop forwarding any pending text tokens.
                        yield {"type": "tool_call_started"}
                    entry = tool_calls_acc.setdefault(
                        idx,
                        {"id": None, "type": "function",
                         "function": {"name": "", "arguments": ""}},
                    )
                    if getattr(tc, "id", None):
                        entry["id"] = tc.id
                    if getattr(tc, "type", None):
                        entry["type"] = tc.type
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            entry["function"]["name"] += fn.name
                        if getattr(fn, "arguments", None):
                            entry["function"]["arguments"] += fn.arguments

            tool_calls_final = (
                [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
                if tool_calls_acc
                else None
            )
            content_final = "".join(content_parts) if content_parts else None

            final_result: dict[str, Any] = {
                "type": "final",
                "content": content_final,
                "tool_calls": tool_calls_final,
                "usage": usage,
                "model": final_model or model,
            }
            request_overrides = self._extract_request_overrides(request_params)
            if request_overrides:
                final_result["request_overrides"] = request_overrides
            yield final_result

        except Exception as e:
            raise LLMError(f"OpenAI API error: {e}") from e

    async def health_check(self) -> bool:
        """Check if OpenAI API is available."""
        try:
            # Simple models list call to check connectivity
            await self._client.models.list()
            return True
        except Exception:
            return False
