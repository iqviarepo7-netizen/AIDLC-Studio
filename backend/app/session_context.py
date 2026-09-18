from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .connection_models import SessionConnection

_current_session: ContextVar[SessionConnection | None] = ContextVar("aidlc_session", default=None)


def get_current_session() -> SessionConnection | None:
    return _current_session.get()


def set_current_session(session: SessionConnection | None) -> None:
    _current_session.set(session)
