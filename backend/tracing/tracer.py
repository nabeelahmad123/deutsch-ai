"""Structured tracing for every tool call and agent decision.

CLAUDE.md non-negotiable principle #4: name, input, output, latency,
success/failure -- logged from day one, not bolted on later. JSON lines to start
(section 3); a Langfuse/OTel exporter can be added behind the same interface.

Day-1 status: the JSONL sink and the ``trace_tool_call`` context manager are
implemented; agent/MCP code will call into them as those layers land.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TRACE_PATH = Path(os.environ.get("TRACE_LOG_PATH", "./_traces/trace.jsonl"))


@dataclass
class TraceEvent:
    kind: str  # "tool_call" | "agent_decision" | "error"
    name: str
    trace_id: str
    input: Any = None
    output: Any = None
    latency_ms: float | None = None
    success: bool | None = None
    error: str | None = None
    ts: float = field(default_factory=time.time)


class Tracer:
    def __init__(self, path: Path | str = DEFAULT_TRACE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: TraceEvent) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(event), ensure_ascii=False, default=str) + "\n")

    @contextmanager
    def trace_tool_call(self, name: str, payload: Any) -> Iterator[dict]:
        trace_id = uuid.uuid4().hex
        started = time.perf_counter()
        box: dict[str, Any] = {"trace_id": trace_id, "output": None}
        try:
            yield box
        except Exception as exc:
            self.emit(
                TraceEvent(
                    kind="error",
                    name=name,
                    trace_id=trace_id,
                    input=payload,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    success=False,
                    error=repr(exc),
                )
            )
            raise
        else:
            self.emit(
                TraceEvent(
                    kind="tool_call",
                    name=name,
                    trace_id=trace_id,
                    input=payload,
                    output=box.get("output"),
                    latency_ms=(time.perf_counter() - started) * 1000,
                    success=True,
                )
            )


_default = Tracer()


def get_tracer() -> Tracer:
    return _default
