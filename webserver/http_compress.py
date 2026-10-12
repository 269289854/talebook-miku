"""HTTP compression transforms for Tornado."""

from tornado.web import GZipContentEncoding


class JsonGZipContentEncoding(GZipContentEncoding):
    """只压缩 JSON；书籍、TXT、图片及 Range 响应保持原样，避免破坏续传字节偏移。"""

    CONTENT_TYPES = {"application/json"}

    def _compressible_type(self, ctype: str) -> bool:
        if not ctype:
            return False
        return ctype.split(";")[0].strip().lower() == "application/json"

    def transform_first_chunk(self, status_code, headers, chunk, finishing):
        if status_code == 206 or "Content-Range" in headers:
            self._gzipping = False
        return super().transform_first_chunk(status_code, headers, chunk, finishing)
