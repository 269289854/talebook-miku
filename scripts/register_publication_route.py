"""Add only the publication route to a pre-existing deployed handler registry."""

import ast
import sys
from pathlib import Path

path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
if "routes += publication.routes()" not in source:
    marker = "    routes += book.routes()\n"
    if source.count(marker) != 1:
        raise SystemExit("Unexpected deployed handler registry; no changes made")
    source = source.replace(
        marker, marker + "    from . import publication\n\n    routes += publication.routes()\n"
    )
    ast.parse(source)
    path.write_text(source, encoding="utf-8")
