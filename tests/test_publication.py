"""Ordinary, isolated publication replacement fixtures; no live server data."""

import copy
import importlib.util
import io
import json
import tempfile
import threading
import unittest
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("publication_core", ROOT / "webserver/services/publication.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def make_epub(text="The villagers inspect the old bridge."):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
            '<rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        archive.writestr(
            "book.opf",
            '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Bridge</dc:title>'
            "<dc:creator>Test Author</dc:creator><dc:language>en</dc:language>"
            '<dc:identifier id="bookid">bridge-test</dc:identifier></metadata>'
            '<manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>'
            '<spine toc="ncx"><itemref idref="chapter"/></spine></package>',
        )
        archive.writestr(
            "toc.ncx",
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            "<head/><docTitle><text>Bridge</text></docTitle><navMap>"
            '<navPoint id="c1" playOrder="1"><navLabel><text>Bridge inspection</text></navLabel>'
            '<content src="chapter.xhtml#c1"/></navPoint></navMap></ncx>',
        )
        archive.writestr(
            "chapter.xhtml",
            f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Bridge</title></head>'
            f'<body><h1 id="c1">Bridge inspection</h1><p>{text}</p></body></html>',
        )
    return stream.getvalue()


def make_cover(color="green"):
    stream = io.BytesIO()
    Image.new("RGB", (32, 48), color).save(stream, "JPEG")
    return stream.getvalue()


class FakeCache:
    def __init__(self, root):
        self.root = Path(root)
        self.backend = SimpleNamespace(library_path=str(self.root), set_cover=self.write_cover)
        self.meta = {
            "title": "Bridge",
            "authors": ["Test Author"],
            "comments": "Old",
            "tags": ["ordinary"],
            "languages": ["eng"],
            "uuid": "stable-id",
            "path": "Test Author/Bridge (7)",
        }
        self.formats_data = {"TXT": b"unchanged original", "EPUB": make_epub()}
        self.cover_data = make_cover()
        self.exists = True
        self.writes = 0
        self.fail_cover = 0
        self.write_lock = threading.RLock()

    def has_id(self, bid):
        return bid == 7 and self.exists

    def field_for(self, field, bid):
        return copy.deepcopy(self.meta[field])

    def formats(self, bid):
        return tuple(self.formats_data)

    def format_abspath(self, bid, fmt):
        if fmt not in self.formats_data:
            return None
        path = self.root / f"book.{fmt.lower()}"
        path.write_bytes(self.formats_data[fmt])
        return str(path)

    def cover(self, bid):
        return self.cover_data

    def set_field(self, field, values, **kwargs):
        self.meta[field] = copy.deepcopy(values[7])

    def add_format(self, bid, fmt, source, replace=True, run_hooks=True):
        self.writes += 1
        self.formats_data[fmt] = source.read() if hasattr(source, "read") else Path(source).read_bytes()
        return True

    def remove_formats(self, values):
        for fmt in values[7]:
            self.formats_data.pop(fmt, None)

    def set_cover(self, values):
        self.cover_data = values[7]
        if self.fail_cover:
            self.fail_cover -= 1
            raise OSError("simulated write failure")

    def write_cover(self, bid, path, data, no_processing=False):
        self.cover_data = data


