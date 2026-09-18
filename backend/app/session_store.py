from __future__ import annotations

from .connection_models import SessionConnection


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionConnection] = {}

    def create(self, connection: SessionConnection) -> SessionConnection:
        self._sessions[connection.session_id] = connection
        return connection

    def get(self, session_id: str | None) -> SessionConnection | None:
        if not session_id:
            return None
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
