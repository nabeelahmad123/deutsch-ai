"""A scripted stand-in for anthropic.Anthropic -- deterministic, no network.

Build responses with ``text_block`` / ``tool_use`` / ``response`` and hand a
list to ``FakeLLM``; each ``messages.create(...)`` returns the next one and
records the call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    name: str
    input: dict
    id: str
    type: str = "tool_use"


@dataclass
class FakeResponse:
    content: list[Any]
    stop_reason: str = "end_turn"


def text_block(text: str) -> TextBlock:
    return TextBlock(text=text)


def tool_use(name: str, tool_input: dict, tool_id: str | None = None) -> ToolUseBlock:
    return ToolUseBlock(name=name, input=tool_input, id=tool_id or f"tu_{name}")


def response(*blocks: Any, stop_reason: str = "end_turn") -> FakeResponse:
    has_tool = any(getattr(b, "type", None) == "tool_use" for b in blocks)
    return FakeResponse(list(blocks), stop_reason="tool_use" if has_tool else stop_reason)


@dataclass
class _Messages:
    script: list[FakeResponse]
    calls: list[dict] = field(default_factory=list)

    def create(self, **kwargs) -> FakeResponse:
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self.script.pop(0)


class FakeLLM:
    def __init__(self, script: list[FakeResponse]) -> None:
        self.messages = _Messages(list(script))

    @property
    def calls(self) -> list[dict]:
        return self.messages.calls
