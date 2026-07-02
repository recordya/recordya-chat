"""Shared evaluation framework for plugin prompt evals.

Usage:
    from src.plugin_sdk.evals import (
        # Utilities
        extract_content,
        extract_tool_history,
        # Evaluator factories
        make_hidden_columns_evaluator,
        make_no_technical_leak_evaluator,
        run_overall_score,
        # LLM judge
        LLMJudge,
        # Seeding helpers
        seed_prompt,
        seed_dataset,
        resolve_prompt_version,
    )
"""

from src.plugin_sdk.evals.evaluators import (  # noqa: E402
    extract_content,
    extract_tool_history,
    make_hidden_columns_evaluator,
    make_no_technical_leak_evaluator,
    run_overall_score,
)
from src.plugin_sdk.evals.execution import run_single_turn  # noqa: E402
from src.plugin_sdk.evals.llm_judge import LLMJudge  # noqa: E402
from src.plugin_sdk.evals.seeding import (  # noqa: E402
    resolve_prompt_version,
    seed_dataset,
    seed_prompt,
)

__all__ = [
    "extract_content",
    "extract_tool_history",
    "make_hidden_columns_evaluator",
    "make_no_technical_leak_evaluator",
    "run_overall_score",
    "run_single_turn",
    "LLMJudge",
    "seed_prompt",
    "seed_dataset",
    "resolve_prompt_version",
]

