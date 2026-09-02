"""Deliberate fault injection for the agent (CLAUDE.md section 11).

A first-class deliverable, not an "if time allows" edge case. Can deliberately:
  - time out a tool call
  - return a malformed / unexpected MCP response
  - simulate an ambiguous user request

For each, the agent's recovery (retry / fallback / ask for clarification / fail
gracefully -- never silently hang or crash) is traced and a tool-call
success/recovery rate is reported.

Day-1 status: stub. This is build-order step 6.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class FaultKind(enum.StrEnum):
    timeout = "timeout"
    malformed_response = "malformed_response"
    ambiguous_request = "ambiguous_request"


@dataclass
class FaultSpec:
    kind: FaultKind
    target_tool: str | None = None
    probability: float = 1.0


def wrap_tool(tool, spec: FaultSpec):
    """Return a wrapper around ``tool`` that injects ``spec`` before delegating."""
    raise NotImplementedError("failure injection lands in build-order step 6")
