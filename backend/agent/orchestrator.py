"""Agent tool-calling loop against the Anthropic API.

The agent does ONE piece of natural-language reasoning -- turning a request like
"I have 10 minutes, German for work" into a time budget + topic -- and then calls
MCP server #1 tools to compose the session. It never picks words or computes
intervals itself (a core design rule).

Every LLM turn is traced as an ``agent_decision`` and every tool call is traced
by ``MCPToolClient`` .

``run_session`` runs the LLM loop: parse intent -> compose the session -> build
the quiz. Answers then come in one at a time through ``LearningSession.answer``
(a fixed evaluate_answer -> update_learning_state sequence -- no LLM turn), and
``LearningSession.summary`` closes the session out. ``start_session`` wires the
two together.
"""

from __future__ import annotations

import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.agent.mcp_client import MCPToolClient, MCPToolError
from backend.tracing.tracer import TraceEvent, Tracer, get_tracer


def _resolve_transient() -> tuple[type[BaseException], ...]:
    """Anthropic error types worth retrying: rate limits, 5xx, dropped
    connections. Empty when the SDK isn't installed (scripted-LLM tests)."""
    try:
        import anthropic
    except ImportError:  # pragma: no cover - agent extra always present in CI
        return ()
    return (
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.InternalServerError,
    )


_TRANSIENT_EXC: tuple[type[BaseException], ...] = _resolve_transient()
_RETRY_ATTEMPTS = 3


def _create_message(llm, **kwargs):
    """``llm.messages.create`` with bounded exponential backoff on transient
    API failures. A scripted FakeLLM never raises these, so this is a no-op
    there."""
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            return llm.messages.create(**kwargs)
        except _TRANSIENT_EXC:
            if attempt == _RETRY_ATTEMPTS:
                raise
            time.sleep(min(2**attempt, 8) * (0.5 + random.random()))


DEFAULT_MODEL = "claude-opus-5"
MAX_TURNS = 8
# The loop only needs room for a sentence of reasoning + a few tool calls per
# turn; a tight cap keeps a runaway turn cheap.
MAX_TOKENS = 1200

SYSTEM = """\
You plan a single German vocabulary study session for learner user_id={user_id}.

1. Read the learner's request and work out two things. This is the only
   judgement you make:
   - minutes: an integer. If the request names a duration, use it. If it does
     NOT ("brush up before my trip", "help me with German"), default to 10.
     Never skip composing a session just because no duration was given.
   - topic: an optional subject filter, one of exactly: work, travel, transport,
     food, home, health, body, education, nature, family, money, time,
     communication, clothing. Use null unless the request clearly matches one.
     "exam prep", "general practice" and vague requests have NO topic (null) --
     do not guess "work".
2. Call get_user_profile first to see where the learner stands (and optionally
   get_words_due_for_review / get_weak_words / get_new_words).
3. Call create_learning_session exactly once, passing the minutes and topic you
   inferred. The deterministic scheduler decides which words -- never choose,
   reorder, or invent vocabulary yourself, and never compute review dates.
4. Then call create_quiz once, passing every word id from the session (review
   words then new words) and a quiz_type ("en_to_de" unless the request implies
   another). Do NOT call evaluate_answer or update_learning_state -- answers are
   graded outside this loop.

After create_quiz returns, tell the learner in one sentence what the session
holds, and stop.
"""
QUIZ_TYPES = ("en_to_de", "de_to_en", "multiple_choice", "article")
DEFAULT_QUIZ_TYPE = "en_to_de"


@dataclass
class SessionRequest:
    raw_text: str
    user_id: int


@dataclass
class SessionResult:
    stopped: str  # "completed" | "no_session" | "max_turns" | "refusal"
    intent: dict = field(default_factory=dict)  # {minutes_available, topic}
    session_id: int | None = None
    review_words: list[dict] = field(default_factory=list)
    new_words: list[dict] = field(default_factory=list)
    quiz: list[dict] = field(default_factory=list)  # QuizQuestion dicts
    tool_calls: list[str] = field(default_factory=list)
    turns: int = 0
    reply: str = ""


@dataclass
class AnswerFeedback:
    question_id: str
    word_id: int
    correct: bool
    score: float
    rationale: str
    expected: str
    method: str
    new_state: dict = field(default_factory=dict)  # CardStateView after the update


class MissingAPIKey(RuntimeError):
    """Raised when the agent is run without Anthropic credentials configured.

    The deterministic core, the MCP servers and the study API all run without a
    key -- only the agent's tool-calling loop needs one.
    """


def _anthropic_client():
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise MissingAPIKey(
            "the agent needs an Anthropic API key: set ANTHROPIC_API_KEY in your "
            "environment (or a .env file) and re-run. Everything else in this "
            "project -- the scheduler, both MCP servers, the study API and its "
            "frontend -- runs without one."
        )
    from anthropic import Anthropic

    return Anthropic()  # resolves ANTHROPIC_API_KEY / auth profile


