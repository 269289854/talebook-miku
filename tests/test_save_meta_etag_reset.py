"""Tests for StaticFileHandler.reset call in BaseHandler.save_book_meta."""

import os
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from tornado import web


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from webserver.handlers.base import BaseHandler


class SaveMetaEtagResetTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.epub_file = os.path.join(self.tmp_dir.name, "book.epub")
        with open(self.epub_file, "wb") as f:
            f.write(b"fake epub content")

        self.fake_mi = SimpleNamespace(
            title="Sample Book",
            authors=["Sample Author"],
            comments="Sample Comments",
            title_sort=None,
            author_sort=None,
            cover_data=None,
        )

        self.fake_db = mock.Mock()
        self.fake_db.get_metadata.return_value = self.fake_mi
        self.fake_db.cover.return_value = b"sample cover data"

        self.fake_handler = SimpleNamespace(
            session=mock.Mock(),
            db=self.fake_db,
            get_book=mock.Mock(return_value={"id": 1, "fmt_epub": self.epub_file}),
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_save_meta_resets_static_file_etag_on_success(self):
        mock_meta_module = types.ModuleType("calibre.ebooks.metadata.meta")
        mock_set_metadata = mock.Mock()
        mock_meta_module.set_metadata = mock_set_metadata

        mock_modules = {
            "calibre": types.ModuleType("calibre"),
            "calibre.ebooks": types.ModuleType("calibre.ebooks"),
            "calibre.ebooks.metadata": types.ModuleType("calibre.ebooks.metadata"),
            "calibre.ebooks.metadata.meta": mock_meta_module,
        }

        with (
            mock.patch.dict(sys.modules, mock_modules),
            mock.patch("webserver.handlers.base.is_external_index_format", return_value=False, create=True),
            mock.patch.object(web.StaticFileHandler, "reset") as mock_reset,
        ):
            res = BaseHandler.save_book_meta(self.fake_handler, 1)

            self.assertEqual(res.get("err"), "ok")
            mock_set_metadata.assert_called_once()
            mock_reset.assert_called_once()

    def test_save_meta_does_not_reset_etag_on_failure(self):
        mock_meta_module = types.ModuleType("calibre.ebooks.metadata.meta")
        mock_set_metadata = mock.Mock(side_effect=RuntimeError("Metadata write failed"))
        mock_meta_module.set_metadata = mock_set_metadata

        mock_modules = {
            "calibre": types.ModuleType("calibre"),
            "calibre.ebooks": types.ModuleType("calibre.ebooks"),
            "calibre.ebooks.metadata": types.ModuleType("calibre.ebooks.metadata"),
            "calibre.ebooks.metadata.meta": mock_meta_module,
        }

        with (
            mock.patch.dict(sys.modules, mock_modules),
            mock.patch("webserver.handlers.base.is_external_index_format", return_value=False, create=True),
            mock.patch.object(web.StaticFileHandler, "reset") as mock_reset,
        ):
            res = BaseHandler.save_book_meta(self.fake_handler, 1)

            self.assertEqual(res.get("err"), "save.failed")
            mock_reset.assert_not_called()

    def test_real_etag_changes_after_metadata_write(self):
        before = web.StaticFileHandler.get_content_version(self.epub_file)
        module = types.ModuleType("calibre.ebooks.metadata.meta")

        def write_metadata(stream, metadata, stream_type):
            stream.seek(0)
            stream.write(b"updated epub metadata")
            stream.truncate()

        module.set_metadata = write_metadata
        with (
            mock.patch.dict(sys.modules, {"calibre.ebooks.metadata.meta": module}),
            mock.patch("webserver.handlers.base.is_external_index_format", return_value=False, create=True),
        ):
            result = BaseHandler.save_book_meta(self.fake_handler, 1)
        self.assertEqual(result["err"], "ok")
        after = web.StaticFileHandler.get_content_version(self.epub_file)
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
