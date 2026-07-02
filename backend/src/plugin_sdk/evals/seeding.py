"""Shared Langfuse dataset/prompt seeding helpers for plugin eval runners.

Each plugin's ``run_eval.py`` keeps its own module-level env setup
(dotenv, path manipulation, config patching) because those are
plugin-specific. These helpers eliminate the duplicated seeding logic.

Usage::

    from src.plugin_sdk.evals.seeding import seed_prompt, seed_dataset

    seed_prompt(langfuse, plugin_id="my_plugin", prompt_template=PROMPT_TEMPLATE)
    seed_dataset(langfuse, dataset_name="my_plugin_evals", eval_items=EVAL_ITEMS)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langfuse import Langfuse

logger = logging.getLogger(__name__)


def _to_langfuse_template(python_template: str) -> str:
    """Convert Python ``{var}`` placeholders to Langfuse ``{{var}}``."""
    return re.sub(r"\{(\w+)\}", r"{{\1}}", python_template)


def seed_prompt(
    langfuse: Langfuse,
    *,
    plugin_id: str,
    prompt_template: str,
) -> int:
    """Seed PROMPT_TEMPLATE to Langfuse only if the prompt does not exist yet.

    Returns the current prompt version number.
    """
    try:
        existing = langfuse.get_prompt(plugin_id, label="production")
        logger.info(
            "Langfuse prompt '%s' v%s already exists — skipping seed",
            plugin_id, existing.version,
        )
        return existing.version
    except Exception:
        logger.debug("Langfuse prompt '%s' not found — will create initial version", plugin_id)

    langfuse_template = _to_langfuse_template(prompt_template)
    prompt = langfuse.create_prompt(
        name=plugin_id, prompt=langfuse_template, labels=["production"],
    )
    logger.info("Langfuse prompt '%s' v%s created (initial seed)", plugin_id, prompt.version)
    return prompt.version


def resolve_prompt_version(langfuse: Langfuse, *, plugin_id: str, label: str) -> int:
    """Return the prompt version for the given label."""
    prompt = langfuse.get_prompt(plugin_id, label=label)
    return prompt.version


def seed_dataset(
    langfuse: Langfuse,
    *,
    dataset_name: str,
    eval_items: list[dict[str, Any]],
) -> None:
    """Create/update dataset items from code definition.

    New items are created; existing items (matched by input) are updated
    so that ``expected_output`` and ``metadata`` stay in sync with code.
    """
    langfuse.create_dataset(name=dataset_name)
    existing = langfuse.get_dataset(dataset_name)

    def _input_key(inp: Any) -> str:
        return json.dumps(inp, ensure_ascii=False, sort_keys=True) if isinstance(inp, list) else inp

    existing_by_input = {_input_key(item.input): item for item in existing.items}

    created, updated = 0, 0
    for item in eval_items:
        expected_output = item["expected_output"]
        metadata = item.get("metadata", {})
        existing_item = existing_by_input.get(_input_key(item["input"]))

        if existing_item is None:
            langfuse.create_dataset_item(
                dataset_name=dataset_name, input=item["input"],
                expected_output=expected_output, metadata=metadata,
            )
            created += 1
        elif (
            existing_item.expected_output != expected_output
            or existing_item.metadata != metadata
        ):
            langfuse.create_dataset_item(
                id=existing_item.id, dataset_name=dataset_name,
                input=item["input"], expected_output=expected_output,
                metadata=metadata,
            )
            updated += 1

    if created or updated:
        logger.info("Dataset '%s': %d created, %d updated", dataset_name, created, updated)

