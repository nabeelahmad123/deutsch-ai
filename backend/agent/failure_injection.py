"""Deliberate fault injection for the agent (CLAUDE.md section 11).

A first-class deliverable. Three fault kinds:

  - ``timeout``            -- the tool call raises a timeout error (after an
                             optional, capped real delay). Never hangs forever.
  - ``malformed_response`` -- the tool "succeeds" but returns junk instead of
                             the real payload, so the agent has to notice.
  - ``ambiguous_request``  -- a request transformer, not a call-time fault:
                             strips concrete cues (minutes, topic) so the agent
                             must ask for clarification or fail gracefully.

``FaultInjectingClient`` wraps a tool client (``MCPToolClient`` /
``MultiServerToolClient``) with the same ``tool_specs()`` / ``call()`` interface,
so ``run_session`` / ``run_conversation`` don't know they're being sabotaged.
Every injected fault is traced (``fault.<kind>.<tool>``) and recorded on
``.injected`` for the recovery-rate report (LG-14).
"""

from __future__ import annotations

import enum
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.agent.mcp_client import MCPToolError
from backend.tracing.tracer import TraceEvent, Tracer, get_tracer

# Hard ceiling on any real sleep a timeout fault does -- we simulate slowness,
# we don't actually block the suite.
MAX_REAL_DELAY_SECONDS = 0.5

MALFORMED_PAYLOAD: dict = {
    "__malformed__": True,
    "note": "injected malformed MCP response",
    "partial": '{"session_id": 1, "review_wor',
}


class FaultKind(enum.StrEnum):
    timeout = "timeout"
    malformed_response = "malformed_response"
    ambiguous_request = "ambiguous_request"


@dataclass
class FaultSpec:
    kind: FaultKind
    target_tool: str | None = None  # None = any tool
    probability: float = 1.0
    delay_seconds: float = 0.0  # timeout only: how slow to look before failing
    max_fires: int | None = None  # stop injecting after N hits (None = unlimited)
    _fires: int = field(default=0, repr=False)

    def matches(self, tool: str) -> bool:
        if self.kind is FaultKind.ambiguous_request:
            return False  # handled by ``ambiguate``, not at call time
        if self.target_tool is not None and self.target_tool != tool:
            return False
        return self.max_fires is None or self._fires < self.max_fires


def _select(specs: list[FaultSpec], tool: str, rng: random.Random) -> FaultSpec | None:
    for spec in specs:
        if spec.matches(tool) and rng.random() < spec.probability:
            spec._fires += 1
            return spec
    return None


def _apply_fault(name: str, fault: FaultSpec, call_fn, arguments) -> Any:
    if fault.kind is FaultKind.timeout:
        if fault.delay_seconds:
            time.sleep(min(fault.delay_seconds, MAX_REAL_DELAY_SECONDS))
        raise MCPToolError(
            name, f"tool call '{name}' timed out after {fault.delay_seconds or 30}s (injected)"
        )
    if fault.kind is FaultKind.malformed_response:
        return dict(MALFORMED_PAYLOAD)
    return call_fn(name, arguments)  # unreachable: ambiguous_request never matches


def wrap_tool(
    call_fn,
    specs: list[FaultSpec],
    *,
    rng: random.Random | None = None,
    on_inject=None,
    tracer: Tracer | None = None,
):
    """Wrap a ``call(name, arguments)`` callable so it may inject a fault first.

    ``on_inject(tool, spec)`` fires whenever a fault does. If ``tracer`` is given,
    an injected call still produces an ``agent.tool_call.<name>`` trace event
    (error for a timeout, ok-with-junk for a malformed response), so
    tool-call-success maths counts the sabotaged attempt.
    """
    rng = rng or random.Random()
    active = list(specs)

    def wrapped(name: str, arguments: dict | None = None) -> Any:
        fault = _select(active, name, rng)
        if fault is None:
            return call_fn(name, arguments)  # inner client traces this itself
        if on_inject is not None:
            on_inject(name, fault)
        if tracer is None:
            return _apply_fault(name, fault, call_fn, arguments)
        with tracer.trace_tool_call(f"agent.tool_call.{name}", arguments or {}) as box:
            result = _apply_fault(name, fault, call_fn, arguments)
            box["output"] = "<injected malformed response>"
            return result

    return wrapped


class FaultInjectingClient:
    """A tool client that sabotages calls per the given ``FaultSpec``s."""

    def __init__(
        self,
        inner,
        specs: list[FaultSpec],
        *,
        seed: int = 0,
        tracer: Tracer | None = None,
    ) -> None:
        self._inner = inner
        self._tracer = tracer or get_tracer()
        self.injected: list[dict] = []
        self._call = wrap_tool(
            inner.call,
            specs,
            rng=random.Random(seed),
            on_inject=self._record,
            tracer=self._tracer,
        )

    # -- same interface as MCPToolClient / MultiServerToolClient --------------
    def tool_specs(self) -> list[dict]:
        return self._inner.tool_specs()

    def server_for(self, name: str) -> str | None:
        fn = getattr(self._inner, "server_for", None)
        return fn(name) if fn else None

    def call(self, name: str, arguments: dict | None = None) -> Any:
        return self._call(name, arguments)

    # -- fault bookkeeping ------------------------------------------------
    def _record(self, tool: str, spec: FaultSpec) -> None:
        entry = {"tool": tool, "kind": str(spec.kind), "fire": spec._fires}
        self.injected.append(entry)
        self._tracer.emit(
            TraceEvent(
                kind="fault_injected",
                name=f"fault.{spec.kind}.{tool}",
                trace_id=uuid.uuid4().hex,
                input={
                    "tool": tool,
                    "spec": {"kind": str(spec.kind), "probability": spec.probability},
                },
                success=True,
            )
        )


# --- ambiguous request simulation ----------------------------------------

AMBIGUOUS_REQUESTS: tuple[str, ...] = (
    "I want to practise German",
    "help me study",
    "let's do some vocab",
    "German session please",
    "quiz me",
)

_MINUTES_RE = re.compile(r"\b(?:a |about |around )?\d+\s*(?:mins?|minutes?|hours?|hrs?)\b", re.I)
_TOPIC_RE = re.compile(r"\bfor (?:work|travel|exam|business|holiday|my trip|a trip)\b", re.I)


def ambiguate(text: str) -> str:
    """Strip concrete cues (a time budget, a topic) from a request."""
    stripped = _TOPIC_RE.sub("", _MINUTES_RE.sub("some time", text)).strip()
    stripped = re.sub(r"\s{2,}", " ", stripped).rstrip(",. ")
    return stripped or "let's do some German"
