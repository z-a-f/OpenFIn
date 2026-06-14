from __future__ import annotations

from collections.abc import Iterable

from openfin.agent_store import AgentEvent


COMPLETION_FILLERS = {
    "done",
    "done.",
    "complete",
    "complete.",
    "completed",
    "completed.",
    "finished",
    "finished.",
}


def render_agent_event(
    event: AgentEvent,
    *,
    assistant_texts: Iterable[str] = (),
) -> str:
    if event.kind == "assistant_text":
        return event.text
    if event.kind == "tool_use":
        return event.text
    if event.kind == "tool_result":
        return event.text
    if event.kind == "needs_input":
        return event.text
    if event.kind == "error":
        return f"error: {event.text}"
    if event.kind == "turn_done":
        if is_completion_echo(event.text, assistant_texts):
            return ""
        return event.text
    if event.kind == "progress":
        return event.text
    return event.text


def is_completion_echo(text: str, assistant_texts: Iterable[str] = ()) -> bool:
    normalized = normalize_display_text(text)
    if not normalized:
        return True
    if normalized in COMPLETION_FILLERS:
        return True
    assistant_texts = list(assistant_texts)
    normalized_assistant_texts = [
        normalize_display_text(assistant_text)
        for assistant_text in assistant_texts
        if normalize_display_text(assistant_text)
    ]
    if normalized in normalized_assistant_texts:
        return True
    return normalized == normalize_display_text("\n".join(assistant_texts))


def normalize_display_text(text: str) -> str:
    return " ".join(text.split()).casefold()
