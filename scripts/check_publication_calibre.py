"""Run with calibre-debug; touches only a new temporary ordinary-text library."""

import importlib.util
import tempfile
import uuid
from pathlib import Path

from calibre.db.legacy import LibraryDatabase
from calibre.ebooks.metadata.book.base import Metadata

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publication_tests", root / "tests/test_publication.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)

with tempfile.TemporaryDirectory(prefix="p-") as work:
    directory = Path(work)
    library = directory / "l"
    library.mkdir()
    epub = directory / "old.epub"
    epub.write_bytes(fixtures.make_epub())
    text = directory / "original.txt"
    text.write_text("The villagers inspect the old bridge.", encoding="utf-8")
    db = LibraryDatabase(str(library))
    try:
        bid = db.import_book(Metadata("Bridge", ["Test Author"]), [str(epub), str(text)])
        db.new_api.set_cover({bid: fixtures.make_cover()})
        service = fixtures.core.PublicationService(db.new_api, directory / "backups")
        old = service.inspect(bid)
        original_txt_hash = fixtures.core.file_digest(db.new_api.format_abspath(bid, "TXT"))
        metadata = {
            "title": "Bridge",
            "authors": ["Test Author"],
            "comments": "New complete chapter",
            "tags": ["ordinary", "bridge"],
            "languages": ["eng"],
        }
        request = str(uuid.uuid4())
        result = service.replace(
            bid,
            request,
            old["revision"],
            fixtures.make_epub("A new chapter."),
            metadata,
            fixtures.make_cover("blue"),
        )
        assert result["state"] == "completed", result
        assert fixtures.core.file_digest(db.new_api.format_abspath(bid, "TXT")) == original_txt_hash
        assert db.new_api.has_id(bid)
        assert service.status(bid, request)["state"] == "completed"
        assert (
            service.replace(
                bid,
                request,
                old["revision"],
                fixtures.make_epub("A new chapter."),
                metadata,
                fixtures.make_cover("blue"),
            )["state"]
            == "completed"
        )
        before_rollback = service.inspect(bid)
        original_set_cover = db.new_api.set_cover
        count = [0]

        def fail_once(values):
            original_set_cover(values)
            count[0] += 1
            if count[0] == 1:
                raise OSError("simulated cover failure")

        db.new_api.set_cover = fail_once
        try:
            service.replace(
                bid,
                str(uuid.uuid4()),
                before_rollback["revision"],
                fixtures.make_epub("Should roll back."),
                {**metadata, "comments": "Should roll back"},
                fixtures.make_cover("red"),
            )
            raise AssertionError("Expected rollback")
        except fixtures.core.PublicationError as error:
            assert error.code == "publication.rolled_back", error
        finally:
            db.new_api.set_cover = original_set_cover
        assert service.inspect(bid) == before_rollback
        print("Real Calibre: replacement, original TXT, stable ID, idempotency and rollback passed")
    finally:
        db.close()
