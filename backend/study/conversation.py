"""Conversational practice: a short German roleplay that forces the learner to
use their due / weak words in context, then feeds the outcomes back to the
deterministic scheduler.

The scheduler still picks *which* words (``compose_targets`` is just due + weak +
a little new). The LLM only runs the dialogue and judges, per turn, which target
words the learner used correctly -- a grading task, like ``grading.semantic_grade``.
Without credentials the tutor degrades to a clear placeholder and zero updates.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session as DbSession

from backend.core import read_models, scheduler
from backend.core.read_models import WordView
from backend.db.models import User

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_TARGET_COUNT = 8
MAX_TURN_TOKENS = 400

SCENARIOS = {
    "cafe": "ordering food and drink in a Berlin café",
    "directions": "asking a stranger for directions in a city",
    "shopping": "buying clothes in a shop and asking about size and price",
    "smalltalk": "small talk with a colleague about the weekend",
    "doctor": "describing symptoms to a doctor",
    "hotel": "checking in at a hotel and asking about breakfast",
}

_USED_LINE = re.compile(r"^\s*USED:\s*(.*)$", re.IGNORECASE | re.MULTILINE)

_SYSTEM = """\
You are a warm, patient German conversation tutor. Roleplay this scenario with \
the learner: {scenario}. Reply ONLY in German, 1-3 short sentences at CEFR level \
{level} or easier, and always end with a question that keeps the conversation \
going. Naturally create openings for the learner to use these target words: \
{targets}. Do not lecture or correct in English.

After your German reply, on a final separate line, write:
USED: <comma-separated target words from the list that the learner used \
correctly and meaningfully in their LAST message, or NONE>
"""


@dataclass(frozen=True)
class ConversationStart:
    session_id: int
    scenario: str
    level: str
    targets: list[WordView]
    opener: str


@dataclass(frozen=True)
class TutorReply:
    reply: str
    used_lemmas: list[str] = field(default_factory=list)
    available: bool = True  # False when the LLM path was unavailable


def _level_ceiling(session: DbSession, user_id: int) -> str:
    return str(scheduler.cefr_ceiling(session, user_id))


def compose_targets(
    session: DbSession, user_id: int, *, count: int = DEFAULT_TARGET_COUNT
) -> list[WordView]:
    """The words this practice session should exercise: due reviews first, then
    the learner's weakest words, then a few new words to fill. Deterministic."""
    from datetime import UTC, datetime

    n = max(3, min(count, 15))
    due = scheduler.words_due_for_review(session, user_id, datetime.now(UTC))
    weak = scheduler.weak_words(session, user_id, n)
    picked: list[int] = []
    for wid in [*due, *weak]:
        if wid not in picked:
            picked.append(wid)
        if len(picked) >= n:
            break
    if len(picked) < n:
        for wid in scheduler.select_new_words(session, user_id, None, n - len(picked)):
            if wid not in picked:
                picked.append(wid)
    return read_models.load_word_views(session, picked[:n])


def _client(client):
    if client is not None:
        return client
    from anthropic import Anthropic

    return Anthropic()


def _model() -> str:
    return os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL


def _split_used(text: str, target_lemmas: list[str]) -> tuple[str, list[str]]:
    match = _USED_LINE.search(text)
    if not match:
        return text.strip(), []
    reply = text[: match.start()].strip()
    raw = match.group(1).strip()
    if raw.upper() == "NONE" or not raw:
        return reply, []
    lower = {lemma.lower(): lemma for lemma in target_lemmas}
    used: list[str] = []
    for token in re.split(r"[,;]", raw):
        key = re.sub(r"^(der|die|das)\s+", "", token.strip().lower()).strip()
        if key in lower and lower[key] not in used:
            used.append(lower[key])
    return reply, used


def tutor_turn(
    scenario: str,
    level: str,
    targets: list[str],
    history: list[dict],
    user_message: str,
    *,
    client=None,
) -> TutorReply:
    """One dialogue turn. ``history`` is prior ``{"role","content"}`` messages
    (roles ``user`` / ``assistant``). Returns the tutor's German reply and the
    target lemmas the learner used correctly in ``user_message``."""
    try:
        api = _client(client)
        messages = list(history)
        if user_message:
            messages.append({"role": "user", "content": user_message})
        if not messages:
            messages = [{"role": "user", "content": "Hallo!"}]
        resp = api.messages.create(
            model=_model(),
            max_tokens=MAX_TURN_TOKENS,
            system=_SYSTEM.format(
                scenario=SCENARIOS.get(scenario, scenario),
                level=level,
                targets=", ".join(targets) or "(any useful words)",
            ),
            messages=messages,
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        reply, used = _split_used(text, targets)
        return TutorReply(reply or text.strip(), used, True)
    except Exception:  # noqa: BLE001 - graceful degradation, like semantic_grade
        return TutorReply(
            "Der Tutor ist gerade nicht verfügbar (kein API-Schlüssel). "
            "Die Übung läuft ohne Bewertung weiter.",
            [],
            False,
        )


def start_conversation(
    session: DbSession,
    user_id: int,
    scenario: str,
    minutes: int,
    *,
    client=None,
) -> ConversationStart:
    """Compose the target words, persist a ``sessions`` row, and generate the
    tutor's opening line. Raises ``LookupError`` for an unknown user."""
    if session.get(User, user_id) is None:
        raise LookupError(f"no user with id {user_id}")
    level = _level_ceiling(session, user_id)
    targets = compose_targets(session, user_id)
    plan = scheduler.create_learning_session(session, user_id, minutes, scenario)
    opener = tutor_turn(scenario, level, [w.lemma for w in targets], [], "", client=client).reply
    return ConversationStart(
        session_id=plan.session_id or 0,
        scenario=scenario,
        level=level,
        targets=targets,
        opener=opener,
    )


def finish_conversation(
    session: DbSession,
    session_id: int,
    user_id: int,
    used_word_ids: list[int],
    *,
    turns: int,
) -> dict:
    """Record a correct review for each target word the learner used, then close
    the session. Words never used are left untouched (no penalty)."""
    updated = 0
    for word_id in dict.fromkeys(used_word_ids):
        try:
            scheduler.update_after_review(session, user_id, word_id, True, 4000)
            updated += 1
        except LookupError:
            continue
    row = scheduler.finish_session(session, session_id, turns)
    return {
        "session_id": row.id,
        "turns": turns,
        "words_practised": updated,
    }
