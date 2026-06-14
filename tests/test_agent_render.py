from __future__ import annotations

from openfin.agent_render import render_agent_event
from openfin.agent_store import AgentEvent, utc_now


def event(kind: str, text: str) -> AgentEvent:
    return AgentEvent(
        kind=kind,
        text=text,
        raw={},
        ts=utc_now(),
        session_id="native-1",
    )


def test_render_agent_event_suppresses_completion_fillers() -> None:
    assert render_agent_event(event("turn_done", "done.")) == ""
    assert render_agent_event(event("turn_done", "Done")) == ""


def test_render_agent_event_suppresses_duplicate_final_results() -> None:
    rendered = render_agent_event(
        event("turn_done", "Final answer"),
        assistant_texts=["Final answer"],
    )

    assert rendered == ""


def test_render_agent_event_keeps_result_only_answers() -> None:
    rendered = render_agent_event(event("turn_done", "Final answer"))

    assert rendered == "Final answer"


def test_render_agent_event_keeps_regular_user_visible_events() -> None:
    assert render_agent_event(event("assistant_text", "Hello")) == "Hello"
    assert render_agent_event(event("error", "boom")) == "error: boom"
