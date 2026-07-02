"""Guard against LLM leaking tool calls / widget JSON into content text.

LLMs sometimes "simulate" tool calls by dumping raw function invocations or
widget JSON into the content text instead of using the ``tool_calls`` mechanism.

``LeakedToolGuard`` detects this, allows one retry, and sanitizes if needed.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detection patterns (always active, independent of plugin tools)
# ---------------------------------------------------------------------------

# Generic "functions.xxx(" prefix — always a leak regardless of tool name.
_LEAKED_FUNC_PREFIX_RE = re.compile(r'functions?\.\w+\s*\(', re.IGNORECASE)
# Raw widget JSON: {"_widget_type": ...}
_LEAKED_WIDGET_JSON_RE = re.compile(r'\{\s*"_widget_type"\s*:')
_BALANCED_PAIRS = {"(": ")", "{": "}", "[": "]"}

_LEAKED_RETRY_CORRECTION = (
    "Your response contains a raw function call or JSON in the text. "
    "Do not write tool invocations in the response text — "
    "use the tool_calls mechanism to call the tool instead. "
    "Please answer again correctly."
)

# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class LeakedToolGuard:
    """Detects and handles tool-call / widget-JSON leaked into LLM content.

    Usage inside the agentic loop::

        guard = LeakedToolGuard.from_tools(tools)

        # after LLM response, before emitting final content:
        if guard.should_retry(content):
            guard.append_correction(messages, content)
            continue

        final_content = guard.finalize(content)
    """

    _max_retries: int = 1

    def __init__(
        self,
        detect_re: re.Pattern[str] | None,
        strip_re: re.Pattern[str] | None,
    ) -> None:
        self._detect_re = detect_re
        self._strip_re = strip_re
        self._retries = 0

    # -- construction --------------------------------------------------------

    @classmethod
    def from_tools(cls, tools: list[dict[str, Any]]) -> "LeakedToolGuard":
        names = _extract_tool_names(tools)
        return cls(
            detect_re=_build_detect_pattern(names),
            strip_re=_build_strip_pattern(names),
        )

    # -- public API ----------------------------------------------------------

    def has_leak(self, content: str) -> bool:
        """Return True if *content* contains leaked tool artifacts."""
        if _LEAKED_FUNC_PREFIX_RE.search(content):
            return True
        if _LEAKED_WIDGET_JSON_RE.search(content):
            return True
        if self._detect_re and self._detect_re.search(content):
            return True
        return False

    def should_retry(self, content: str | None) -> bool:
        """Check if content has a leak and a retry is still available."""
        return bool(
            content
            and self.has_leak(content)
            and self._retries < self._max_retries
        )

    def append_correction(self, messages: list[dict], content: str) -> None:
        """Append assistant + user correction messages and bump retry counter."""
        self._retries += 1
        logger.warning(
            "Leaked tool call detected in content (retry %s/%s)",
            self._retries,
            self._max_retries,
        )
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": _LEAKED_RETRY_CORRECTION})

    def finalize(self, content: str | None) -> str:
        """Return clean content, sanitizing any remaining leaked artifacts."""
        text = content or ""
        if text and self.has_leak(text):
            logger.warning("Sanitizing leaked tool artifacts from final content")
            text = _sanitize_content(text, self._strip_re)
        return text


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_tool_names(tools: list[dict[str, Any]]) -> list[str]:
    """Extract function names from OpenAI-compatible tool definitions."""
    names: list[str] = []
    for tool in tools:
        name = tool.get("function", {}).get("name")
        if name:
            names.append(name)
    return names


def _build_detect_pattern(tool_names: list[str]) -> re.Pattern[str] | None:
    if not tool_names:
        return None
    escaped = "|".join(re.escape(n) for n in tool_names)
    return re.compile(rf'(?:functions?\.)?\b(?:{escaped})\s*\(', re.IGNORECASE)


def _build_strip_pattern(tool_names: list[str]) -> re.Pattern[str] | None:
    if not tool_names:
        return None
    escaped = "|".join(re.escape(n) for n in tool_names)
    return re.compile(rf'(?:functions?\.)?\b(?:{escaped})\s*\(', re.IGNORECASE)


def _sanitize_content(content: str, strip_re: re.Pattern[str] | None = None) -> str:
    """Strip leaked tool-call / widget-JSON artifacts from content."""
    cleaned = content
    if strip_re:
        cleaned = _strip_balanced_blocks(cleaned, strip_re, open_index_from="end")
    cleaned = _strip_balanced_blocks(
        cleaned,
        _LEAKED_FUNC_PREFIX_RE,
        open_index_from="end",
    )
    cleaned = _strip_balanced_blocks(
        cleaned,
        _LEAKED_WIDGET_JSON_RE,
        open_index_from="start",
    )
    cleaned = _normalize_sanitized_text(cleaned)
    return cleaned


def _strip_balanced_blocks(
    content: str,
    start_re: re.Pattern[str],
    *,
    open_index_from: str,
) -> str:
    spans: list[tuple[int, int]] = []
    for match in start_re.finditer(content):
        start = match.start()
        open_index = start if open_index_from == "start" else match.end() - 1
        end = _find_balanced_end(content, open_index)
        spans.append((start, end))
    return _remove_spans(content, spans)


def _find_balanced_end(content: str, open_index: int) -> int:
    open_char = content[open_index]
    close_char = _BALANCED_PAIRS.get(open_char)
    if close_char is None:
        return open_index + 1

    stack = [close_char]
    in_string = False
    escape_next = False
    string_quote = ""

    for index in range(open_index + 1, len(content)):
        char = content[index]

        if in_string:
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == string_quote:
                in_string = False
            continue

        if char in ('"', "'"):
            in_string = True
            string_quote = char
            continue

        if char in _BALANCED_PAIRS:
            stack.append(_BALANCED_PAIRS[char])
            continue

        if stack and char == stack[-1]:
            stack.pop()
            if not stack:
                return index + 1

    return len(content)


def _remove_spans(content: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return content

    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        merged[-1] = (prev_start, max(prev_end, end))

    parts: list[str] = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            parts.append(content[cursor:start])
        cursor = max(cursor, end)
    if cursor < len(content):
        parts.append(content[cursor:])
    return "".join(parts)


def _normalize_sanitized_text(content: str) -> str:
    content = re.sub(r"[ \t]{2,}", " ", content)
    content = re.sub(r"[ \t]+\n", "\n", content)
    content = re.sub(r"\n[ \t]+", "\n", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()
