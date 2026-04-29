from __future__ import annotations

from hmac import compare_digest

from fastapi import Header, HTTPException, status


def require_internal_token(token: str, header_value: str | None) -> None:
    if not header_value or not token or not compare_digest(header_value, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unauthorized",
        )


def internal_token_header(x_internal_token: str | None = Header(default=None)) -> str | None:
    return x_internal_token