def _blocks_to_dicts(content: Any) -> list[dict]:
    out: list[dict] = []
    for block in content:
        kind = getattr(block, "type", None)
        if kind == "text":
            out.append({"type": "text", "text": block.text})
        elif kind == "tool_use":
            out.append(
                {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
            )
    return out


@dataclass
class LoopOutcome:
    stopped: str  # "completed" | "max_turns" | "refusal"
    turns: int
    reply: str
    tool_calls: list[str] = field(default_factory=list)


def _run_loop(
    *,
    system: str,
    user_text: str,
    mcp,
    llm,
    model: str,
    tracer: Tracer,
    max_turns: int,
    on_tool: Any = None,  # Callable[[name, args, payload|None], None]
) -> LoopOutcome:
    """The shared Anthropic tool-use loop: one agent_decision trace per turn,
    tool errors fed back as is_error results (never raised). ``on_tool`` is
    called for each executed tool (payload is None on a tool error)."""
    tools = mcp.tool_specs()
    messages: list[dict] = [{"role": "user", "content": user_text}]
    out = LoopOutcome(stopped="max_turns", turns=0, reply="")

    for turn in range(1, max_turns + 1):
        out.turns = turn
        response = _create_message(
            llm,
            model=model,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools,
            messages=messages,
        )
        blocks = list(response.content)
        text = " ".join(b.text for b in blocks if getattr(b, "type", None) == "text").strip()
        tool_uses = [b for b in blocks if getattr(b, "type", None) == "tool_use"]

        tracer.emit(
            TraceEvent(
                kind="agent_decision",
                name="agent.turn",
                trace_id=uuid.uuid4().hex,
                input={"turn": turn, "request": user_text},
                output={
                    "stop_reason": response.stop_reason,
                    "text": text[:400],
                    "tools_requested": [b.name for b in tool_uses],
                },
                success=True,
            )
        )
        messages.append({"role": "assistant", "content": _blocks_to_dicts(blocks)})
        if text:
            out.reply = text

        if response.stop_reason == "refusal":
            out.stopped = "refusal"
            return out
        if not tool_uses:
            out.stopped = "completed"
            return out

        results: list[dict] = []
        for block in tool_uses:
            out.tool_calls.append(block.name)
            try:
                payload = mcp.call(block.name, block.input or {})
                if on_tool is not None:
                    on_tool(block.name, block.input or {}, payload)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(payload, default=str),
                    }
                )
            except MCPToolError as exc:
                if on_tool is not None:
                    on_tool(block.name, block.input or {}, None)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "is_error": True,
                        "content": exc.message,
                    }
                )
        messages.append({"role": "user", "content": results})

    return out


def run_session(
    request: SessionRequest,
    *,
    mcp_client: MCPToolClient | None = None,
    llm_client=None,
    tracer: Tracer | None = None,
    model: str | None = None,
) -> SessionResult:
    """Run the intent->tools loop and return the composed session."""
    tracer = tracer or get_tracer()
    mcp = mcp_client or MCPToolClient(tracer=tracer)
    llm = llm_client or _anthropic_client()
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    result = SessionResult(stopped="max_turns")
    session_payload: dict | None = None

    def on_tool(name: str, args: dict, payload: Any) -> None:
        nonlocal session_payload
        if name == "create_learning_session":
            session_payload = payload if isinstance(payload, dict) else None
            result.intent = {
                "minutes_available": args.get("minutes_available"),
                "topic": args.get("topic"),
            }
        elif name == "create_quiz" and isinstance(payload, list):
            result.quiz = payload

    outcome = _run_loop(
        system=SYSTEM.format(user_id=request.user_id),
        user_text=request.raw_text,
        mcp=mcp,
        llm=llm,
        model=model,
        tracer=tracer,
        max_turns=MAX_TURNS,
        on_tool=on_tool,
    )
    result.turns = outcome.turns
    result.reply = outcome.reply
    result.tool_calls = outcome.tool_calls
    result.stopped = outcome.stopped
    if outcome.stopped == "completed" and session_payload is None:
        result.stopped = "no_session"

    if session_payload is not None:
        result.session_id = session_payload.get("session_id")
        result.review_words = session_payload.get("review_words", [])
        result.new_words = session_payload.get("new_words", [])

    return result


