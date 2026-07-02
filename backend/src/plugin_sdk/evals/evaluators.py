"""Shared heuristic evaluators and evaluator factories for plugin evals.

Provides parametrised factory functions so each plugin can create evaluators
with its own domain-specific signals without duplicating boilerplate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langfuse import Evaluation
from langfuse.experiment import ExperimentItemResult

# Langfuse evaluator callback signature.
EvalFn = Callable[..., Evaluation | None]


# ---------------------------------------------------------------------------
# Utilities (shared across all plugins)
# ---------------------------------------------------------------------------


def extract_content(output: dict[str, Any]) -> str:
    """Return the text content from an eval output dict."""
    return output.get("content", "")


def extract_tool_history(output: dict[str, Any]) -> list[dict[str, Any]]:
    """Return tool_history from an eval output dict."""
    return output.get("tool_history", [])


def _lower(text: str | None) -> str:
    return (text or "").lower()


# ---------------------------------------------------------------------------
# Evaluator factories
# ---------------------------------------------------------------------------


def make_hidden_columns_evaluator(
    hidden_columns: tuple[str, ...] | list[str],
) -> EvalFn:
    """Create an evaluator that checks internal column/table names don't leak.

    Args:
        hidden_columns: snake_case identifiers that must never appear in output.
    """
    columns = tuple(hidden_columns)

    def hidden_columns_evaluator(
        *, input: str, output: dict, expected_output: str, metadata: dict, **kwargs: Any,
    ) -> Evaluation:
        out = _lower(extract_content(output))
        leaked = [col for col in columns if col in out]
        return Evaluation(
            name="hidden_columns_safe",
            value=0.0 if leaked else 1.0,
            comment=f"Leaked columns: {leaked}" if leaked else "No hidden columns leaked",
        )

    return hidden_columns_evaluator


def make_no_technical_leak_evaluator(
    *,
    always_forbidden: tuple[str, ...] | list[str],
    non_refusal_forbidden: tuple[str, ...] | list[str],
    refusal_markers: list[str],
) -> EvalFn:
    """Create an evaluator that checks technical details don't leak.

    Args:
        always_forbidden: Signals always forbidden in output.
        non_refusal_forbidden: Signals forbidden only when output is NOT a refusal.
        refusal_markers: Phrases indicating the response is a refusal.
    """
    _always = tuple(always_forbidden)
    _non_refusal = tuple(non_refusal_forbidden)
    _refusal = list(refusal_markers)

    def no_technical_leak_evaluator(
        *, input: str, output: dict, expected_output: str, metadata: dict, **kwargs: Any,
    ) -> Evaluation:
        content = extract_content(output)
        leaked = [s for s in _always if s in content]

        out_lower = _lower(content)
        is_refusal = any(m in out_lower for m in _refusal)
        if not is_refusal:
            leaked.extend(s for s in _non_refusal if s in content)

        return Evaluation(
            name="no_technical_leak",
            value=0.0 if leaked else 1.0,
            comment=f"Leaked: {leaked}" if leaked else "No technical details leaked",
        )

    return no_technical_leak_evaluator


# ---------------------------------------------------------------------------
# Run-level evaluator (generic)
# ---------------------------------------------------------------------------


def run_overall_score(
    *, item_results: list[ExperimentItemResult], **kwargs: object,
) -> Evaluation:
    """Compute average score across all items and evaluators."""
    scores: list[float] = []
    for item in item_results:
        for ev in item.evaluations:
            if isinstance(ev.value, (int, float)):
                scores.append(float(ev.value))
    avg = sum(scores) / len(scores) if scores else 0.0
    return Evaluation(name="overall_score", value=round(avg, 4))

