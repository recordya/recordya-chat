"""LLM-as-judge evaluators — shared infrastructure.

Provides ``LLMJudge`` class that each plugin instantiates with its own
domain-specific hidden column descriptions.

Usage::

    from src.plugin_sdk.evals.llm_judge import LLMJudge

    judge = LLMJudge(
        plugin_display_name="MarketEcho",
        hidden_columns_description="audiobooks_normalized, platform_id, ...",
        allowed_phrases='"audiobooki", "autorzy"',
        forbidden_examples='"audiobooks_normalized", "platform_id"',
    )

    # Use as Langfuse evaluator callbacks:
    evaluators = [judge.behaviour_evaluator, judge.hidden_columns_evaluator]
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langfuse import Evaluation
from langfuse.openai import AsyncOpenAI

from src.plugin_sdk.evals.evaluators import extract_content

logger = logging.getLogger(__name__)

JUDGE_MODEL = "gpt-4o-mini"


class LLMJudge:
    """LLM-as-judge evaluator pair for a plugin.

    Encapsulates the OpenAI client lifecycle and provides two Langfuse-compatible
    evaluator methods: ``behaviour_evaluator`` and ``hidden_columns_evaluator``.
    """

    def __init__(
        self,
        *,
        plugin_display_name: str,
        hidden_columns_description: str,
        allowed_phrases: str,
        forbidden_examples: str,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._client: AsyncOpenAI | None = client
        self._client_lock = asyncio.Lock()

        self._system_prompt = (
            f"You are an evaluator for an AI assistant called {plugin_display_name}.\n"
            "Your job is to judge whether the assistant's response matches "
            "the expected behaviour.\n\n"
            "Rules:\n"
            '- Answer ONLY "PASS" or "FAIL" on the first line.\n'
            "- On the second line give a short reason (max 30 words).\n"
            "- PASS if the response fulfils the intent of the expected behaviour, "
            "even if the exact wording or level of detail differs.\n"
            "- FAIL only if the response clearly contradicts or ignores "
            "the expected behaviour."
        )

        self._hidden_prompt_template = (
            "The assistant must NEVER leak internal database column or table names "
            "in its response. These are snake_case identifiers like:\n"
            f"{hidden_columns_description}\n\n"
            "IMPORTANT: Only flag a FAIL if the response contains the EXACT snake_case "
            "identifier with underscores. Natural Polish words and phrases are NOT leaks.\n"
            f"Examples of ALLOWED phrases (PASS):\n{allowed_phrases}\n\n"
            f"Examples of FORBIDDEN strings (FAIL):\n{forbidden_examples}\n\n"
            "## Assistant response\n{{content}}\n\n"
            "Does the response contain any exact forbidden identifiers? "
            "Answer PASS (no leak) or FAIL (leak)."
        )

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------

    async def _get_client(self) -> AsyncOpenAI:
        async with self._client_lock:
            if self._client is None:
                from src.core.config import get_settings
                settings = get_settings()
                self._client = AsyncOpenAI(
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_BASE_URL or None,
                )
        return self._client

    # ------------------------------------------------------------------
    # Shared judge call
    # ------------------------------------------------------------------

    async def _judge(self, user_prompt: str) -> tuple[bool, str]:
        """Send a PASS/FAIL question to the judge model."""
        client = await self._get_client()
        response = await client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=60,
        )
        text = (response.choices[0].message.content or "").strip()
        lines = text.split("\n", 1)
        verdict = lines[0].strip().upper()
        reason = lines[1].strip() if len(lines) > 1 else ""
        return verdict.startswith("PASS"), reason

    # ------------------------------------------------------------------
    # Langfuse evaluator callbacks
    # ------------------------------------------------------------------

    async def behaviour_evaluator(
        self,
        *, input: str | list, output: dict, expected_output: str,
        metadata: dict, **kwargs: Any,
    ) -> Evaluation | None:
        """LLM-as-judge: does the response match the expected behaviour?"""
        description = (metadata or {}).get("expected_behaviour")
        if not description:
            return None
        content = extract_content(output)
        user_question = input[-1] if isinstance(input, list) else input
        prompt = (
            f"## Expected behaviour\n{description}\n\n"
            f"## User question\n{user_question}\n\n"
            f"## Assistant response\n{content}\n\n"
            "Does the assistant's response match the expected behaviour? "
            "Answer PASS or FAIL."
        )
        passed, reason = await self._judge(prompt)
        return Evaluation(
            name="llm_behaviour_match",
            value=1.0 if passed else 0.0,
            comment=reason or ("PASS" if passed else "FAIL"),
        )

    async def hidden_columns_evaluator(
        self,
        *, input: str, output: dict, expected_output: str,
        metadata: dict, **kwargs: Any,
    ) -> Evaluation:
        """LLM-as-judge: do hidden column names leak into the response?"""
        content = extract_content(output)
        prompt = self._hidden_prompt_template.format(content=content)
        passed, reason = await self._judge(prompt)
        return Evaluation(
            name="llm_hidden_columns_safe",
            value=1.0 if passed else 0.0,
            comment=reason or ("PASS" if passed else "FAIL"),
        )

