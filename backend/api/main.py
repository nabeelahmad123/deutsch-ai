"""FastAPI app -- deliberately thin (CLAUDE.md section 4).

It exposes CRUD over the data model and will later delegate session composition
to ``backend/core`` and expose nothing that the agent needs directly (the agent
talks to MCP servers, not this API -- non-negotiable principle #3).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.auth import router as auth_router
from backend.api.schemas import (
    ReviewLogIn,
    ReviewLogOut,
    TopicCount,
    UserIn,
    UserOut,
    WordIn,
    WordOut,
    WordPage,
)
from backend.api.study import router as study_router
from backend.db.models import CEFRLevel, ReviewLog, User, Word
from backend.db.session import get_session

app = FastAPI(title="learn-german backend", version="0.1.0")
app.include_router(auth_router)
app.include_router(study_router)

# The minimal frontend (a static page) calls this API from the browser. Origins
# are configurable; default is permissive for local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def db() -> Iterator[Session]:
    yield from get_session()


@app.exception_handler(IntegrityError)
def _integrity_error(_request, exc: IntegrityError):  # pragma: no cover - thin shim
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=409, content={"detail": "constraint violation"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- words ---------------------------------------------------------------
@app.get("/words", response_model=WordPage)
def list_words(
    session: Session = Depends(db),
    cefr_level: CEFRLevel | None = None,
    topic: str | None = None,
    article: str | None = None,
    q: str | None = Query(default=None, description="case-insensitive lemma prefix"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> WordPage:
    filters = []
    if cefr_level:
        filters.append(Word.cefr_level == cefr_level)
    if topic:
        filters.append(Word.topic == topic)
    if article:
        filters.append(Word.article == article)
    if q:
        filters.append(Word.lemma.ilike(f"{q}%"))

    total = session.scalar(select(func.count()).select_from(Word).where(*filters)) or 0
    rows = session.scalars(
        select(Word).where(*filters).order_by(Word.frequency_rank).limit(limit).offset(offset)
    )
    return WordPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[WordOut.model_validate(w) for w in rows],
    )


@app.get("/topics", response_model=list[TopicCount])
def list_topics(session: Session = Depends(db)) -> list[TopicCount]:
    rows = session.execute(
        select(Word.topic, func.count())
        .where(Word.topic.is_not(None))
        .group_by(Word.topic)
        .order_by(func.count().desc())
    )
    return [TopicCount(topic=t, count=c) for t, c in rows]


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
    user_id: int,
    session: Session = Depends(db),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[ReviewLog]:
    if session.get(User, user_id) is None:
        raise HTTPException(404, "user not found")
    stmt = (
        select(ReviewLog)
        .where(ReviewLog.user_id == user_id)
        .order_by(ReviewLog.timestamp.desc(), ReviewLog.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


# --- static frontend --------------------------------------------------------
# Serve the minimal frontend from this app so the demo is a single origin: no
# separate static server, no port juggling, no CORS. `?api=` still overrides the
# base URL (used when the page is hosted elsewhere -- e.g. behind nginx). Mounted
# last so every explicit API route above takes precedence over the catch-all.
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
