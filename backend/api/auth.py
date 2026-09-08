"""Lightweight username/password login for the frontend.

No tokens, no cookies, no sessions: register/login return the user's id and the
browser remembers it. Anonymous users (``POST /users``, the agent, the
simulator) are unaffected -- they simply have a NULL username.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.schemas import AuthOut, LoginIn, RegisterIn
from backend.api.security import hash_password, verify_password
from backend.db.models import User
from backend.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


def db() -> Iterator[Session]:
    yield from get_session()


def _by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(func.lower(User.username) == username.lower()))


@router.post("/register", response_model=AuthOut, status_code=201)
def register(payload: RegisterIn, session: Session = Depends(db)) -> User:
    if _by_username(session, payload.username) is not None:
        raise HTTPException(409, "username already taken")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        target=payload.target,
    )
    session.add(user)
    session.flush()
    session.refresh(user)
    return user


@router.post("/login", response_model=AuthOut)
def login(payload: LoginIn, session: Session = Depends(db)) -> User:
    user = _by_username(session, payload.username)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid username or password")
    return user
