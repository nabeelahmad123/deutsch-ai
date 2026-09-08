"""Structured tracing for every tool call and agent decision.

Each event records name, input, output, latency and success/failure, as JSON
lines. A Langfuse/OTel exporter could sit behind the same interface later.

The MCP servers wrap every tool and resource read with ``trace_tool_call``; the
orchestrator adds an ``agent_decision`` event per LLM turn.
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

DEFAULT_TRACE_PATH = "./_traces/trace.jsonl"


def _resolve_path(path: Path | str | None) -> Path:
    return Path(path or os.environ.get("TRACE_LOG_PATH") or DEFAULT_TRACE_PATH)


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
    def __init__(self, path: Path | str | None = None) -> None:
        # Resolved at construction, not import (so tests can point TRACE_LOG_PATH
        # somewhere harmless). The directory is created on first write.
        self.path = _resolve_path(path)

    def emit(self, event: TraceEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
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


_default: Tracer | None = None


def get_tracer() -> Tracer:
    """Process-wide tracer, created lazily on first use."""
    global _default
    if _default is None:
        _default = Tracer()
    return _default
