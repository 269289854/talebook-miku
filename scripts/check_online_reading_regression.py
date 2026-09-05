"""Exercise unchanged deployed Moke reading handlers on a disposable library."""

import json
import sys
import uuid
from pathlib import Path
from unittest import main
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_publication_http as publication_test  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from webserver.handlers.base import BaseHandler  # noqa: E402
from webserver.handlers.book import BookDownload, BookReadingProgress  # noqa: E402
from webserver.handlers.files import EpubReader  # noqa: E402
from webserver.models import ReadingState  # noqa: E402


class ReadingContext:
    def get_current_user(self):
        user = publication_test.FixtureHandler.get_current_user(self)
        if user:
            user.can_save = lambda: True
            user.can_read = lambda: True
            user.is_active = lambda: True
        return user

    def user_id(self):
        return 1 if self.current_user else None

    def get_book(self, bid, raise_exception=True):
        rows = self.db.get_data_as_dict(ids=[int(bid)])
        return rows[0] if rows else None

    def get_book_or_404(self, bid):
        book = self.get_book(bid)
        if book is None:
            from tornado.web import HTTPError
            raise HTTPError(404)
        return book

    def user_history(self, *args):
        self.settings["reading_counters"].append(("history", args))

    def count_increase(self, *args, **kwargs):
        self.settings["reading_counters"].append(("count", args, kwargs))


class FixtureDownload(ReadingContext, BookDownload):
    pass


class FixtureProgress(ReadingContext, BookReadingProgress):
    pass


class FixtureExtract(ReadingContext, EpubReader):
    pass


class OnlineReadingRegression(publication_test.PublicationHTTP):
    def get_app(self):
        app = super().get_app()
        engine = create_engine("sqlite:///:memory:")
        ReadingState.__table__.create(engine)
        self.addCleanup(engine.dispose)
        app.settings.update(
            SessionMaker=sessionmaker(bind=engine), build_time="fixture", default_cover="",
            reading_counters=[],
        )
        prepare = patch.object(BaseHandler, "prepare", lambda self: None)
        prepare.start()
        self.addCleanup(prepare.stop)
        app.add_handlers(".*$", [
            (r"/api/book/([0-9]+\..+)", FixtureDownload),
            (r"/api/book/([0-9]+)/progress", FixtureProgress),
            (r"/get/extract/([0-9]+)/(.*)", FixtureExtract),
        ])
        return app

    def test_online_range_etag_navigation_and_progress_survive_replacement(self):
        url = f"/api/book/{self.bid}.epub?mode=read"
        headers = {"X-Test-Role": "user"}
        old = self.fetch(url, headers=headers)
        self.assertEqual(old.code, 200)
        self.assertEqual(old.headers["Content-Type"], "application/epub+zip")
        self.assertIn("inline", old.headers["Content-Disposition"])
        old_etag = old.headers["Etag"]
        partial = self.fetch(url, headers={**headers, "Range": "bytes=0-31"})
        self.assertEqual(partial.code, 206)
        self.assertEqual(partial.body, old.body[:32])
        self.assertEqual(self._app.settings["reading_counters"], [])
        progress = {
            "schema": "moke.readest.progress.v1", "reader": "readest",
            "moke_book_id": str(self.bid), "location": "epubcfi(/6/2!/4/2)", "fraction": 0.3,
        }
        progress_url = f"/api/book/{self.bid}/progress"
        saved = self.request(
            progress_url, role="user", method="POST", body=json.dumps({"progress": progress}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(saved["err"], "ok", saved)
        before_progress = self.request(progress_url, role="user")["progress"]
        target = self.request()
        replacement = self.request(**self.multipart(target["revision"], str(uuid.uuid4())))
        self.assertEqual(replacement.get("state"), "completed", replacement)
        current = self.fetch(url, headers={**headers, "If-None-Match": old_etag})
        self.assertEqual(current.code, 200, "Old ETag must not produce a stale 304")
        self.assertNotEqual(current.headers["Etag"], old_etag)
        self.assertNotEqual(current.body, old.body)
        partial = self.fetch(url, headers={**headers, "Range": "bytes=-64"})
        self.assertEqual(partial.code, 206)
        self.assertEqual(partial.body, current.body[-64:])
        chapter = self.fetch(f"/get/extract/{self.bid}/chapter.xhtml", headers=headers)
        self.assertEqual(chapter.code, 200)
        self.assertIn(b"A new chapter.", chapter.body)
        navigation = self.fetch(f"/get/extract/{self.bid}/toc.ncx", headers=headers)
        self.assertEqual(navigation.code, 200)
        self.assertIn(b"chapter.xhtml#c1", navigation.body)
        self.assertEqual(self.request(progress_url, role="user")["progress"], before_progress)
        self.assertEqual(self._app.settings["reading_counters"], [])

    def test_other_books_and_pdf_reading_are_unchanged(self):
        from calibre.ebooks.metadata.book.base import Metadata
        pdf = self.directory / "other.pdf"
        pdf.write_bytes(b"%PDF-1.4\n% isolated range fixture\n%%EOF\n")
        bid = self.db.import_book(Metadata("Other book", ["Another author"]), [str(pdf)])
        headers = {"X-Test-Role": "user"}
        url = f"/api/book/{bid}.pdf?mode=read"
        before = self.fetch(url, headers=headers)
        self.assertEqual(before.code, 200)
        self.assertEqual(before.headers["Content-Type"], "application/pdf")
        target = self.request()
        result = self.request(**self.multipart(target["revision"], str(uuid.uuid4())))
        self.assertEqual(result.get("state"), "completed", result)
        after = self.fetch(url, headers=headers)
        self.assertEqual(after.body, before.body)
        self.assertEqual(after.headers["Etag"], before.headers["Etag"])
        partial = self.fetch(url, headers={**headers, "Range": "bytes=0-7"})
        self.assertEqual(partial.code, 206)
        self.assertEqual(partial.body, before.body[:8])

    def test_reading_permissions_are_not_bypassed(self):
        from webserver.handlers import book, files
        with patch.dict(book.CONF, {"ALLOW_GUEST_DOWNLOAD": False}):
            denied = self.fetch(f"/api/book/{self.bid}.epub?mode=read", follow_redirects=False)
            self.assertEqual(denied.code, 302)
            self.assertEqual(denied.headers["Location"], "/login")
        with patch.dict(files.CONF, {"ALLOW_GUEST_READ": False}):
            denied = self.fetch(f"/get/extract/{self.bid}/chapter.xhtml", follow_redirects=False)
            self.assertEqual(denied.code, 302)
        self.assertEqual(self.request(f"/api/book/{self.bid}/progress", role=None)["err"], "user.need_login")


if __name__ == "__main__":
    main()
