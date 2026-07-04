"""Admin authentication.

For the first phase, a single admin account is bootstrapped from environment
variables (ADMIN_USERNAME / ADMIN_PASSWORD_HASH). A full user table for the panel
can replace this later without changing the token contract.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated

from fastapi import Depends

from app.api.schemas import Token
from app.api.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Bootstrap admin (optional). Generate a hash with:
#   python -c "from app.api.security import hash_password; print(hash_password('secret'))"
_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
_ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")


@router.post("/token", response_model=Token)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
    if not _ADMIN_PASSWORD_HASH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin login not configured (set ADMIN_PASSWORD_HASH).",
        )
    valid = (
        form.username == _ADMIN_USERNAME
        and verify_password(form.password, _ADMIN_PASSWORD_HASH)
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    token = create_access_token(subject=form.username, extra={"role": "admin"})
    return Token(access_token=token)