def grade_answer(
    mcp: MCPToolClient, *, user_id: int, question_id: str, user_answer: str
) -> AnswerFeedback:
    """Grade one answer and apply it: evaluate_answer then update_learning_state.

    No LLM turn -- the semantic grading (if any) happens inside evaluate_answer.
    Both tool calls are traced by ``mcp``.
    """
    ev = mcp.call("evaluate_answer", {"question_id": question_id, "user_answer": user_answer})
    state = mcp.call(
        "update_learning_state",
        {"user_id": user_id, "word_id": ev["word_id"], "correct": ev["correct"]},
    )
    return AnswerFeedback(
        question_id=ev["question_id"],
        word_id=ev["word_id"],
        correct=ev["correct"],
        score=ev["score"],
        rationale=ev["rationale"],
        expected=ev["expected"],
        method=ev["method"],
        new_state=state if isinstance(state, dict) else {},
    )


@dataclass
class LearningSession:
    """A composed session you can answer question-by-question, then summarise."""

    user_id: int
    session_id: int | None
    quiz: list[dict]
    result: SessionResult
    _mcp: MCPToolClient
    feedback: list[AnswerFeedback] = field(default_factory=list)

    def answer(self, question_id: str, user_answer: str) -> AnswerFeedback:
        fb = grade_answer(
            self._mcp, user_id=self.user_id, question_id=question_id, user_answer=user_answer
        )
        self.feedback.append(fb)
        return fb

    def summary(self) -> dict:
        answered = len(self.feedback)
        correct = sum(1 for f in self.feedback if f.correct)
        closed = {}
        if self.session_id is not None:
            closed = self._mcp.call(
                "finish_learning_session",
                {"session_id": self.session_id, "words_covered": answered},
            )
        return {
            "session_id": self.session_id,
            "answered": answered,
            "correct": correct,
            "accuracy": round(correct / answered, 3) if answered else None,
            "topic": self.result.intent.get("topic"),
            "minutes_available": self.result.intent.get("minutes_available"),
            "session_row": closed,
        }


def start_session(
    request: SessionRequest,
    *,
    mcp_client: MCPToolClient | None = None,
    llm_client=None,
    tracer: Tracer | None = None,
    model: str | None = None,
) -> LearningSession:
    """Run the planning loop and hand back an answerable session."""
    tracer = tracer or get_tracer()
    mcp = mcp_client or MCPToolClient(tracer=tracer)
    result = run_session(request, mcp_client=mcp, llm_client=llm_client, tracer=tracer, model=model)
    return LearningSession(
        user_id=request.user_id,
        session_id=result.session_id,
        quiz=result.quiz,
        result=result,
        _mcp=mcp,
    )


# --- cross-server orchestration -------------------------------------

CONVERSATION_MAX_TURNS = 10

CONVERSATION_SYSTEM = """\
You help a German learner (user_id={user_id}). Two independent tool surfaces:

- LEARNING tools (get_user_profile, get_words_due_for_review, get_weak_words,
  get_new_words, create_learning_session, create_quiz, finish_learning_session,
  ...): a deterministic spaced-repetition core. Never pick, reorder or invent
  vocabulary yourself; never compute review dates.
- NOTES tools (write_note, append_note, read_note, list_notes, log_progress): a
  Markdown vault for recording things. log_progress appends a dated section to
  progress.md.

Do what the learner asks with the fewest tool calls. When they ask you to
record / log / note / summarise progress, first gather the facts with the
learning tools, then write them with log_progress (or a note). Reply in one or
two sentences when done.
"""


@dataclass
class ConversationResult:
    stopped: str  # "completed" | "max_turns" | "refusal"
    turns: int
    reply: str
    tool_calls: list[str] = field(default_factory=list)
    servers_used: list[str] = field(default_factory=list)  # e.g. ["learning", "notes"]


def run_conversation(
    request: SessionRequest,
    *,
    mcp_client=None,
    llm_client=None,
    tracer: Tracer | None = None,
    model: str | None = None,
) -> ConversationResult:
    """A single conversation that may span both MCP servers.

    Default ``mcp_client`` exposes learning + notes tools together; the trace
    shows which server each call went to.
    """
    from backend.agent.mcp_client import build_default_clients

    tracer = tracer or get_tracer()
    mcp = mcp_client or build_default_clients(tracer=tracer)
    llm = llm_client or _anthropic_client()
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    used: set[str] = set()

    def on_tool(name: str, _args: dict, _payload: Any) -> None:
        server = getattr(mcp, "server_for", lambda _n: None)(name)
        if server:
            used.add(server)

    outcome = _run_loop(
        system=CONVERSATION_SYSTEM.format(user_id=request.user_id),
        user_text=request.raw_text,
        mcp=mcp,
        llm=llm,
        model=model,
        tracer=tracer,
        max_turns=CONVERSATION_MAX_TURNS,
        on_tool=on_tool,
    )
    return ConversationResult(
        stopped=outcome.stopped,
        turns=outcome.turns,
        reply=outcome.reply,
        tool_calls=outcome.tool_calls,
        servers_used=sorted(used),
    )
