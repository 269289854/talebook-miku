import os
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"


def test_coverage_targets_report_current_webserver_package():
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert 'coverage report --include "webserver/*"' in makefile
    assert 'coverage html -d ".htmlcov" --include "webserver/*"' in makefile
    assert '"*talebook*"' not in makefile


def test_non_build_targets_do_not_probe_git_during_makefile_parse():
    env = os.environ.copy()
    env["PATH"] = ""
    result = subprocess.run(
        [shutil.which("make"), "-n", "init"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "git" not in result.stderr.lower()


def test_local_build_uses_lazy_branch_version_for_tags_and_build_arg():
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert "VER = $(shell git branch --show-current | tr '/' '-')" in makefile
    assert re.search(r"^GIT_VER\s*[:?+]?=", makefile, flags=re.MULTILINE) is None

    result = subprocess.run(
        [shutil.which("make"), "-n", "build-spa", "VER=feature-docker-slim"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "GIT_VERSION=feature-docker-slim" in result.stdout
    assert "ghcr.io/269289854/talebook-miku:feature-docker-slim" in result.stdout


def test_makefile_exposes_no_push_targets_or_commands():
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert re.search(r"^push(?:-base)?:", makefile, flags=re.MULTILINE) is None
    assert "docker push" not in makefile
    assert "--push" not in makefile


def test_makefile_exposes_no_base_image_build_targets():
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert re.search(r"^build-base:", makefile, flags=re.MULTILINE) is None
    assert "Dockerfile.base" not in makefile
    assert "BASE_VER" not in makefile
