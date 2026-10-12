#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import hashlib
import json
import urllib.parse
from unittest import mock

from sqlalchemy import create_engine, inspect

from tests.test_main import TestApp, get_db
from tests.test_main import setUpModule as init
from webserver import main, models
from webserver.device_api_keys import ACTIVE_KEY_LIMIT, TOKEN_PATTERN
from webserver.migrate_db import compare_and_migrate


def setUpModule():
    init()


def _form(**values):
    return urllib.parse.urlencode(values)


class TestDeviceApiKeys(TestApp):
    usernames = ("moke_key_user", "moke_key_other")
    password = "MokeKeyPass66!"

    def _remove_test_users(self, session):
        users = session.query(models.Reader).filter(models.Reader.username.in_(self.usernames)).all()
        user_ids = [user.id for user in users]
        if user_ids:
            session.query(models.ReaderApiKey).filter(models.ReaderApiKey.reader_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            for user in users:
                for social in user.social_auth.all():
                    session.delete(social)
            session.flush()
            for user in users:
                session.delete(user)
            session.commit()

    def setUp(self):
        super().setUp()
        main.CONF["INVITE_MODE"] = False
        session = get_db()
        self._remove_test_users(session)
        for username in self.usernames:
            user = models.Reader(
                username=username,
                name=username,
                email="%s@example.invalid" % username,
                active=True,
                admin=False,
                permission="",
                create_time=datetime.datetime.now(),
                update_time=datetime.datetime.now(),
                access_time=datetime.datetime.now(),
                extra={"kindle_email": ""},
            )
            user.set_secure_password(self.password)
            session.add(user)
        session.commit()

    def tearDown(self):
        main.CONF["INVITE_MODE"] = False
        session = get_db()
        self._remove_test_users(session)
        super().tearDown()

    @staticmethod
    def _cookie_header(response):
        return "; ".join(value.split(";", 1)[0] for value in response.headers.get_list("Set-Cookie"))

    def _password_login(self, username=None, **extra):
        body = {
            "username": username or self.usernames[0],
            "password": self.password,
        }
        body.update(extra)
        response = self.fetch("/api/user/sign_in", method="POST", body=_form(**body))
        self.assertEqual(response.code, 200)
        return response, json.loads(response.body)

    def _remembered_login(self, device_id="device-one", username=None):
        return self._password_login(
            username=username,
            remember_device="true",
            device_id=device_id,
            device_name="Test phone",
        )

    def test_welcome_advertises_password_and_device_key_capabilities(self):
        response = self.json("/api/welcome")
        self.assertEqual(response["auth"], {"password_login": True, "device_api_key": True})

    def test_password_login_bypasses_invite_code_and_sets_both_sessions(self):
        main.CONF["INVITE_MODE"] = True
        response, data = self._password_login()
        self.assertEqual(data["err"], "ok")
        cookie_names = {value.split("=", 1)[0] for value in response.headers.get_list("Set-Cookie")}
        self.assertTrue({"invited", "user_id", "lt"}.issubset(cookie_names))

    def test_password_login_still_validates_captcha_and_password(self):
        main.CONF["INVITE_MODE"] = True
        with mock.patch("webserver.handlers.user.captcha_module.is_captcha_enabled", return_value=True):
            _, captcha = self._password_login()
        self.assertEqual(captcha["err"], "captcha.invalid")

        response = self.json(
            "/api/user/sign_in",
            method="POST",
            body=_form(username=self.usernames[0], password="wrong-password"),
        )
        self.assertEqual(response["err"], "params.invalid")

    def test_remembered_login_returns_raw_key_once_and_stores_only_hash(self):
        _, data = self._remembered_login()
        self.assertEqual(data["err"], "ok")
        token = data["api_key"]
        self.assertRegex(token, TOKEN_PATTERN)
        self.assertNotIn(token, json.dumps(data["api_key_info"]))

        session = get_db()
        row = session.query(models.ReaderApiKey).filter(models.ReaderApiKey.id == data["api_key_info"]["id"]).one()
        self.assertEqual(row.token_hash, hashlib.sha256(token.encode("utf-8")).hexdigest())
        self.assertNotEqual(row.token_hash, token)

    def test_same_device_rotates_key(self):
        _, first = self._remembered_login()
        _, second = self._remembered_login()
        self.assertNotEqual(first["api_key"], second["api_key"])

        session = get_db()
        user = session.query(models.Reader).filter(models.Reader.username == self.usernames[0]).one()
        rows = (
            session.query(models.ReaderApiKey)
            .filter(models.ReaderApiKey.reader_id == user.id, models.ReaderApiKey.device_id == "device-one")
            .all()
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row.revoked_at is None for row in rows), 1)

    def test_active_key_limit_is_enforced(self):
        for index in range(ACTIVE_KEY_LIMIT):
            _, data = self._remembered_login(device_id="device-%02d" % index)
            self.assertEqual(data["err"], "ok")
        _, overflow = self._remembered_login(device_id="device-overflow")
        self.assertEqual(overflow["err"], "api_key.limit")

    def test_api_key_exchanges_for_cookie_session_and_updates_last_use(self):
        _, created = self._remembered_login()
        response = self.fetch(
            "/api/user/api_key/sign_in",
            method="POST",
            body="",
            headers={"Authorization": "Bearer %s" % created["api_key"]},
        )
        data = json.loads(response.body)
        self.assertEqual(data["err"], "ok")
        self.assertIsNotNone(data["api_key_info"]["last_used_at"])

        user_info = self.json("/api/user/info", headers={"Cookie": self._cookie_header(response)})
        self.assertEqual(user_info["user"]["username"], self.usernames[0])

    def test_bearer_key_does_not_authenticate_ordinary_api(self):
        _, created = self._remembered_login()
        response = self.json(
            "/api/user/api_keys",
            headers={"Authorization": "Bearer %s" % created["api_key"]},
        )
        self.assertEqual(response["err"], "user.need_login")

    def test_list_create_revoke_and_cross_account_isolation(self):
        login_response, _ = self._password_login()
        owner_cookie = self._cookie_header(login_response)
        created = self.json(
            "/api/user/api_keys",
            method="POST",
            body=_form(password=self.password, device_id="manual-device", device_name="Manual key"),
            headers={"Cookie": owner_cookie},
        )
        self.assertEqual(created["err"], "ok")
        self.assertNotIn("token_hash", json.dumps(created))

        listed = self.json("/api/user/api_keys", headers={"Cookie": owner_cookie})
        self.assertEqual([item["id"] for item in listed["api_keys"]], [created["api_key_info"]["id"]])

        other_response, _ = self._password_login(username=self.usernames[1])
        other_cookie = self._cookie_header(other_response)
        forbidden = self.json(
            "/api/user/api_keys/%s" % created["api_key_info"]["id"],
            method="DELETE",
            headers={"Cookie": other_cookie},
        )
        self.assertEqual(forbidden["err"], "api_key.not_found")

        revoked = self.json(
            "/api/user/api_keys/%s" % created["api_key_info"]["id"],
            method="DELETE",
            headers={"Cookie": owner_cookie},
        )
        self.assertEqual(revoked["err"], "ok")
        invalid = self.json(
            "/api/user/api_key/sign_in",
            method="POST",
            body="",
            headers={"Authorization": "Bearer %s" % created["api_key"]},
        )
        self.assertEqual(invalid["err"], "api_key.invalid")


def test_compare_and_migrate_creates_reader_api_keys_table(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "legacy.db"))
    models.Reader.__table__.create(engine)

    assert compare_and_migrate(engine)
    inspector = inspect(engine)
    assert "reader_api_keys" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("reader_api_keys")}
    assert {"reader_id", "device_id", "prefix", "token_hash", "revoked_at"}.issubset(columns)
