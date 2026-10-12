"""Apply the reviewed gzip/ETag delta to the fixed production snapshot."""

import ast
import sys
from pathlib import Path


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise SystemExit("Production source anchor changed")
    return source.replace(old, new, 1)


def main(root):
    path = root / "webserver/main.py"
    source = path.read_text(encoding="utf-8")
    if "JsonGZipContentEncoding" in source or "transforms=" in source:
        raise SystemExit("Compression transform is already configured")
    source = replace_once(
        source,
        "\nfrom tornado import web\n",
        "\nfrom tornado import web\nfrom webserver.http_compress import JsonGZipContentEncoding\n",
    )
    source = replace_once(
        source, "        **app_settings,\n", "        transforms=[JsonGZipContentEncoding],\n        **app_settings,\n"
    )
    tree = ast.parse(source)
    path.write_text(source, encoding="utf-8")
    assert tree
    path = root / "webserver/handlers/base.py"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "            if success_formats:\n",
        "            if success_formats:\n                web.StaticFileHandler.reset()\n",
    )
    ast.parse(source)
    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
