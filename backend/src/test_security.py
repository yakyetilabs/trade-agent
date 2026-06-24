"""Unit tests for the auth boundary.

Firebase verification and app init are monkeypatched so the allowlist logic and the
401/403 branching are exercised without real credentials or network calls.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from src import security


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_authorized_email_passes_and_is_lowercased(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "get_firebase_app", lambda: None)
    monkeypatch.setattr(security.auth, "verify_id_token", lambda _t: {"email": "Ok@Example.com"})
    monkeypatch.setattr(security, "ALLOWED_USERS", frozenset({"ok@example.com"}))

    assert security.verify_authorized_analyst(_creds("good-token")) == "ok@example.com"


def test_unlisted_email_is_rejected_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "get_firebase_app", lambda: None)
    monkeypatch.setattr(security.auth, "verify_id_token", lambda _t: {"email": "intruder@evil.com"})
    monkeypatch.setattr(security, "ALLOWED_USERS", frozenset({"ok@example.com"}))

    with pytest.raises(HTTPException) as exc_info:
        security.verify_authorized_analyst(_creds("good-token"))
    assert exc_info.value.status_code == 403


def test_invalid_token_is_rejected_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "get_firebase_app", lambda: None)

    def _raise(_t: str) -> dict[str, object]:
        raise ValueError("invalid signature")

    monkeypatch.setattr(security.auth, "verify_id_token", _raise)

    with pytest.raises(HTTPException) as exc_info:
        security.verify_authorized_analyst(_creds("forged-token"))
    assert exc_info.value.status_code == 401