class TestPublication(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="publication-unit-")
        self.addCleanup(self.directory.cleanup)
        self.cache = FakeCache(self.directory.name)
        self.service = core.PublicationService(self.cache, Path(self.directory.name) / "backups")
        self.target = self.service.inspect(7)
        self.request = str(uuid.uuid4())
        self.metadata = {key: self.cache.meta[key] for key in core.FIELDS}
        self.metadata = {**self.metadata, "comments": "New bridge chapter", "tags": ["ordinary", "bridge"]}
        self.epub = make_epub("They return to inspect the river bank.")
        self.cover = make_cover("blue")

    def replace(self, **changes):
        values = dict(
            book_id=7,
            request_id=self.request,
            expected_revision=self.target["revision"],
            epub=self.epub,
            metadata=self.metadata,
            cover=self.cover,
        )
        values.update(changes)
        return self.service.replace(**values)

    def test_replace_keeps_id_txt_and_backup(self):
        receipt = self.replace()
        self.assertEqual(receipt["state"], "completed")
        self.assertEqual(receipt["epub_hash"], core.digest(self.epub))
        self.assertTrue(self.cache.has_id(7))
        self.assertEqual(self.cache.formats_data["TXT"], b"unchanged original")
        self.assertEqual(self.cache.formats_data["EPUB"], self.epub)
        backup = self.service._directory(7, self.request)
        self.assertEqual((backup / "previous.epub").read_bytes(), make_epub())
        self.assertEqual(
            json.loads((backup / "previous.json").read_text("utf-8"))["metadata"]["comments"], "Old"
        )

    def test_completed_request_is_idempotent(self):
        self.replace()
        self.replace()
        self.assertEqual(self.cache.writes, 1)
        with self.assertRaisesRegex(core.PublicationError, "不一致"):
            self.replace(epub=make_epub("Different input."))

    def test_changed_target_requires_confirmation(self):
        self.cache.meta["comments"] = "Edited elsewhere"
        with self.assertRaisesRegex(core.PublicationError, "重新确认"):
            self.replace()
        self.assertEqual(self.cache.writes, 0)

    def test_failed_cover_write_restores_all_changes(self):
        before = self.service.inspect(7)
        self.cache.fail_cover = 1
        with self.assertRaisesRegex(core.PublicationError, "已恢复"):
            self.replace()
        self.assertEqual(self.service.inspect(7), before)
        self.assertEqual(self.service.status(7, self.request)["state"], "rolled_back")

    def test_failure_when_adding_first_epub_restores_absence(self):
        del self.cache.formats_data["EPUB"]
        self.target = self.service.inspect(7)
        self.cache.fail_cover = 1
        with self.assertRaises(core.PublicationError):
            self.replace()
        self.assertNotIn("EPUB", self.cache.formats_data)
        self.assertEqual(self.cache.formats_data["TXT"], b"unchanged original")

    def test_invalid_payloads_cannot_write(self):
        for changes in (
            {"epub": b"not epub"},
            {"request_id": "../../bad"},
            {"cover": b"\xff\xd8\xffbad"},
            {"metadata": {}},
            {"expected_revision": "bad"},
        ):
            with self.subTest(changes=list(changes)), self.assertRaises(core.PublicationError):
                self.replace(**changes)
        self.assertEqual(self.cache.writes, 0)

    def test_completed_but_later_changed_is_not_success(self):
        self.replace()
        self.cache.formats_data["EPUB"] = make_epub("Later external edit.")
        with self.assertRaisesRegex(core.PublicationError, "又有变化"):
            self.service.status(7, self.request)

    def test_interrupted_request_is_not_reapplied(self):
        self.replace()
        path = self.service._directory(7, self.request) / "receipt.json"
        receipt = json.loads(path.read_text("utf-8"))
        receipt["state"] = "applying"
        core.write_json(path, receipt)
        with self.assertRaisesRegex(core.PublicationError, "未完成"):
            self.replace()
        self.assertEqual(self.cache.writes, 1)

    def test_external_absolute_path_is_rejected_before_writing(self):
        self.cache.meta["path"] = str(self.cache.root.resolve())
        with self.assertRaisesRegex(core.PublicationError, "外部路径"):
            self.replace()
        self.assertEqual(self.cache.writes, 0)

    def test_language_metadata_is_not_silently_skipped(self):
        self.metadata["languages"] = ["zho"]
        self.replace()
        self.assertEqual(self.cache.meta["languages"], ["zho"])

    def test_silent_cover_write_failure_is_not_success(self):
        self.cache.set_cover = lambda values: None
        self.cache.backend.set_cover = lambda *args, **kwargs: None
        with self.assertRaisesRegex(core.PublicationError, "已恢复"):
            self.replace()
        self.assertEqual(self.service.status(7, self.request)["state"], "rolled_back")


if __name__ == "__main__":
    unittest.main()
