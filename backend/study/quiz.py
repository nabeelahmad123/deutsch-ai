"""Quiz question construction + self-contained question ids.

``create_quiz`` builds questions; ``evaluate_answer`` grades them. There is no
server-side question store -- the ``question_id`` carries everything grading
needs (word id, quiz type, reference answer, prompt), base64url-encoded. It is
opaque to the agent, not secret.
"""

from __future__ import annotations

import base64
import binascii
import json
import random
from dataclasses import dataclass

from backend.core.read_models import WordView

QUIZ_TYPES: tuple[str, ...] = ("en_to_de", "de_to_en", "multiple_choice", "article")
_QID_PREFIX = "q1:"


@dataclass(frozen=True)
class QuizQuestion:
    question_id: str
    word_id: int
    quiz_type: str
    prompt: str
    options: list[str] | None
    hint: str | None


def encode_qid(spec: dict) -> str:
    raw = json.dumps(spec, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    return _QID_PREFIX + base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_qid(question_id: str) -> dict:
    if not question_id.startswith(_QID_PREFIX):
        raise ValueError("unrecognised question_id")
    try:
        payload = base64.urlsafe_b64decode(question_id[len(_QID_PREFIX) :])
        return json.loads(payload)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("corrupt question_id") from exc


def _deterministic_shuffle(items: list[str], seed: int) -> list[str]:
    out = list(items)
    random.Random(seed).shuffle(out)
    return out


def build_question(
    word: WordView, quiz_type: str, distractors: list[str] | None = None
) -> QuizQuestion | None:
    """Return a question, or None when the word cannot support the type
    (e.g. ``article`` for a non-noun)."""
    if quiz_type not in QUIZ_TYPES:
        raise ValueError(f"unknown quiz_type {quiz_type!r}")

    options: list[str] | None = None
    if quiz_type == "article":
        if not word.article:
            return None
        reference = word.article
        prompt = f"Which article completes: ___ {word.lemma}? ({word.translation_en})"
        options = ["der", "die", "das"]
        hint = word.cefr_level
    elif quiz_type == "en_to_de":
        reference = word.lemma
        prompt = f"Translate to German: {word.translation_en}"
        hint = f"{word.cefr_level}, starts with '{word.lemma[:1]}'"
    elif quiz_type == "de_to_en":
        reference = word.translation_en
        shown = f"{word.article} {word.lemma}" if word.article else word.lemma
        prompt = f"Translate to English: {shown}"
        hint = word.cefr_level
    else:  # multiple_choice
        reference = word.translation_en
        options = _deterministic_shuffle([reference, *(distractors or [])[:3]], seed=word.id)
        prompt = f"What does '{word.lemma}' mean?"
        hint = word.cefr_level

    spec = {"w": word.id, "t": quiz_type, "r": reference, "p": prompt}
    return QuizQuestion(
        question_id=encode_qid(spec),
        word_id=word.id,
        quiz_type=quiz_type,
        prompt=prompt,
        options=options,
        hint=hint,
    )
