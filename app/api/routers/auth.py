"""Admin authentication.

For the first phase, a single admin account is bootstrapped from environment
variables (ADMIN_USERNAME / ADMIN_PASSWORD_HASH). A full user table for the panel
can replace this later without changing the token contract.
"""

from __future__ import annotations

import os

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger

from app.api.schemas import Token
from app.api.security import create_access_token, verify_password
from app.services.throttle import rate_limited

router = APIRouter(prefix="/auth", tags=["auth"])

# Bootstrap admin (optional). Generate a hash with:
#   python -c "from app.api.security import hash_password; print(hash_password('secret'))"
_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
_ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")


#: Failed logins allowed per client before a lockout window kicks in.
_LOGIN_ATTEMPTS = 5
_LOGIN_WINDOW = 300


@router.post("/token", response_model=Token)
async def login(
    request: Request, form: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Token:
    if not _ADMIN_PASSWORD_HASH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin login not configured (set ADMIN_PASSWORD_HASH).",
        )

    # Without this, the password hash can be brute-forced at full speed.
    client = request.client.host if request.client else "unknown"
    if await rate_limited(f"login:{client}", limit=_LOGIN_ATTEMPTS, window=_LOGIN_WINDOW):
        logger.warning("AUTH: login attempts from {} are rate limited", client)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again in a few minutes.",
        )

    valid = (
        form.username == _ADMIN_USERNAME
        and verify_password(form.password, _ADMIN_PASSWORD_HASH)
    )
    if not valid:
        logger.warning("AUTH: failed login for {!r} from {}", form.username, client)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    token = create_access_token(subject=form.username, extra={"role": "admin"})
    return Token(access_token=token)
