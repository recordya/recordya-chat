"""LLM model parameter policies."""

from __future__ import annotations

import os
from typing import Any


def _is_openai_model(model: str) -> bool:
    return model.startswith("openai/") or model.startswith("gpt-")


def _is_reasoning_model(model: str) -> bool:
    """Check if model is an o-series or GPT-5 reasoning model.

    Reasoning models: o1, o1-mini, o1-preview, o3, o3-mini, gpt-5, etc.
    NOT reasoning: gpt-4, gpt-4o, gpt-4o-mini, gpt-4-turbo, etc.
    """
    model_lower = model.lower()

    # Check for o-series models (o1, o1-mini, o1-preview, o3, etc.)
    # Must start with 'o' followed by a digit, or contain '/o' followed by a digit
    import re

    if re.search(r"(^|/)o[134](-|$|[a-z])", model_lower):
        return True

    # Check for GPT-5 series
    if "gpt-5" in model_lower or "gpt-4.1" in model_lower:
        return True

    return False


class ModelPolicy:
    """Return default LLM parameters based on model and purpose."""

    def __init__(self):
        self.max_summary_tokens = int(os.environ.get("MAX_SUMMARY_TOKENS", 4000))
        self.summary_temperature = float(os.environ.get("SUMMARY_TEMPERATURE", 0))
        self.summary_reasoning = os.environ.get("SUMMARY_REASONING", "low")

        self.max_agent_tokens = int(os.environ.get("MAX_AGENT_TOKENS", 8000))
        self.agent_temperature = float(os.environ.get("AGENT_TEMPERATURE", 0))
        self.agent_reasoning = os.environ.get("AGENT_REASONING", "low")

    def for_purpose(self, model: str, purpose: str) -> dict[str, Any]:
        if purpose == "summary":
            return self._summary_params(model)
        return self._agent_params(model)

    def _agent_params(self, model: str) -> dict[str, Any]:
        params = {"max_tokens": self.max_agent_tokens, "temperature": self.agent_temperature}
        if _is_openai_model(model):
            params["seed"] = 42

        if _is_reasoning_model(model):
            params["reasoning_effort"] = self.agent_reasoning

        return params

    def _summary_params(self, model: str) -> dict[str, Any]:
        params = {"max_tokens": self.max_summary_tokens, "temperature": self.summary_temperature}
        if _is_openai_model(model):
            params["seed"] = 42

        if _is_reasoning_model(model):
            params["reasoning_effort"] = self.summary_reasoning

        return params
