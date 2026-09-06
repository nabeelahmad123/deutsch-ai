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
    ConversationIn,
    ConversationStartOut,
    ConvFinishIn,
    FinishIn,
    ProgressOut,
    QuizIn,
    QuizQuestionOut,
    ReviewIn,
    ReviewOut,
    SessionIn,
    SessionOut,
    TurnIn,
    TurnOut,
)
from backend.core import read_models, scheduler
from backend.db.models import Word
from backend.db.session import get_session
from backend.study import conversation, grading, quiz

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
            session,
            payload.user_id,
            payload.minutes_available,
            payload.topic,
            level=payload.cefr_level,
            as_of=_now(),
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
    # Verdict is exact/fuzzy (+ an LLM semantic path for de_to_en); the diagnosis
    # of *why* a miss happened is rule-based first, LLM only for genuinely wrong
    # words, and degrades to a generic label without credentials.
    result = grading.grade(spec["t"], spec["r"], payload.user_answer, prompt=spec.get("p", ""))
    word = session.get(Word, spec["w"])
    diag = grading.diagnose(
        spec["t"],
        spec["r"],
        payload.user_answer,
        correct=result.correct,
        prompt=spec.get("p", ""),
        article=word.article if word else None,
        plural=word.plural if word else None,
    )
    try:
        scheduler.update_after_review(
            session,
            payload.user_id,
            spec["w"],
            result.correct,
            _NO_TIMING_MS,
            as_of=_now(),
            error_type=diag.error_type,
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
        error_type=diag.error_type,
        feedback=diag.feedback,
        new_state=asdict(state),
    )


@router.post("/conversation", response_model=ConversationStartOut, status_code=201)
def start_conversation(
    payload: ConversationIn, session: Session = Depends(db)
) -> ConversationStartOut:
    """Begin a conversational-practice session: compose target words (due + weak +
    a little new -- the deterministic scheduler still picks them) and generate the
    tutor's German opening line."""
    try:
        start = conversation.start_conversation(
            session, payload.user_id, payload.scenario, payload.minutes
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return ConversationStartOut(
        session_id=start.session_id,
        scenario=start.scenario,
        level=start.level,
        opener=start.opener,
        targets=[asdict(w) for w in start.targets],
    )


@router.post("/conversation/turn", response_model=TurnOut)
def conversation_turn(payload: TurnIn, session: Session = Depends(db)) -> TurnOut:
    """One dialogue turn. The frontend keeps the transcript; this replies in
    German and reports which target words the learner just used correctly."""
    targets = read_models.load_word_views(session, payload.target_word_ids)
    by_lemma = {w.lemma.lower(): w.id for w in targets}
    level = str(scheduler.cefr_ceiling(session, payload.user_id))
    reply = conversation.tutor_turn(
        payload.scenario,
        level,
        [w.lemma for w in targets],
        [m.model_dump() for m in payload.history],
        payload.user_message,
    )
    used_ids = [by_lemma[lemma.lower()] for lemma in reply.used_lemmas if lemma.lower() in by_lemma]
    return TurnOut(reply=reply.reply, used_word_ids=used_ids, available=reply.available)


@router.post("/conversation/finish")
def finish_conversation(payload: ConvFinishIn, session: Session = Depends(db)) -> dict:
    try:
        return conversation.finish_conversation(
            session,
            payload.session_id,
            payload.user_id,
            payload.used_word_ids,
            turns=payload.turns,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/review", response_model=ReviewOut)
def submit_review(payload: ReviewIn, session: Session = Depends(db)) -> ReviewOut:
    """Record a self-graded outcome (swipe deck) -- no answer text to grade."""
    try:
        scheduler.update_after_review(
            session,
            payload.user_id,
            payload.word_id,
            payload.correct,
            payload.response_time_ms,
            as_of=_now(),
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    state = read_models.card_state_view(session, payload.user_id, payload.word_id)
    return ReviewOut(word_id=payload.word_id, correct=payload.correct, new_state=asdict(state))


@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: int, payload: FinishIn, session: Session = Depends(db)) -> dict:
    try:
        summary = read_models.summarise_session(session, session_id, payload.words_covered)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return asdict(summary)


@router.get("/users/{user_id}/dashboard")
def dashboard(user_id: int, session: Session = Depends(db)) -> dict:
    """Rich analytics for the frontend Dashboard tab (activity, streak, maturity,
    forecast, per-topic coverage, recent sessions). Read-only projections."""
    try:
        return read_models.build_dashboard(session, user_id, as_of=_now())
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


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
        by_level=read_models.coverage_by_level(session, user_id),
        due_words=[asdict(w) for w in read_models.load_word_views(session, due_ids)],
        weak_words=[asdict(w) for w in read_models.load_word_views(session, weak_ids)],
    )
