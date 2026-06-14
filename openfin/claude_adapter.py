from __future__ import annotations

import json
import signal
import subprocess
from collections.abc import Callable, Iterator
from typing import Any

from openfin.agent_store import AgentEvent, AgentStatus, Project, utc_now


PopenFactory = Callable[..., Any]


class ClaudeAdapter:
    name = "claude"

    def __init__(
        self,
        *,
        executable: str = "claude",
        popen: PopenFactory | None = None,
    ) -> None:
        self.executable = executable
        self._popen = popen or subprocess.Popen
        self._process: Any | None = None
        self._status: AgentStatus = "idle"
        self.native_session_id: str | None = None

    def build_command(
        self,
        *,
        project: Project,
        prompt: str,
        resume_id: str | None = None,
        model: str | None = None,
        system_context: str | None = None,
    ) -> list[str]:
        del project
        command = [self.executable, "-p", "--output-format", "stream-json"]
        if resume_id:
            command.extend(["--resume", resume_id])
        if model:
            command.extend(["--model", model])
        if system_context:
            command.extend(["--append-system-prompt", system_context])
        command.append(prompt)
        return command

    def run_turn(
        self,
        *,
        project: Project,
        prompt: str,
        resume_id: str | None = None,
        model: str | None = None,
        system_context: str | None = None,
    ) -> Iterator[AgentEvent]:
        command = self.build_command(
            project=project,
            prompt=prompt,
            resume_id=resume_id,
            model=model,
            system_context=system_context,
        )
        self._status = "busy"
        had_error = False
        process = self._popen(
            command,
            cwd=str(project.root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._process = process
        stdout = process.stdout or []
        for raw_line in stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                had_error = True
                yield AgentEvent(
                    kind="error",
                    text=f"invalid Claude JSON: {line}",
                    raw={"line": line},
                    ts=utc_now(),
                    session_id=self.native_session_id or "",
                )
                continue
            event = normalize_claude_event(payload)
            if event.session_id:
                self.native_session_id = event.session_id
            yield event

        returncode = process.wait()
        stderr_text = process.stderr.read().strip() if process.stderr else ""
        self._process = None
        if returncode != 0:
            had_error = True
            yield AgentEvent(
                kind="error",
                text=stderr_text or f"Claude exited with status {returncode}",
                raw={"returncode": returncode, "stderr": stderr_text},
                ts=utc_now(),
                session_id=self.native_session_id or "",
            )
        self._status = "error" if had_error else "idle"

    def interrupt(self) -> None:
        if self._process is not None:
            self._process.send_signal(signal.SIGINT)

    def status(self) -> AgentStatus:
        return self._status


def normalize_claude_event(payload: dict[str, Any]) -> AgentEvent:
    event_type = str(payload.get("type") or payload.get("event") or "progress")
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "")
    if event_type == "assistant":
        kind = "assistant_text"
        text = extract_text(payload)
    elif event_type == "tool_use":
        kind = "tool_use"
        name = payload.get("name") or payload.get("tool_name") or "tool"
        text = f"Tool use: {name}"
    elif event_type == "tool_result":
        kind = "tool_result"
        text = extract_text(payload) or "Tool result"
    elif event_type == "result":
        kind = "turn_done"
        text = extract_text(payload) or str(payload.get("result") or "")
    elif event_type == "needs_input":
        kind = "needs_input"
        text = extract_text(payload)
    elif event_type == "error":
        kind = "error"
        text = extract_text(payload) or str(payload.get("error") or "Claude error")
    else:
        kind = "progress"
        text = extract_text(payload) or event_type
    return AgentEvent(
        kind=kind,
        text=text,
        raw=payload,
        ts=utc_now(),
        session_id=session_id,
    )


def extract_text(payload: dict[str, Any]) -> str:
    for key in ("text", "result", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
    content = payload.get("content")
    if isinstance(content, str):
        return content
    return ""
