"""Add Moke device-login support to an existing deployed TaleBook snapshot."""

import ast
import sys
from pathlib import Path


def replace_once(source, old, new, label):
    count = source.count(old)
    if count != 1:
        raise SystemExit("Unexpected %s marker count: %d" % (label, count))
    return source.replace(old, new, 1)


def patch_models(path):
    source = path.read_text(encoding="utf-8")
    if "class ReaderApiKey(" in source:
        raise SystemExit("ReaderApiKey is already registered")

    source = replace_once(
        source,
        "from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint\n",
        "from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint\n",
        "SQLAlchemy import",
    )
    model = """class ReaderApiKey(Base, SQLAlchemyMixin):
    __tablename__ = "reader_api_keys"

    id = Column(Integer, primary_key=True)
    reader_id = Column(Integer, ForeignKey("readers.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(String(200), nullable=False)
    name = Column(String(200), default="", nullable=False)
    prefix = Column(String(32), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    purpose = Column(String(32), default="device_login", nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.now, nullable=False)
    last_used_at = Column(DateTime)
    expires_at = Column(DateTime)
    revoked_at = Column(DateTime)

    reader = relationship(Reader, backref="api_keys")

    __table_args__ = (
        Index("ix_reader_api_keys_reader_active", "reader_id", "revoked_at"),
        Index("ix_reader_api_keys_prefix", "prefix"),
    )


"""
    source = replace_once(
        source, "class Message(Base, SQLAlchemyMixin):\n", model + "class Message(Base, SQLAlchemyMixin):\n", "Message model"
    )
    ast.parse(source)
    path.write_text(source, encoding="utf-8")


def patch_migration(path):
    source = path.read_text(encoding="utf-8")
    marker = "    model_columns = get_model_columns()\n    db_columns = get_database_columns(engine)\n\n"
    addition = """    model_columns = get_model_columns()
    db_columns = get_database_columns(engine)

    # New feature tables must be created with all constraints and indexes.
    missing_tables = [table for table in models.Base.metadata.sorted_tables if table.name not in db_columns]
    for table in missing_tables:
        logger.info("Creating missing table '%s'", table.name)
        table.create(engine, checkfirst=True)

    if missing_tables:
        db_columns = get_database_columns(engine)

"""
    source = replace_once(source, marker, addition, "migration prelude")
    source = replace_once(
        source,
        """        if table_name not in db_columns:
            logger.info(f"Table '{table_name}' does not exist, will be created later")
            continue
""",
        """        if table_name not in db_columns:
            logger.error("Table '%s' is still missing after table creation", table_name)
            return False
""",
        "missing-table validation",
    )
    ast.parse(source)
    path.write_text(source, encoding="utf-8")


