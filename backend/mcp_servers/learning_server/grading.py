"""Answer grading for ``evaluate_answer`` (CLAUDE.md section 8).

Exact / fuzzy string matching for constrained answers; the Anthropic API for
free-text semantic grading. If the LLM path is unavailable (no credentials, API
error) it degrades to fuzzy matching and says so in ``method`` -- graceful
failure is a first-class requirement here, and the failure-injection suite
(LG-13/14) leans on it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

# Default grader model. The env var wins; Sonnet is a reasonable, cheaper choice
# for this one-shot classification if the operator prefers it.
DEFAULT_MODEL = "claude-opus-5"
FUZZY_THRESHOLD = 0.85
_LEADING = re.compile(r"^(der|die|das|ein|eine|einen|to|the|a|an)\s+", re.IGNORECASE)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM = (
    "You grade a German learner's answer. Reply with ONLY a compact JSON object: "
    '{"correct": <bool>, "score": <number 0..1>, "rationale": "<one short sentence>"}. '
    "Accept spelling slips, missing articles and word-order differences; reject "
    "answers whose meaning is wrong or missing."
)


@dataclass(frozen=True)
class GradeResult:
    correct: bool
    score: float
    rationale: str
    method: str  # "exact" | "fuzzy" | "semantic" | "semantic_fallback_fuzzy"


@dataclass(frozen=True)
class AnswerEvaluation:
    question_id: str
    word_id: int
    quiz_type: str
    correct: bool
    score: float
    rationale: str
    method: str
    expected: str


def normalize(text: str) -> str:
    text = _LEADING.sub("", text.strip().casefold())
    text = _PUNCT.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _close_enough(answer: str, part: str) -> tuple[bool, float]:
    ratio = SequenceMatcher(None, answer, part).ratio()
    # A ratio threshold handles longer answers; an edit-distance allowance
    # (~1 typo per 6 chars, min 1) rescues short words where one substitution
    # already drops the ratio below the threshold.
    edits_allowed = max(1, len(part) // 6)
    ok = ratio >= FUZZY_THRESHOLD or _levenshtein(answer, part) <= edits_allowed
    return ok, ratio


def fuzzy_match(answer: str, reference: str) -> tuple[bool, float]:
    """Match against the reference; multi-sense references ("journey, travel")
    match if any comma/semicolon/slash-separated part matches."""
    a = normalize(answer)
    if not a:
        return False, 0.0
    parts = [normalize(p) for p in re.split(r"[;,/]", reference) if p.strip()] or [
        normalize(reference)
    ]
    results = [_close_enough(a, p) for p in parts]
    best_ok = any(ok for ok, _ in results)
    best_ratio = max(ratio for _, ratio in results)
    return best_ok, round(best_ratio, 3)


def _parse_grade(text: str) -> dict:
    match = _JSON_OBJ.search(text)
    if match is None:
        raise ValueError(f"no JSON object in model reply: {text[:120]!r}")
    return json.loads(match.group(0))


def semantic_grade(
    prompt: str, reference: str, user_answer: str, *, model: str | None = None, client=None
) -> GradeResult:
    """Grade a free-text answer with the Anthropic API. Raises on any failure so
    the caller can fall back."""
    if client is None:
        from anthropic import Anthropic

        client = Anthropic()  # resolves ANTHROPIC_API_KEY / auth profile
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    message = client.messages.create(
        model=model,
        max_tokens=256,
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Question: {prompt}\nReference answer: {reference}\n"
                    f"Learner's answer: {user_answer}"
                ),
            }
        ],
    )
    text = "".join(block.text for block in message.content if block.type == "text")
    data = _parse_grade(text)
    correct = bool(data["correct"])
    score = float(data.get("score", 1.0 if correct else 0.0))
    return GradeResult(
        correct, max(0.0, min(score, 1.0)), str(data.get("rationale", "")), "semantic"
    )


def grade(
    quiz_type: str,
    reference: str,
    user_answer: str,
    *,
    prompt: str = "",
    client=None,
) -> GradeResult:
    if quiz_type == "de_to_en":
        try:
            return semantic_grade(prompt, reference, user_answer, client=client)
        except Exception as exc:  # noqa: BLE001 - any failure -> fuzzy fallback
            ok, score = fuzzy_match(user_answer, reference)
            return GradeResult(
                ok,
                score,
                f"semantic grading unavailable ({type(exc).__name__}); used fuzzy match",
                "semantic_fallback_fuzzy",
            )

    if quiz_type == "multiple_choice":
        ok = normalize(user_answer) == normalize(reference)
        return GradeResult(ok, 1.0 if ok else 0.0, "exact option match", "exact")

    # en_to_de, article: exact, else fuzzy
    if normalize(user_answer) == normalize(reference):
        return GradeResult(True, 1.0, "exact match", "exact")
    ok, score = fuzzy_match(user_answer, reference)
    return GradeResult(ok, score, f"fuzzy string match (ratio {score})", "fuzzy")
