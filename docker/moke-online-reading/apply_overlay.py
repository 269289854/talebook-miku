#!/usr/bin/env python3
import hashlib
import py_compile
import sys
from pathlib import Path


BASELINE_SHA256 = "f566363fd4f9afbe44503da6aca7f963defd83647bc33032bcfa84abd0343001"
LIST_HANDLER_BASELINE_SHA256 = "b94d3e0a461ad38c840cac1802a941f92e1041508e7754b90dfc5b5d682017b9"
NGINX_BASELINE_SHA256 = "1559c0a08b67205a3987025775ce440e00527725b8d01871d5e6611732afeb99"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: apply_overlay.py <book.py> <base.py> <talebook.conf>")
    path = Path(sys.argv[1])
    list_handler_path = Path(sys.argv[2])
    nginx_path = Path(sys.argv[3])
    original = path.read_bytes()
    actual = hashlib.sha256(original).hexdigest()
    if actual != BASELINE_SHA256:
        raise RuntimeError(f"unexpected production handler checksum: {actual}")
    list_handler_original = list_handler_path.read_bytes()
    list_handler_actual = hashlib.sha256(list_handler_original).hexdigest()
    if list_handler_actual != LIST_HANDLER_BASELINE_SHA256:
        raise RuntimeError(f"unexpected production list handler checksum: {list_handler_actual}")
    nginx_original = nginx_path.read_bytes()
    nginx_actual = hashlib.sha256(nginx_original).hexdigest()
    if nginx_actual != NGINX_BASELINE_SHA256:
        raise RuntimeError(f"unexpected production nginx checksum: {nginx_actual}")

    text = original.decode("utf-8")
    text = replace_once(
        text,
        """        self.is_opds = self.get_argument("from", "") == "opds"\n        BaseHandler.initialize(self)""",
        """        self.is_opds = self.get_argument("from", "") == "opds"\n        self.is_read_mode = self.get_argument("mode", "").lower() == "read"\n        self.download_content_type = "application/octet-stream"\n        self.download_content_disposition = None\n        BaseHandler.initialize(self)""",
        "initialize read mode",
    )
    text = replace_once(
        text,
        """        self.user_history("download_history", book)\n        self.count_increase(book_id, count_download=1)""",
        """        if not self.is_read_mode:\n            self.user_history("download_history", book)\n            self.count_increase(book_id, count_download=1)""",
        "suppress download side effects",
    )
    text = replace_once(
        text,
        """        path = book["fmt_%s" % fmt]""",
        """        if self.is_read_mode and fmt not in ("epub", "pdf"):\n            raise web.HTTPError(415, reason=_("%s格式暂不支持在线阅读" % fmt))\n\n        path = book["fmt_%s" % fmt]""",
        "online format allowlist",
    )

    header_start = text.index("        # PDF ", text.index("class BookDownload"))
    header_end = text.index("        return path", header_start)
    header_block = """        if self.is_read_mode:\n            self.download_content_type = "application/pdf" if fmt == "pdf" else "application/epub+zip"\n            self.download_content_disposition = f'inline; filename="{fname}"'.encode("UTF-8")\n        elif fmt == "pdf":\n            self.download_content_type = "application/pdf"\n            if not self.is_opds:\n                self.download_content_disposition = f'inline; filename="{fname}"'.encode("UTF-8")\n            else:\n                self.download_content_disposition = att.encode("UTF-8")\n        else:\n            self.download_content_disposition = att.encode("UTF-8")\n"""
    text = text[:header_start] + header_block + text[header_end:]
    text = replace_once(
        text,
        """    @classmethod\n    def get_absolute_path(cls, root: str, path: str) -> str:""",
        """    def set_extra_headers(self, path: str) -> None:\n        self.set_header("Content-Type", self.download_content_type)\n        if self.download_content_disposition:\n            self.set_header("Content-Disposition", self.download_content_disposition)\n        if self.is_read_mode:\n            self.set_header("Cache-Control", "private, no-cache")\n\n    @classmethod\n    def get_absolute_path(cls, root: str, path: str) -> str:""",
        "late static response headers",
    )
    text = replace_once(
        text,
        """class LibraryBook(ListHandler):
    @js
    async def get(self):
        title = _("书库")

        publisher = self.get_argument("publisher", None)
        author = self.get_argument("author", None)
        tag = self.get_argument("tag", None)
        book_format = self.get_argument("format", None)
        stream = self.get_argument("stream", None)

        ids = self.books_by_id()

        if publisher and publisher != "全部":
            publisher_books = self.db.search_getting_ids(f"publisher:'{publisher}'", "")
            ids = list(set(ids) & set(publisher_books))

        if author and author != "全部":
            author_books = self.db.search_getting_ids(f"author:'{author}'", "")
            ids = list(set(ids) & set(author_books))

        if tag and tag != "全部":
            tag_books = self.db.search_getting_ids(f"tag:'{tag}'", "")
            ids = list(set(ids) & set(tag_books))

        if book_format and book_format != "全部":
            books = self.get_books(ids=ids)
            ids = [book["id"] for book in books if f"fmt_{book_format.lower()}" in book]

        if stream == "1":
            return await self.stream_book_list([], ids=ids, title=title, sort_by_id=True)

        return self.render_book_list([], ids=ids, title=title, sort_by_id=True)
""",
        """class LibraryBook(ListHandler):
    @js
    async def get(self):
        title = _("书库")

        publisher = self.get_argument("publisher", None)
        author = self.get_argument("author", None)
        tag = self.get_argument("tag", None)
        book_format = self.get_argument("format", None)
        stream = self.get_argument("stream", None)
        order = self.get_argument("order", "desc").lower()
        if order not in ("asc", "desc"):
            order = "desc"

        ids = self.books_by_id()

        if publisher and publisher != "全部":
            publisher_books = self.db.search_getting_ids(f"publisher:'{publisher}'", "")
            publisher_ids = set(publisher_books)
            ids = [book_id for book_id in ids if book_id in publisher_ids]

        if author and author != "全部":
            author_books = self.db.search_getting_ids(f"author:'{author}'", "")
            author_ids = set(author_books)
            ids = [book_id for book_id in ids if book_id in author_ids]

        if tag and tag != "全部":
            tag_books = self.db.search_getting_ids(f"tag:'{tag}'", "")
            tag_ids = set(tag_books)
            ids = [book_id for book_id in ids if book_id in tag_ids]

        if book_format and book_format != "全部":
            books = self.get_books(ids=ids)
            ids = [book["id"] for book in books if f"fmt_{book_format.lower()}" in book]

        ids.sort(reverse=order == "desc")
        id_ascending = order == "asc"
        if stream == "1":
            return await self.stream_book_list(
                [], ids=ids, title=title, sort_by_id=True, id_ascending=id_ascending
            )

        return self.render_book_list([], ids=ids, title=title, sort_by_id=True, id_ascending=id_ascending)
""",
        "add global library id ordering",
    )

    list_handler_text = list_handler_original.decode("utf-8")
    list_handler_text = replace_once(
        list_handler_text,
        """    def render_book_list(self, all_books, ids=None, title=None, sort_by_id=False):""",
        """    def render_book_list(self, all_books, ids=None, title=None, sort_by_id=False, id_ascending=False):""",
        "add JSON list order argument",
    )
    list_handler_text = replace_once(
        list_handler_text,
        """            if sort_by_id:
                # 归一化，按照 id 从大到小排列。
                self.do_sort(books, "id", False)""",
        """            if sort_by_id:
                self.do_sort(books, "id", id_ascending)""",
        "apply JSON list order",
    )
    list_handler_text = replace_once(
        list_handler_text,
        """    async def stream_book_list(self, all_books, ids=None, title=None, sort_by_id=False):""",
        """    async def stream_book_list(self, all_books, ids=None, title=None, sort_by_id=False, id_ascending=False):""",
        "add stream list order argument",
    )
    list_handler_text = replace_once(
        list_handler_text,
        """            if sort_by_id:
                self.do_sort(books, "id", False)""",
        """            if sort_by_id:
                self.do_sort(books, "id", id_ascending)""",
        "apply stream list order",
    )

    nginx_text = nginx_original.decode("utf-8")
    nginx_text = replace_once(
        nginx_text,
        "server {" + chr(10),
        (
            "map $arg_mode $moke_book_cache_control {"
            + chr(10)
            + "    default no-cache;"
            + chr(10)
            + '    read "private, no-cache";'
            + chr(10)
            + "}"
            + chr(10)
            + chr(10)
            + "server {"
            + chr(10)
        ),
        "add online reading cache policy map",
    )
    nginx_text = replace_once(
        nginx_text,
        "    location ~ ^/(api|get|read|opds|auth|books|media)/ {" + chr(10),
        (
            "    location ~ ^/api/book/[0-9]+\\.[^/]+$ {"
            + chr(10)
            + "        expires off;"
            + chr(10)
            + "        proxy_hide_header Cache-Control;"
            + chr(10)
            + "        proxy_hide_header Expires;"
            + chr(10)
            + "        add_header Cache-Control $moke_book_cache_control always;"
            + chr(10)
            + "        proxy_pass       http://tornado;"
            + chr(10)
            + "        proxy_redirect   off;"
            + chr(10)
            + "        proxy_set_header Host $http_host;"
            + chr(10)
            + "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;"
            + chr(10)
            + "        proxy_set_header X-Scheme $req_scheme;"
            + chr(10)
            + "    }"
            + chr(10)
            + chr(10)
            + "    location ~ ^/(api|get|read|opds|auth|books|media)/ {"
            + chr(10)
        ),
        "add online reading cache policy location",
    )

    path.write_text(text, encoding="utf-8")
    list_handler_path.write_text(list_handler_text, encoding="utf-8")
    nginx_path.write_text(nginx_text, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)
    py_compile.compile(str(list_handler_path), doraise=True)
    print("patched_sha256=" + hashlib.sha256(path.read_bytes()).hexdigest())
    print("list_handler_patched_sha256=" + hashlib.sha256(list_handler_path.read_bytes()).hexdigest())
    print("nginx_patched_sha256=" + hashlib.sha256(nginx_path.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
