#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from webserver import models  # noqa: E402
from webserver.device_api_keys import (  # noqa: E402
    ACTIVE_KEY_LIMIT,
    TOKEN_PATTERN,
    DeviceApiKeyLimitError,
    authenticate_api_key,
    hash_token,
    issue_api_key,
)


def main():
    with tempfile.TemporaryDirectory() as directory:
        engine = create_engine("sqlite:///%s" % (Path(directory) / "device-auth.db"))
        models.Reader.__table__.create(engine)
        models.ReaderApiKey.__table__.create(engine)
        session = sessionmaker(bind=engine)()

        first, first_token = issue_api_key(session, 1, "phone", "Test phone")
        assert TOKEN_PATTERN.fullmatch(first_token)
        assert first.token_hash == hash_token(first_token)
        assert first.token_hash != first_token
        assert authenticate_api_key(session, first_token).id == first.id

        rotated, rotated_token = issue_api_key(session, 1, "phone", "Test phone")
        session.refresh(first)
        assert first.revoked_at is not None
        assert rotated_token != first_token
        assert authenticate_api_key(session, first_token) is None
        assert authenticate_api_key(session, rotated_token).id == rotated.id

        for index in range(ACTIVE_KEY_LIMIT):
            issue_api_key(session, 2, "device-%02d" % index, "Test device")
        try:
            issue_api_key(session, 2, "overflow", "Test device")
        except DeviceApiKeyLimitError:
            pass
        else:
            raise AssertionError("active device key limit was not enforced")

        rotated.revoked_at = datetime.datetime.now()
        session.commit()
        assert authenticate_api_key(session, rotated_token) is None
        session.close()
        engine.dispose()

    print("device auth overlay smoke test passed")


if __name__ == "__main__":
    main()
