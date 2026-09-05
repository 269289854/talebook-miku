"""Administrator-only, explicitly confirmed replacement of an existing book."""

import json
import logging
import os

from tornado.web import StaticFileHandler

from webserver import loader
from webserver.models import ScanFile
from webserver.services.publication import PublicationError, PublicationService

from .base import BaseHandler, auth, js


class BookPublication(BaseHandler):
    def _service(self, bid):
        if not self.is_admin() or not self.current_user.can_edit() or not self.current_user.can_upload():
            raise PublicationError("permission", "仅管理员可确认覆盖发布")
        if not self.db.new_api.has_id(bid):
            raise PublicationError("not_found", "服务器旧书已删除")
        rows = self.session.query(ScanFile).filter(ScanFile.book_id == bid).all()
        if any(isinstance(row.data, dict) and (row.data.get("external_path") or row.data.get("source_path")) for row in rows):
            raise PublicationError("publication.external", "外部路径索引书不支持覆盖，请先转入受管理书库")
        root = os.path.join(loader.get_settings()["convert_path"], "publication-backups")
        return PublicationService(self.db.new_api, root)

    @js
    @auth
    def get(self, bid):
        try:
            service = self._service(int(bid))
            request_id = self.get_argument("request_id", "")
            return service.status(int(bid), request_id) if request_id else service.inspect(int(bid))
        except PublicationError as error:
            return {"err": error.code, "msg": str(error)}

    @js
    @auth
    def post(self, bid):
        attempted = False
        try:
            service = self._service(int(bid))
            if self.get_argument("confirmed", "") != "true":
                raise PublicationError("publication.confirmation", "必须明确确认覆盖")
            ebooks = self.request.files.get("ebook", [])
            covers = self.request.files.get("cover", [])
            if len(ebooks) != 1 or len(covers) != 1:
                raise PublicationError("publication.invalid", "请选择一个 EPUB 和一张封面")
            raw_metadata = self.get_argument("metadata", "")
            if len(raw_metadata) > 100000:
                raise PublicationError("publication.invalid", "发布元数据过长")
            try:
                metadata = json.loads(raw_metadata)
            except ValueError as error:
                raise PublicationError("publication.invalid", "发布元数据不是 JSON") from error
            attempted = True
            return service.replace(
                int(bid),
                self.get_argument("request_id", ""),
                self.get_argument("expected_revision", ""),
                ebooks[0]["body"],
                metadata,
                covers[0]["body"],
            )
        except PublicationError as error:
            return {"err": error.code, "msg": str(error)}
        finally:
            if attempted:
                # Same-path EPUB replacement must not keep Tornado's old ETag.
                StaticFileHandler.reset()
                try:
                    self.db.data.refresh_ids([int(bid)])
                except Exception:
                    logging.exception("publication cache refresh failed for book %s", bid)


def routes():
    return [(r"/api/book/([0-9]+)/publication", BookPublication)]
