#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import base64
import datetime
import hashlib
import hmac
import re
import secrets

from webserver.models import ReaderApiKey


TOKEN_VERSION = "moke_tk1"
TOKEN_PURPOSE = "device_login"
ACTIVE_KEY_LIMIT = 10
TOKEN_PATTERN = re.compile(r"^moke_tk1_([A-Za-z0-9_-]{12})_([A-Za-z0-9_-]{43})$")


class DeviceApiKeyLimitError(Exception):
    pass


def _urlsafe_random(byte_count):
    return base64.urlsafe_b64encode(secrets.token_bytes(byte_count)).decode("ascii").rstrip("=")


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_token(token):
    match = TOKEN_PATTERN.fullmatch(token or "")
    if not match:
        return None
    return match.group(1)


def serialize_api_key(api_key):
    def iso(value):
        return value.isoformat() if value else None

    return {
        "id": api_key.id,
        "device_id": api_key.device_id,
        "device_name": api_key.name,
        "prefix": api_key.prefix,
        "created_at": iso(api_key.created_at),
        "last_used_at": iso(api_key.last_used_at),
    }


def issue_api_key(session, reader_id, device_id, device_name):
    device_id = (device_id or "").strip()[:200]
    device_name = (device_name or "").strip()[:200]
    if not device_id:
        raise ValueError("device_id is required")
    if not device_name:
        device_name = "Moke"

    now = datetime.datetime.now()
    same_device = (
        session.query(ReaderApiKey)
        .filter(
            ReaderApiKey.reader_id == reader_id,
            ReaderApiKey.device_id == device_id,
            ReaderApiKey.revoked_at.is_(None),
        )
        .all()
    )
    for api_key in same_device:
        api_key.revoked_at = now

    active_count = (
        session.query(ReaderApiKey).filter(ReaderApiKey.reader_id == reader_id, ReaderApiKey.revoked_at.is_(None)).count()
    )
    if active_count >= ACTIVE_KEY_LIMIT:
        session.rollback()
        raise DeviceApiKeyLimitError()

    prefix = _urlsafe_random(9)
    secret = _urlsafe_random(32)
    token = "%s_%s_%s" % (TOKEN_VERSION, prefix, secret)
    api_key = ReaderApiKey(
        reader_id=reader_id,
        device_id=device_id,
        name=device_name,
        prefix=prefix,
        token_hash=hash_token(token),
        purpose=TOKEN_PURPOSE,
        created_at=now,
    )
    session.add(api_key)
    session.commit()
    return api_key, token


def authenticate_api_key(session, token):
    prefix = parse_token(token)
    if not prefix:
        return None

    digest = hash_token(token)
    candidates = (
        session.query(ReaderApiKey)
        .filter(
            ReaderApiKey.prefix == prefix,
            ReaderApiKey.purpose == TOKEN_PURPOSE,
            ReaderApiKey.revoked_at.is_(None),
        )
        .all()
    )
    now = datetime.datetime.now()
    for api_key in candidates:
        if api_key.expires_at and api_key.expires_at <= now:
            continue
        if hmac.compare_digest(api_key.token_hash, digest):
            return api_key
    return None
