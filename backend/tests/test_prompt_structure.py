"""Generic prompt structure tests — plugin-independent.

Tests ConversationBuilder and prompt hash mechanism without
depending on any specific plugin implementation.

Run:
    pytest tests/test_prompt_structure.py -v
"""

import hashlib

import pytest


# ---------------------------------------------------------------------------
# Tests: prompt hash stability
# ---------------------------------------------------------------------------


@pytest.mark.prompt_eval
class TestPromptHash:
    """Verify prompt hash mechanism works correctly."""

    def test_hash_deterministic(self):
        from src.plugin_sdk.sql import BaseSQLPlugin

        class StubPlugin(BaseSQLPlugin):
            PROMPT_TEMPLATE = "Hello {name}"
            allowed_tables = frozenset()

            def get_predefined_tools(self):
                return []

            async def _get_template_vars(self):
                return {"name": "world"}

        plugin = StubPlugin()
        assert plugin.get_prompt_hash() == plugin.get_prompt_hash()

    def test_hash_changes_on_template_change(self):
        from src.plugin_sdk.sql import BaseSQLPlugin

        class PluginA(BaseSQLPlugin):
            PROMPT_TEMPLATE = "Version A"
            allowed_tables = frozenset()

            def get_predefined_tools(self):
                return []

            async def _get_template_vars(self):
                return {}

        class PluginB(BaseSQLPlugin):
            PROMPT_TEMPLATE = "Version B"
            allowed_tables = frozenset()

            def get_predefined_tools(self):
                return []

            async def _get_template_vars(self):
                return {}

        assert PluginA().get_prompt_hash() != PluginB().get_prompt_hash()

    def test_hash_matches_manual_sha256(self):
        from src.plugin_sdk.sql import BaseSQLPlugin

        template = "Test template content"

        class StubPlugin(BaseSQLPlugin):
            PROMPT_TEMPLATE = template
            allowed_tables = frozenset()

            def get_predefined_tools(self):
                return []

            async def _get_template_vars(self):
                return {}

        expected = hashlib.sha256(template.encode()).hexdigest()[:12]
        assert StubPlugin().get_prompt_hash() == expected

