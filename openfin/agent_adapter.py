from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from openfin.agent_store import AgentEvent, AgentStatus, Project


class AgentAdapter(Protocol):
    name: str

    def run_turn(
        self,
        *,
        project: Project,
        prompt: str,
        resume_id: str | None = None,
        model: str | None = None,
        system_context: str | None = None,
    ) -> Iterator[AgentEvent]: ...

    def interrupt(self) -> None: ...

    def status(self) -> AgentStatus: ...
