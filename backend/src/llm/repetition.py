"""Detection of degenerate repetition in streamed model output.

Some models, especially with greedy decoding (temperature 0), can fall into a loop and
repeat the same short sequence ("473938473938…") until ``max_tokens``. Without a guard
such a loop streams for minutes and keeps the upstream LLM busy.
"""

from __future__ import annotations

# Shortest repeated run (in characters) treated as a loop; long enough that a markdown
# rule ("------") or a table separator never qualifies.
MIN_REPEATED_CHARS = 400
# Longest repeated unit looked for.
MAX_PERIOD = 80


def repeated_tail_start(
    text: str,
    *,
    min_chars: int = MIN_REPEATED_CHARS,
    max_period: int = MAX_PERIOD,
) -> int | None:
    """Start of a run of one unit repeated at the end of ``text``, or None.

    The last ``min_chars`` characters must be one unit of at most ``max_period``
    characters repeated; the run is then extended backwards as far as it goes.
    """
    if len(text) < min_chars:
        return None
    tail = text[-min_chars:]
    for period in range(1, max_period + 1):
        if tail[period:] == tail[:-period]:
            start = len(text) - min_chars
            while start > 0 and text[start - 1] == text[start - 1 + period]:
                start -= 1
            return start
    return None