def patch_user(path):
    source = path.read_text(encoding="utf-8")
    if "class ApiKeySignIn(" in source:
        raise SystemExit("Device API key handlers are already registered")

    source = replace_once(
        source,
        "from webserver import demo_mode, loader, utils\n",
        """from webserver import demo_mode, loader, utils
from webserver.device_api_keys import (
    DeviceApiKeyLimitError,
    authenticate_api_key,
    issue_api_key,
    serialize_api_key,
)
""",
        "device API key import",
    )
    source = replace_once(
        source,
        "from webserver.models import Device, Message, Reader\n",
        "from webserver.models import Device, Message, Reader, ReaderApiKey\n",
        "ReaderApiKey import",
    )
    source = replace_once(
        source,
        "class SignIn(BaseHandler):\n    @js\n",
        "class SignIn(BaseHandler):\n    def should_be_invited(self):\n        pass\n\n    @js\n",
        "password sign-in invite bypass",
    )
    source = replace_once(
        source,
        """        self.login_user(user)
        return {"err": "ok", "msg": "ok"}


class UserReset(BaseHandler):
""",
        """        remember_device = self.get_argument("remember_device", "").strip().lower() in ("1", "true", "yes", "on")
        api_key = None
        api_key_info = None
        if remember_device:
            try:
                issued_key, api_key = issue_api_key(
                    self.session,
                    user.id,
                    self.get_argument("device_id", ""),
                    self.get_argument("device_name", ""),
                )
                api_key_info = serialize_api_key(issued_key)
            except ValueError:
                return {"err": "params.device.invalid", "msg": _("设备信息无效")}
            except DeviceApiKeyLimitError:
                return {"err": "api_key.limit", "msg": _("设备密钥数量已达上限")}

        self.mark_invited()
        self.login_user(user)
        response = {"err": "ok", "msg": "ok"}
        if api_key:
            response["api_key"] = api_key
            response["api_key_info"] = api_key_info
        return response


class ApiKeySignIn(BaseHandler):
    def should_be_invited(self):
        pass

    @js
    def post(self):
        authorization = self.request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return {"err": "api_key.invalid", "msg": _("设备密钥无效或已吊销")}

        api_key = authenticate_api_key(self.session, authorization[7:].strip())
        if not api_key:
            return {"err": "api_key.invalid", "msg": _("设备密钥无效或已吊销")}

        user = self.session.get(Reader, api_key.reader_id)
        if not user or not demo_mode.can_login(CONF, user) or not user.can_login():
            return {"err": "api_key.invalid", "msg": _("设备密钥无效或已吊销")}

        api_key.last_used_at = datetime.datetime.now()
        self.mark_invited()
        self.login_user(user)
        self.session.commit()
        return {"err": "ok", "msg": "ok", "api_key_info": serialize_api_key(api_key)}


class UserApiKeys(BaseHandler):
    @js
    @auth
    def get(self):
        api_keys = (
            self.session.query(ReaderApiKey)
            .filter(ReaderApiKey.reader_id == self.user_id(), ReaderApiKey.revoked_at.is_(None))
            .order_by(ReaderApiKey.created_at.desc())
            .all()
        )
        return {"err": "ok", "api_keys": [serialize_api_key(api_key) for api_key in api_keys]}

    @js
    @auth
    def post(self):
        password = self.get_argument("password", "").strip()
        if not password or self.current_user.get_secure_password(password) != self.current_user.password:
            return {"err": "params.password.error", "msg": _("当前密码错误")}

        try:
            api_key, token = issue_api_key(
                self.session,
                self.current_user.id,
                self.get_argument("device_id", ""),
                self.get_argument("device_name", ""),
            )
        except ValueError:
            return {"err": "params.device.invalid", "msg": _("设备信息无效")}
        except DeviceApiKeyLimitError:
            return {"err": "api_key.limit", "msg": _("设备密钥数量已达上限")}
        return {"err": "ok", "msg": "ok", "api_key": token, "api_key_info": serialize_api_key(api_key)}


class UserApiKeyItem(BaseHandler):
    @js
    @auth
    def delete(self, api_key_id):
        api_key = (
            self.session.query(ReaderApiKey)
            .filter(
                ReaderApiKey.id == int(api_key_id),
                ReaderApiKey.reader_id == self.user_id(),
                ReaderApiKey.revoked_at.is_(None),
            )
            .first()
        )
        if not api_key:
            return {"err": "api_key.not_found", "msg": _("设备密钥不存在")}
        api_key.revoked_at = datetime.datetime.now()
        self.session.commit()
        return {"err": "ok", "msg": "ok"}


class UserReset(BaseHandler):
""",
        "device API key handlers",
    )
    source = replace_once(
        source,
        """    @js
    def get(self):
        if not self.need_invited():
            return {"err": "free", "msg": _("无需访问码")}
        if self.invited_code_is_ok():
            return {"err": "free", "msg": _("已输入访问码")}
        return {"err": "ok", "msg": "", "welcome": CONF["INVITE_MESSAGE"]}
""",
        """    @js
    def get(self):
        auth_capabilities = {"password_login": True, "device_api_key": True}
        if not self.need_invited():
            return {"err": "free", "msg": _("无需访问码"), "auth": auth_capabilities}
        if self.invited_code_is_ok():
            return {"err": "free", "msg": _("已输入访问码"), "auth": auth_capabilities}
        return {"err": "ok", "msg": "", "welcome": CONF["INVITE_MESSAGE"], "auth": auth_capabilities}
""",
        "welcome capabilities",
    )
    source = replace_once(
        source,
        """        (r"/api/user/sign_in", SignIn),
        (r"/api/user/sign_up", SignUp),
""",
        """        (r"/api/user/sign_in", SignIn),
        (r"/api/user/api_key/sign_in", ApiKeySignIn),
        (r"/api/user/api_keys", UserApiKeys),
        (r"/api/user/api_keys/([0-9]+)", UserApiKeyItem),
        (r"/api/user/sign_up", SignUp),
""",
        "device API key routes",
    )
    ast.parse(source)
    path.write_text(source, encoding="utf-8")


def main():
    root = Path(sys.argv[1])
    patch_models(root / "webserver/models.py")
    patch_migration(root / "webserver/migrate_db.py")
    patch_user(root / "webserver/handlers/user.py")


if __name__ == "__main__":
    main()
