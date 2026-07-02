"""Tests for leaked_tool_guard helpers and guard lifecycle."""

from src.services.leaked_tool_guard import (
    LeakedToolGuard,
    _build_detect_pattern,
    _build_strip_pattern,
    _extract_tool_names,
    _sanitize_content,
)

_NESTED_TOOL_CALL = (
    'make_choices({"title":"Pick","questions":'
    '[{"id":"q1","prompt":"P?","options":[{"id":"a","label":"A"}]}]})'
)

_NESTED_WIDGET_JSON = (
    '{"_widget_type":"make_choices","_widget_payload":{"title":"T",'
    '"questions":[{"id":"q1","prompt":"P?",'
    '"options":[{"id":"a","label":"A"}]}]}}'
)


class TestExtractToolNames:
    def test_extracts_names_from_tool_definitions(self):
        tools = [
            {"type": "function", "function": {"name": "make_choices", "parameters": {}}},
            {"type": "function", "function": {"name": "generate_custom_sql", "parameters": {}}},
        ]

        assert _extract_tool_names(tools) == ["make_choices", "generate_custom_sql"]

    def test_empty_tools_list(self):
        assert _extract_tool_names([]) == []

    def test_skips_malformed_entries(self):
        tools = [
            {"type": "function", "function": {"name": "valid_tool"}},
            {"type": "function", "function": {}},
            {"type": "function"},
        ]

        assert _extract_tool_names(tools) == ["valid_tool"]


class TestBuildDetectPattern:
    def test_returns_none_for_empty_list(self):
        assert _build_detect_pattern([]) is None

    def test_matches_bare_tool_name(self):
        pattern = _build_detect_pattern(["make_choices"])
        assert pattern.search("make_choices({")

    def test_matches_functions_prefix(self):
        pattern = _build_detect_pattern(["make_choices"])
        assert pattern.search("functions.make_choices({")
        assert pattern.search("function.make_choices({")

    def test_does_not_match_unrelated_text(self):
        pattern = _build_detect_pattern(["make_choices"])
        assert not pattern.search("I will make some choices for you")


class TestLeakedToolGuard:
    def _make_guard(self, tool_names: list[str] | None = None) -> LeakedToolGuard:
        tools = [{"type": "function", "function": {"name": name}} for name in (tool_names or [])]
        return LeakedToolGuard.from_tools(tools)

    def test_detects_functions_prefix(self):
        guard = self._make_guard()
        assert guard.has_leak("functions.anything({})")

    def test_detects_widget_json(self):
        guard = self._make_guard()
        content = '{"_widget_type": "voice_actor_cards", "_widget_payload": {}}'
        assert guard.has_leak(content)

    def test_detects_dynamic_tool_name(self):
        guard = self._make_guard(["make_choices"])
        assert guard.has_leak('make_choices({"title": "Pick one"})')

    def test_clean_content_returns_false(self):
        guard = self._make_guard(["make_choices"])
        assert not guard.has_leak("Here is the list of voice actors to choose from.")

    def test_detects_widget_json_with_surrounding_text(self):
        guard = self._make_guard()
        content = (
            'Here are the voice options:\n\n'
            '{"_widget_type":"voice_actor_cards","_widget_payload":{"rows":[]}}'
        )
        assert guard.has_leak(content)

    def test_should_retry_true_on_first_leak(self):
        guard = self._make_guard()
        assert guard.should_retry('functions.foo({"x": 1})')

    def test_should_retry_false_after_max_retries(self):
        guard = self._make_guard()
        messages: list[dict] = []
        guard.append_correction(messages, 'functions.foo({"x": 1})')
        assert not guard.should_retry('functions.foo({"x": 1})')

    def test_should_retry_false_for_clean_content(self):
        guard = self._make_guard()
        assert not guard.should_retry("Here is the answer.")

    def test_should_retry_false_for_none(self):
        guard = self._make_guard()
        assert not guard.should_retry(None)

    def test_append_correction_adds_messages(self):
        guard = self._make_guard()
        messages: list[dict] = []
        guard.append_correction(messages, "leaked content")

        assert len(messages) == 2
        assert messages[0]["role"] == "assistant"
        assert messages[1]["role"] == "user"
        assert "tool_calls" in messages[1]["content"]

    def test_finalize_returns_clean_content(self):
        guard = self._make_guard()
        assert guard.finalize("Here is the answer.") == "Here is the answer."

    def test_finalize_sanitizes_leaked_content(self):
        guard = self._make_guard()
        content = (
            'Here are the suggestions:\n\n'
            '{"_widget_type":"cards","_widget_payload":{"rows":[]}}'
        )
        result = guard.finalize(content)

        assert "_widget_type" not in result
        assert "Here are the suggestions:" in result

    def test_finalize_sanitizes_nested_widget_json(self):
        guard = self._make_guard()
        content = f"Here are the questions:\n\n{_NESTED_WIDGET_JSON}"
        assert guard.finalize(content) == "Here are the questions:"

    def test_finalize_returns_empty_for_none(self):
        guard = self._make_guard()
        assert guard.finalize(None) == ""

    def test_finalize_returns_empty_when_only_json(self):
        guard = self._make_guard()
        content = '{"_widget_type":"cards","_widget_payload":{"rows":[]}}'
        assert guard.finalize(content) == ""


class TestSanitizeContent:
    def test_strips_functions_call_block(self):
        content = 'Please clarify\n\nfunctions.make_choices({"title": "Pick", "questions": []})'
        result = _sanitize_content(content)

        assert result == "Please clarify"
        assert "functions" not in result

    def test_strips_widget_json(self):
        content = (
            'Here are the voice suggestions:\n\n'
            '{"_widget_type":"voice_actor_cards","_widget_payload":{"rows":[]}}'
        )
        result = _sanitize_content(content)

        assert result == "Here are the voice suggestions:"
        assert "_widget_type" not in result

    def test_strips_with_dynamic_tool_pattern(self):
        strip_re = _build_strip_pattern(["make_choices"])
        content = 'Choose an option\n\nmake_choices({"title": "Pick"})'
        assert _sanitize_content(content, strip_re) == "Choose an option"

    def test_strips_nested_dynamic_tool_pattern(self):
        strip_re = _build_strip_pattern(["make_choices"])
        content = f"Choose an option\n\n{_NESTED_TOOL_CALL}"
        assert _sanitize_content(content, strip_re) == "Choose an option"

    def test_strips_nested_widget_json(self):
        content = f"Here are the questions:\n\n{_NESTED_WIDGET_JSON}"
        assert _sanitize_content(content) == "Here are the questions:"

    def test_returns_empty_when_only_json(self):
        content = '{"_widget_type":"voice_actor_cards","_widget_payload":{"rows":[]}}'
        assert _sanitize_content(content) == ""

    def test_returns_empty_when_only_function_call(self):
        content = 'functions.make_choices({"title": "Pick", "questions": []})'
        assert _sanitize_content(content) == ""

    def test_preserves_clean_content(self):
        content = "Here is the list of voice actors to choose from."
        assert _sanitize_content(content) == content
