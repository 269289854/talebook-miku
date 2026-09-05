"""Isolated real-Calibre HTTP tests, run inside the deployed backend image."""

import importlib.util
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from calibre.db.legacy import LibraryDatabase
from calibre.ebooks.metadata.book.base import Metadata
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webserver.handlers.publication import BookPublication  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publication_fixtures", ROOT / "tests/test_publication.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class Session:
    def __init__(self, external=False):
        self.external = external

    def query(self, *args):
        return self

    def filter(self, *args):
        return self

    def all(self):
        return [SimpleNamespace(data={"external_path": True})] if self.external else []

    def close(self):
        pass


class FixtureHandler(BookPublication):
    def initialize(self):
        self.db = self.settings["legacy"]
        self.session = Session(self.request.headers.get("X-Test-External") == "yes")
        self.admin_user = None

    def prepare(self):
        # Auth decorators and permission checks remain the production code.
        # Only unrelated installation, cookie and invitation setup is isolated.
        pass

    def get_current_user(self):
        role = self.request.headers.get("X-Test-Role")
        if role is None:
            return None
        return SimpleNamespace(
            id=1,
            username="fixture",
            is_admin=lambda: role == "admin",
            can_edit=lambda: role != "readonly",
            can_upload=lambda: role != "readonly",
        )


class PublicationHTTP(AsyncHTTPTestCase):
    def get_app(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="p-")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        library = self.directory / "l"
        library.mkdir()
        self.db = LibraryDatabase(str(library))
        self.addCleanup(self.db.close)
        epub = self.directory / "old.epub"
        epub.write_bytes(fixtures.make_epub())
        txt = self.directory / "original.txt"
        txt.write_text("The villagers inspect the old bridge.", encoding="utf-8")
        self.bid = self.db.import_book(Metadata("Bridge", ["Test Author"]), [str(epub), str(txt)])
        self.db.new_api.set_cover({self.bid: fixtures.make_cover()})
        self.path = f"/api/book/{self.bid}/publication"
        from unittest.mock import patch

        from webserver.handlers import publication

        config = patch.object(
            publication.loader, "get_settings", return_value={"convert_path": str(self.directory)}
        )
        config.start()
        self.addCleanup(config.stop)
        errors = patch.object(publication.logging, "exception")
        self.errors = errors.start()
        self.addCleanup(errors.stop)
        self.addCleanup(self.errors.assert_not_called)
        return Application([(r"/api/book/([0-9]+)/publication", FixtureHandler)], legacy=self.db)

    def request(self, path=None, role="admin", **kwargs):
        headers = kwargs.pop("headers", {})
        if role:
            headers["X-Test-Role"] = role
        response = self.fetch(path or self.path, headers=headers, **kwargs)
        self.assertEqual(response.code, 200)
        return json.loads(response.body)

    def multipart(self, revision, request_id, confirmed="true"):
        boundary = "publication-fixture"
        metadata = {
            "title": "Bridge",
            "authors": ["Test Author"],
            "comments": "New complete chapter",
            "tags": ["ordinary", "bridge"],
            "languages": ["eng"],
        }
        parts = []
        for key, value in {
            "confirmed": confirmed,
            "expected_revision": revision,
            "request_id": request_id,
            "metadata": json.dumps(metadata),
        }.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
            )
        for key, name, data in (
            ("ebook", "book.epub", fixtures.make_epub("A new chapter.")),
            ("cover", "cover.jpg", fixtures.make_cover("blue")),
        ):
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n"
            )
        parts.append(f"--{boundary}--\r\n".encode())
        return {
            "method": "POST",
            "body": b"".join(parts),
            "headers": {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        }

    def test_guest_and_ordinary_user_cannot_inspect_or_write(self):
        for role, expected in ((None, "user.need_login"), ("user", "permission"), ("readonly", "permission")):
            self.assertEqual(self.request(role=role)["err"], expected)
            self.assertEqual(self.request(role=role, method="POST", body="")["err"], expected)

    def test_confirmation_is_required(self):
        self.assertEqual(
            self.request(method="POST", body=urlencode({"confirmed": "false"}))["err"],
            "publication.confirmation",
        )

    def test_external_books_are_rejected(self):
        headers = {"X-Test-External": "yes"}
        self.assertEqual(self.request(headers=headers)["err"], "publication.external")

    def test_real_replacement_receipt_and_stable_txt(self):
        before_txt = fixtures.core.file_digest(self.db.new_api.format_abspath(self.bid, "TXT"))
        target = self.request()
        self.assertEqual(target["version"], 1)
        request_id = str(uuid.uuid4())
        self.assertEqual(self.request(f"{self.path}?request_id={request_id}")["state"], "absent")
        payload = self.multipart(target["revision"], request_id)
        first = self.request(**payload)
        self.assertEqual(first["state"], "completed", first)
        self.assertEqual(self.request(**payload), first)
        self.assertEqual(self.request(f"{self.path}?request_id={request_id}"), first)
        self.assertEqual(
            fixtures.core.file_digest(self.db.new_api.format_abspath(self.bid, "TXT")), before_txt
        )
        self.assertTrue(self.db.new_api.has_id(self.bid))
        self.assertEqual(self.db.get_data_as_dict(ids=[self.bid])[0]["comments"], "New complete chapter")

    def test_stale_revision_cannot_replace(self):
        target = self.request()
        self.db.new_api.set_field("comments", {self.bid: "Changed elsewhere"})
        result = self.request(**self.multipart(target["revision"], str(uuid.uuid4())))
        self.assertEqual(result["err"], "publication.conflict")

    def test_missing_target(self):
        self.assertEqual(self.request("/api/book/99999/publication")["err"], "not_found")


if __name__ == "__main__":
    unittest.main()
