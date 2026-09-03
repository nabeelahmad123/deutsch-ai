"""Study-flow endpoints for the minimal frontend (CLAUDE.md section 13).

Human-facing, unlike the agent (which goes through MCP tools). Thin wrappers over
``backend.core.scheduler`` + ``backend.study`` -- the same domain logic the MCP
server uses. Free-text answers are graded by exact/fuzzy match only here (no LLM).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.schemas import (
    AnswerIn,
    AnswerOut,
    FinishIn,
    ProgressOut,
    QuizIn,
    QuizQuestionOut,
    SessionIn,
    SessionOut,
)
from backend.core import read_models, scheduler
from backend.db.session import get_session
from backend.study import grading, quiz

router = APIRouter(prefix="/study", tags=["study"])
_NO_TIMING_MS = 5000  # the frontend does not time answers


def db() -> Iterator[Session]:
    yield from get_session()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@router.post("/sessions", response_model=SessionOut, status_code=201)
def compose_session(payload: SessionIn, session: Session = Depends(db)) -> SessionOut:
    try:
        plan = scheduler.create_learning_session(
            session, payload.user_id, payload.minutes_available, payload.topic, as_of=_now()
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    view = read_models.session_view(session, plan)
    return SessionOut(
        session_id=view.session_id,
        user_id=view.user_id,
        minutes_available=view.minutes_available,
        topic=view.topic,
        review_words=[asdict(w) for w in view.review_words],
        new_words=[asdict(w) for w in view.new_words],
    )


@router.post("/quiz", response_model=list[QuizQuestionOut])
def build_quiz(payload: QuizIn, session: Session = Depends(db)) -> list[QuizQuestionOut]:
    if payload.quiz_type not in quiz.QUIZ_TYPES:
        raise HTTPException(422, f"quiz_type must be one of {quiz.QUIZ_TYPES}")
    out: list[QuizQuestionOut] = []
    for view in read_models.load_word_views(session, payload.word_ids):
        distractors = (
            read_models.pick_distractors(session, view.id)
            if payload.quiz_type == "multiple_choice"
            else None
        )
        q = quiz.build_question(view, payload.quiz_type, distractors)
        if q is not None:
            out.append(QuizQuestionOut(**asdict(q)))
    return out


@router.post("/answers", response_model=AnswerOut)
def submit_answer(payload: AnswerIn, session: Session = Depends(db)) -> AnswerOut:
    try:
        spec = quiz.decode_qid(payload.question_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Frontend grading is exact/fuzzy only -- no LLM.
    result = grading.grade(spec["t"], spec["r"], payload.user_answer, prompt=spec.get("p", ""))
    try:
        scheduler.update_after_review(
            session, payload.user_id, spec["w"], result.correct, _NO_TIMING_MS, as_of=_now()
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    state = read_models.card_state_view(session, payload.user_id, spec["w"])
    return AnswerOut(
        question_id=payload.question_id,
        word_id=spec["w"],
        correct=result.correct,
        score=result.score,
        rationale=result.rationale,
        expected=spec["r"],
        method=result.method,
        new_state=asdict(state),
    )


@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: int, payload: FinishIn, session: Session = Depends(db)) -> dict:
    try:
        summary = read_models.summarise_session(session, session_id, payload.words_covered)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return asdict(summary)


@router.get("/users/{user_id}/progress", response_model=ProgressOut)
def progress(user_id: int, session: Session = Depends(db)) -> ProgressOut:
    try:
        profile = read_models.get_user_profile(session, user_id, as_of=_now())
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    due_ids = scheduler.words_due_for_review(session, user_id, _now())[:20]
    weak_ids = scheduler.weak_words(session, user_id, 10)
    return ProgressOut(
        user_id=profile.user_id,
        target=profile.target,
        cefr_ceiling=profile.cefr_ceiling,
        total_reviews=profile.total_reviews,
        words_seen=profile.words_seen,
        words_due_now=profile.words_due_now,
        overall_accuracy=profile.overall_accuracy,
        due_words=[asdict(w) for w in read_models.load_word_views(session, due_ids)],
        weak_words=[asdict(w) for w in read_models.load_word_views(session, weak_ids)],
    )
