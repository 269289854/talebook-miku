from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def load_ci_workflow() -> dict:
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))


def test_server_uses_base_checkout_and_make_without_explicit_git_config():
    test_server = load_ci_workflow()["jobs"]["test-server"]

    assert test_server["container"]["image"] == "ghcr.io/${{ github.repository_owner }}/talebook-base:slim-v8.5.0"
    assert test_server["container"]["credentials"] == {
        "username": "${{ github.actor }}",
        "password": "${{ secrets.GITHUB_TOKEN }}",
    }

    steps = test_server["steps"]
    checkout = next(step for step in steps if step.get("name") == "Checkout code")
    assert checkout["uses"] == "actions/checkout@v4"

    commands = [step.get("run", "") for step in steps]
    assert all("safe.directory" not in command for command in commands)
    assert "make init" in commands
    assert "make lint-py" in commands
    assert "make pytest" in commands
    assert "make test" not in commands


def test_server_inspects_slim_base_public_commands():
    steps = load_ci_workflow()["jobs"]["test-server"]["steps"]
    inspect = next(step for step in steps if step.get("name") == "Inspect environment")["run"]
    command_lines = {line.strip() for line in inspect.splitlines() if line.strip()}

    assert {
        "command -v ebook-convert",
        "ebook-convert --version",
        "command -v calibredb",
        "calibredb --version",
        "command -v make",
        "make --version",
        "python3 --version",
        "pip3 --version",
    } <= command_lines
    assert "which calibre" not in command_lines
    assert "calibre --version" not in command_lines
