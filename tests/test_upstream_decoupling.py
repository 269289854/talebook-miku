"""防止运行、构建与发布配置重新依赖上游 talebook/talebook 及原作者账号。

README、方案文档、调研资料等记录历史或致谢的文本不在扫描范围内；
随仓库分发的第三方阅读器产物（app/public/static）也不扫描。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCANNED_GLOBS = (
    "webserver/**/*.py",
    "app/components/**/*.vue",
    "app/pages/**/*.vue",
    "app/layouts/**/*.vue",
    "app/composables/**/*.ts",
    "app/plugins/**/*.js",
    "app/plugins/**/*.ts",
    "app/stores/**/*.ts",
    "app/utils/**/*.ts",
    "app/i18n/**/*.json",
    "app/nuxt.config.ts",
    "packages/theme-builder/templates/**/*",
    "Dockerfile",
    "Makefile",
    "docker-compose*.yml",
    "kubernetes/*.yaml",
    "requirements.txt",
    ".gitmodules",
    ".github/workflows/*.yml",
    "SECURITY.md",
)

FORBIDDEN = {
    "上游仓库链接": re.compile(r"github\.com/talebook/talebook(?!-base)"),
    "上游 Docker Hub": re.compile(r"hub\.docker\.com/r/talebook"),
    "上游官网与在线服务": re.compile(r"talebook\.org"),
    "原作者账号": re.compile(r"hehetoshang"),
    "上游 voicebook 仓库": re.compile(r"talebook/voicebook"),
    "上游专属镜像名": re.compile(r"talebook/calibre-webserver"),
    "上游镜像": re.compile(r"(?<![\w./-])talebook/talebook(?:-base)?(?=[:\s\"'`@]|$)", re.MULTILINE),
}

# (文件, 行内必须包含的片段)：明确允许的少数引用。
ALLOWED = {
    # 历史 issue 链接，用于说明该段代码的由来。
    ("webserver/utils.py", "issues/304"),
    # 基础镜像同步流水线必须写明复制来源。
    (".github/workflows/mirror-base-image.yml", "talebook/talebook-base"),
    ("Dockerfile", "上游 talebook/talebook-base"),
}


def scanned_files():
    seen = set()
    for pattern in SCANNED_GLOBS:
        for path in ROOT.glob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def test_runtime_build_and_release_files_do_not_reference_upstream():
    violations = []
    for path in scanned_files():
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for label, pattern in FORBIDDEN.items():
                if not pattern.search(line):
                    continue
                if any(rel == allowed_file and snippet in line for allowed_file, snippet in ALLOWED):
                    continue
                violations.append(f"{rel}:{lineno} [{label}] {line.strip()[:120]}")

    assert violations == []


def test_scan_covers_the_main_runtime_and_release_inputs():
    scanned = {path.relative_to(ROOT).as_posix() for path in scanned_files()}

    for required in (
        "webserver/settings.py",
        "webserver/services/update_checker.py",
        "app/components/AppFooter.vue",
        "Dockerfile",
        "Makefile",
        "docker-compose.yml",
        "requirements.txt",
        ".gitmodules",
        ".github/workflows/build.yml",
        ".github/workflows/ci.yml",
    ):
        assert required in scanned


def test_online_service_defaults_do_not_point_to_upstream():
    settings = (ROOT / "webserver" / "settings.py").read_text(encoding="utf-8")

    assert re.search(r'"CANDLE_READER_SERVER":\s*"",', settings)
    assert re.search(r"'smtp_server'\s*:\s*\"\",", settings)
    assert re.search(r"'smtp_username'\s*:\s*\"\",", settings)
    assert "'FEEDBACK_URL' : 'https://github.com/269289854/talebook-miku/issues'," in settings


def test_update_checker_follows_this_repository_releases():
    checker = (ROOT / "webserver" / "services" / "update_checker.py").read_text(encoding="utf-8")

    assert 'GITHUB_REPO = "269289854/talebook-miku"' in checker


def test_code_dependencies_are_pinned_to_the_owner_forks():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    gitmodules = (ROOT / ".gitmodules").read_text(encoding="utf-8")

    assert "voicebook-tool @ https://github.com/269289854/voicebook/archive/refs/tags/v0.7.1.tar.gz" in requirements
    assert "url = https://github.com/269289854/talebook-audio-cli.git" in gitmodules
