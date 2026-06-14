from __future__ import annotations

import io
import signal
from pathlib import Path

from openfin.agent_store import Project
from openfin.claude_adapter import ClaudeAdapter, normalize_claude_event


class FakeProcess:
    def __init__(self, lines: list[str], returncode: int = 0, stderr: str = "") -> None:
        self.stdout = io.StringIO("\n".join(lines) + "\n")
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode
        self.signals: list[int] = []

    def wait(self) -> int:
        return self.returncode

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)


def test_claude_command_uses_headless_json_and_safe_options(tmp_path: Path) -> None:
    adapter = ClaudeAdapter(executable="claude")
    project = Project(name="OpenFin", root=tmp_path, profile="code")

    command = adapter.build_command(
        project=project,
        prompt="ship it",
        resume_id="native-123",
        model="sonnet",
        system_context="OpenFin context",
    )

    assert command == [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--resume",
        "native-123",
        "--model",
        "sonnet",
        "--append-system-prompt",
        "OpenFin context",
        "ship it",
    ]


def test_claude_event_normalization_handles_text_tool_and_result() -> None:
    assistant = normalize_claude_event(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello"}]},
            "session_id": "native-1",
        }
    )
    tool = normalize_claude_event(
        {"type": "tool_use", "name": "Read", "input": {"file_path": "README.md"}}
    )
    result = normalize_claude_event(
        {"type": "result", "result": "Done", "session_id": "native-2"}
    )

    assert assistant.kind == "assistant_text"
    assert assistant.text == "Hello"
    assert assistant.session_id == "native-1"
    assert tool.kind == "tool_use"
    assert "Read" in tool.text
    assert result.kind == "turn_done"
    assert result.text == "Done"
    assert result.session_id == "native-2"


def test_claude_adapter_streams_events_and_captures_session_id(tmp_path: Path) -> None:
    process = FakeProcess(
        [
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Working"}]}}',
            '{"type":"result","result":"Finished","session_id":"native-abc"}',
        ]
    )
    calls: list[tuple[list[str], Path]] = []

    def fake_popen(command, *, cwd, text, stdout, stderr):
        calls.append((command, Path(cwd)))
        return process

    adapter = ClaudeAdapter(executable="claude", popen=fake_popen)
    project = Project(name="OpenFin", root=tmp_path)

    events = list(adapter.run_turn(project=project, prompt="hello"))

    assert [event.kind for event in events] == ["assistant_text", "turn_done"]
    assert events[-1].session_id == "native-abc"
    assert adapter.native_session_id == "native-abc"
    assert calls[0][1] == tmp_path
    assert adapter.status() == "idle"


def test_claude_adapter_emits_error_on_bad_json_and_failed_exit(tmp_path: Path) -> None:
    process = FakeProcess(["not json"], returncode=2, stderr="boom")
    adapter = ClaudeAdapter(
        executable="claude",
        popen=lambda command, *, cwd, text, stdout, stderr: process,
    )

    events = list(
        adapter.run_turn(project=Project(name="OpenFin", root=tmp_path), prompt="hi")
    )

    assert events[0].kind == "error"
    assert "invalid Claude JSON" in events[0].text
    assert events[-1].kind == "error"
    assert "boom" in events[-1].text
    assert adapter.status() == "error"


def test_claude_adapter_interrupt_sends_sigint(tmp_path: Path) -> None:
    process = FakeProcess([])
    adapter = ClaudeAdapter(
        executable="claude",
        popen=lambda command, *, cwd, text, stdout, stderr: process,
    )
    adapter._process = process

    adapter.interrupt()

    assert process.signals == [signal.SIGINT]
