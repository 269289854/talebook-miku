"""Confirmed, version-checked publication replacement with durable receipts."""

import hashlib
import io
import json
import os
import re
import shutil
import threading
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image


FIELDS = ("title", "authors", "comments", "tags", "languages")
MAX_EPUB = 64 * 1024 * 1024
_LOCK = threading.RLock()


class PublicationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def validate_epub(data):
    if not data or len(data) > MAX_EPUB:
        raise PublicationError("publication.invalid", "EPUB 为空或超过 64MB")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [item.filename for item in entries]
            if len(names) > 10000 or len(set(names)) != len(names):
                raise ValueError("duplicate or excessive ZIP entries")
            if sum(item.file_size for item in entries) > 256 * 1024 * 1024:
                raise ValueError("excessive uncompressed size")
            if archive.read("mimetype") != b"application/epub+zip":
                raise ValueError("invalid mimetype")
            container = archive.read("META-INF/container.xml")
            if len(container) > 1024 * 1024 or b"<!DOCTYPE" in container.upper():
                raise ValueError("invalid container XML")
            root = ElementTree.fromstring(container)
            roots = root.findall(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
            if not roots or roots[0].get("full-path") not in names:
                raise ValueError("missing package")
            package = archive.read(roots[0].get("full-path"))
            if len(package) > 4 * 1024 * 1024 or b"<!DOCTYPE" in package.upper():
                raise ValueError("invalid package XML")
            opf = ElementTree.fromstring(package)
            ns = "{http://www.idpf.org/2007/opf}"
            manifest = {item.get("id") for item in opf.findall(f"{ns}manifest/{ns}item")}
            spine = opf.findall(f"{ns}spine/{ns}itemref")
            if not spine or any(item.get("idref") not in manifest for item in spine):
                raise ValueError("invalid reading order")
            if archive.testzip() is not None:
                raise ValueError("corrupt ZIP data")
    except (ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError, RuntimeError) as error:
        raise PublicationError("publication.invalid", "EPUB 结构校验失败，未替换原文件") from error


def validate_metadata(metadata):
    if not isinstance(metadata, dict) or set(metadata) != set(FIELDS):
        raise PublicationError("publication.invalid", "发布元数据字段不完整")
    if not isinstance(metadata["title"], str) or not metadata["title"].strip() or len(metadata["title"]) > 500:
        raise PublicationError("publication.invalid", "书名无效")
    if not isinstance(metadata["comments"], str) or len(metadata["comments"]) > 50000:
        raise PublicationError("publication.invalid", "简介无效")
    for field in ("authors", "tags", "languages"):
        values = metadata[field]
        if not isinstance(values, list) or not values or len(values) > 100:
            raise PublicationError("publication.invalid", "作者、标签或语言无效")
        if any(not isinstance(value, str) or not value.strip() or len(value) > 500 for value in values):
            raise PublicationError("publication.invalid", "作者、标签或语言条目无效")


class PublicationService:
    """Uses Calibre's public cache API; never removes or recreates a book."""

    def __init__(self, cache, backup_root):
        self.cache = cache
        self.root = Path(backup_root)

    def _directory(self, book_id, request_id):
        if not re.fullmatch(r"[a-f0-9-]{36}", request_id or ""):
            raise PublicationError("publication.invalid", "请求编号无效")
        return self.root / str(int(book_id)) / request_id

    def _state(self, book_id):
        if not self.cache.has_id(book_id):
            raise PublicationError("not_found", "服务器旧书已删除")
        self._ensure_managed(book_id)
        path = self.cache.format_abspath(book_id, "EPUB")
        cover = self.cache.cover(book_id)
        return {
            "uuid": self.cache.field_for("uuid", book_id),
            "metadata": {field: self.cache.field_for(field, book_id) for field in FIELDS},
            "epub_hash": file_digest(path) if path else None,
            "cover_hash": digest(cover) if cover else None,
        }

    def _ensure_managed(self, book_id):
        root = Path(self.cache.backend.library_path).resolve()
        relative = self.cache.field_for("path", book_id)
        if not relative or Path(relative).is_absolute():
            raise PublicationError("publication.external", "外部路径索引书不支持覆盖")
        directory = (root / relative).resolve()
        paths = [directory, (directory / "cover.jpg").resolve()]
        paths.extend(
            Path(path).resolve() for fmt in self.cache.formats(book_id) if (path := self.cache.format_abspath(book_id, fmt))
        )
        if any(path == root or not path.is_relative_to(root) for path in paths):
            raise PublicationError("publication.external", "书籍文件不在受管理书库内，未覆盖")

    def inspect(self, book_id):
        with _LOCK, self.cache.write_lock:
            state = self._state(book_id)
            return {
                "err": "ok",
                "version": 1,
                "book_id": book_id,
                "title": state["metadata"]["title"],
                "authors": list(state["metadata"]["authors"]),
                "formats": list(self.cache.formats(book_id)),
                "revision": digest(json_bytes(state)),
                "epub_hash": state["epub_hash"],
            }

    def status(self, book_id, request_id):
        with _LOCK, self.cache.write_lock:
            path = self._directory(book_id, request_id) / "receipt.json"
            if not path.exists():
                return {"err": "ok", "state": "absent"}
            receipt = json.loads(path.read_text("utf-8"))
            result = {"err": "ok", **{key: receipt[key] for key in ("state", "input_hash", "epub_hash")}}
            if receipt["state"] == "completed":
                state = self._state(book_id)
                if digest(json_bytes(state)) != receipt["result_revision"]:
                    raise PublicationError("publication.changed", "发布后远端内容又有变化，请重新确认")
            return result

    def _set_metadata(self, book_id, values):
        for field in FIELDS:
            self.cache.set_field(field, {book_id: values[field]}, allow_case_change=False)

    def _set_cover(self, book_id, data):
        self.cache.set_cover({book_id: data})
        if data is not None:
            # The cache API refreshes cover metadata and thumbnails. Older
            # Calibre versions recompress JPEGs there; preserve validated bytes
            # under the same write lock using its lossless backend setter.
            self.cache.backend.set_cover(book_id, self.cache.field_for("path", book_id), data, no_processing=True)

    def _restore(self, book_id, directory, old):
        self._set_metadata(book_id, old["metadata"])
        if old["epub_hash"]:
            with (directory / "previous.epub").open("rb") as stream:
                self.cache.add_format(book_id, "EPUB", stream, replace=True, run_hooks=False)
        else:
            self.cache.remove_formats({book_id: ["EPUB"]})
        cover = (directory / "previous.cover").read_bytes() if old["cover_hash"] else None
        self._set_cover(book_id, cover)
        if digest(json_bytes(self._state(book_id))) != digest(json_bytes(old)):
            raise PublicationError("publication.rollback_failed", "回滚校验失败，请使用服务器备份恢复")

    def replace(self, book_id, request_id, expected_revision, epub, metadata, cover):
        validate_epub(epub)
        validate_metadata(metadata)
        if not cover or len(cover) > 5 * 1024 * 1024 or not cover.startswith(b"\xff\xd8\xff"):
            raise PublicationError("publication.invalid", "封面必须是 5MB 以内的 JPEG")
        try:
            with Image.open(io.BytesIO(cover)) as image:
                if image.format != "JPEG" or image.width * image.height > 20_000_000:
                    raise ValueError("invalid cover dimensions")
                image.verify()
        except (ValueError, OSError, Image.DecompressionBombError) as error:
            raise PublicationError("publication.invalid", "封面校验失败，未替换") from error
        if not re.fullmatch(r"[a-f0-9]{64}", expected_revision or ""):
            raise PublicationError("publication.invalid", "缺少确认版本")
        epub_hash = digest(epub)
        input_hash = digest(json_bytes([expected_revision, epub_hash, metadata, digest(cover)]))
        directory = self._directory(book_id, request_id)
        with _LOCK, self.cache.write_lock:
            receipt_path = directory / "receipt.json"
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text("utf-8"))
                if receipt["input_hash"] != input_hash:
                    raise PublicationError("publication.conflict", "同一请求编号的发布内容不一致")
                if receipt["state"] == "completed":
                    return self.status(book_id, request_id)
                raise PublicationError("publication.interrupted", "旧覆盖请求未完成，请核对备份后重新确认；未自动重传")
            state = self._state(book_id)
            if digest(json_bytes(state)) != expected_revision:
                raise PublicationError("publication.conflict", "确认后服务器内容已变化，请重新确认覆盖")
            if directory.exists():
                raise PublicationError("publication.interrupted", "上次备份未完成，请重新确认发布")
            directory.mkdir(parents=True, exist_ok=False)
            write_json(directory / "previous.json", state)
            if state["epub_hash"]:
                shutil.copy2(self.cache.format_abspath(book_id, "EPUB"), directory / "previous.epub")
            if state["cover_hash"]:
                (directory / "previous.cover").write_bytes(self.cache.cover(book_id))
            if (state["epub_hash"] and file_digest(directory / "previous.epub") != state["epub_hash"]) or (
                state["cover_hash"] and file_digest(directory / "previous.cover") != state["cover_hash"]
            ):
                raise PublicationError("publication.backup_failed", "备份校验失败，未覆盖")
            receipt = {"state": "applying", "input_hash": input_hash, "epub_hash": epub_hash}
            write_json(receipt_path, receipt)
            try:
                self._set_metadata(book_id, metadata)
                if not self.cache.add_format(book_id, "EPUB", io.BytesIO(epub), replace=True, run_hooks=False):
                    raise PublicationError("publication.write_failed", "EPUB 未写入")
                self._set_cover(book_id, cover)
                current = self._state(book_id)
                if current["epub_hash"] != epub_hash:
                    raise PublicationError("publication.write_failed", "EPUB 写入后哈希不一致")
                for field in FIELDS:
                    actual, expected = current["metadata"][field], metadata[field]
                    if field in ("tags", "languages"):
                        actual, expected = set(actual), set(expected)
                    elif field == "authors":
                        actual, expected = list(actual), list(expected)
                    if actual != expected:
                        raise PublicationError("publication.write_failed", "元数据写入校验失败")
                if current["cover_hash"] != digest(cover):
                    raise PublicationError("publication.write_failed", "封面写入校验失败")
                receipt.update(state="completed", result_revision=digest(json_bytes(current)))
                write_json(receipt_path, receipt)
            except Exception as error:
                try:
                    self._restore(book_id, directory, state)
                    receipt["state"] = "rolled_back"
                except Exception:
                    receipt["state"] = "rollback_failed"
                    write_json(receipt_path, receipt)
                    raise PublicationError(
                        "publication.rollback_failed", "覆盖失败且回滚未完成，请使用服务器备份恢复"
                    ) from error
                write_json(receipt_path, receipt)
                raise PublicationError(
                    "publication.rolled_back", "覆盖失败，已恢复旧文件和元数据；请重新确认后再试"
                ) from error
            return self.status(book_id, request_id)
