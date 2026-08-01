from __future__ import annotations

import hashlib
import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings


def _token_digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    supplied = authorization.removeprefix("Bearer ").strip()
    expected = get_settings().api_token
    if not supplied or not secrets.compare_digest(
        _token_digest(supplied), _token_digest(expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
        )
