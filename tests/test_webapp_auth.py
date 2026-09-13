"""Tests for Telegram Mini App initData validation."""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.api.webapp_auth import validate_init_data

TOKEN = "123456:TEST-TOKEN"
NOW = 1_800_000_000


def _sign(fields: dict[str, str], token: str = TOKEN) -> str:
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def _init_data(**overrides: str) -> str:
    fields = {
        "auth_date": str(NOW - 60),
        "query_id": "AAH",
        "user": json.dumps({"id": 5933423757, "first_name": "Vlad", "username": "v"}),
    }
    fields.update(overrides)
    fields["hash"] = _sign({k: v for k, v in fields.items() if k != "hash"})
    return urlencode(fields)


def test_valid_init_data_returns_user():
    data = validate_init_data(_init_data(), TOKEN, now=NOW)
    assert data["user"]["id"] == 5933423757
    assert data["user"]["username"] == "v"


def test_tampered_payload_is_rejected():
    raw = _init_data()
    tampered = raw.replace("5933423757", "1")  # change the user id, keep the hash
    with pytest.raises(ValueError, match="bad signature"):
        validate_init_data(tampered, TOKEN, now=NOW)


def test_wrong_bot_token_is_rejected():
    with pytest.raises(ValueError, match="bad signature"):
        validate_init_data(_init_data(), "999:OTHER", now=NOW)


def test_stale_init_data_is_rejected():
    old = _init_data(auth_date=str(NOW - 3 * 86400))
    with pytest.raises(ValueError, match="expired"):
        validate_init_data(old, TOKEN, now=NOW)


def test_missing_hash_is_rejected():
    with pytest.raises(ValueError, match="hash missing"):
        validate_init_data("auth_date=1&user=%7B%7D", TOKEN, now=NOW)
