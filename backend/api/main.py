"""FastAPI app -- deliberately thin (CLAUDE.md section 4).

It exposes CRUD over the data model and will later delegate session composition
to ``backend/core`` and expose nothing that the agent needs directly (the agent
talks to MCP servers, not this API -- non-negotiable principle #3).
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.schemas import (
    ReviewLogIn,
    ReviewLogOut,
    UserIn,
    UserOut,
    WordIn,
    WordOut,
)
from backend.db.models import ReviewLog, User, Word
from backend.db.session import get_session

app = FastAPI(title="learn-german backend", version="0.1.0")


def db() -> Iterator[Session]:
    yield from get_session()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- words ---------------------------------------------------------------
@app.get("/words", response_model=list[WordOut])
def list_words(
    session: Session = Depends(db),
    cefr_level: str | None = None,
    topic: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Word]:
    stmt = select(Word).order_by(Word.frequency_rank)
    if cefr_level:
        stmt = stmt.where(Word.cefr_level == cefr_level)
    if topic:
        stmt = stmt.where(Word.topic == topic)
    stmt = stmt.limit(min(limit, 500)).offset(offset)
    return list(session.scalars(stmt))


@app.get("/words/{word_id}", response_model=WordOut)
def get_word(word_id: int, session: Session = Depends(db)) -> Word:
    word = session.get(Word, word_id)
    if word is None:
        raise HTTPException(404, "word not found")
    return word


@app.post("/words", response_model=WordOut, status_code=201)
def create_word(payload: WordIn, session: Session = Depends(db)) -> Word:
    word = Word(**payload.model_dump())
    session.add(word)
    try:
        session.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "lemma already exists") from exc
    session.refresh(word)
    return word


# --- users --------------------------------------------------------------
@app.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserIn, session: Session = Depends(db)) -> User:
    user = User(**payload.model_dump())
    session.add(user)
    session.flush()
    session.refresh(user)
    return user


@app.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, session: Session = Depends(db)) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    return user


# --- review logs ------------------------------------------------------
@app.post("/review-logs", response_model=ReviewLogOut, status_code=201)
def create_review_log(payload: ReviewLogIn, session: Session = Depends(db)) -> ReviewLog:
    if session.get(User, payload.user_id) is None:
        raise HTTPException(404, "user not found")
    if session.get(Word, payload.word_id) is None:
        raise HTTPException(404, "word not found")
    log = ReviewLog(**payload.model_dump())
    session.add(log)
    session.flush()
    session.refresh(log)
    return log


@app.get("/users/{user_id}/review-logs", response_model=list[ReviewLogOut])
def list_review_logs(
    user_id: int, session: Session = Depends(db), limit: int = 200
) -> list[ReviewLog]:
    stmt = (
        select(ReviewLog)
        .where(ReviewLog.user_id == user_id)
        .order_by(ReviewLog.timestamp.desc())
        .limit(min(limit, 1000))
    )
    return list(session.scalars(stmt))
