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
import re
from dataclasses import dataclass

from backend.core.read_models import WordView

QUIZ_TYPES: tuple[str, ...] = ("en_to_de", "de_to_en", "multiple_choice", "article")
_QID_PREFIX = "q1:"

# Wiktionary glosses often carry the whole dictionary entry -- multiple senses
# separated by ``;`` and long parenthetical notes ("Germany (a nation or
# civilization occupying the country around the Rhine ...)"). For a flashcard we
# want the primary sense only. The full gloss stays in the DB and the /words API.
_GLOSS_PAREN = re.compile(r"\s*\([^()]*\)\s*$")
_GLOSS_MAX = 60


def short_gloss(translation_en: str) -> str:
    """The primary sense of a gloss: first ``;``-clause, trailing note dropped."""
    text = (translation_en or "").split(";", 1)[0].strip()
    text = _GLOSS_PAREN.sub("", text).strip()
    if len(text) < 2 or len(text) > _GLOSS_MAX:
        # a single over-long sense with no ';' -- fall back to a hard clip
        clipped = (text or (translation_en or "")).strip()
        return clipped[:_GLOSS_MAX].rstrip(" ,") if len(clipped) > _GLOSS_MAX else clipped
    return text


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

    gloss = short_gloss(word.translation_en)
    options: list[str] | None = None
    if quiz_type == "article":
        if not word.article:
            return None
        reference = word.article
        prompt = f"Which article completes: ___ {word.lemma}? ({gloss})"
        options = ["der", "die", "das"]
        hint = word.cefr_level
    elif quiz_type == "en_to_de":
        reference = word.lemma
        prompt = f"Translate to German: {gloss}"
        hint = f"{word.cefr_level}, starts with '{word.lemma[:1]}'"
    elif quiz_type == "de_to_en":
        reference = word.translation_en
        shown = f"{word.article} {word.lemma}" if word.article else word.lemma
        prompt = f"Translate to English: {shown}"
        hint = word.cefr_level
    else:  # multiple_choice
        reference = gloss
        options = _deterministic_shuffle(
            [reference, *(short_gloss(d) for d in (distractors or [])[:3])], seed=word.id
        )
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
