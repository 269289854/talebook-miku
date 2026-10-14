from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "update-candle-reader.yml"


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_grants_only_the_write_scopes_needed_to_open_update_prs():
    # 仓库默认 GITHUB_TOKEN 为只读，推送更新分支和创建 PR 必须显式申请写权限。
    assert load_workflow()["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
    }


def test_update_pull_request_uses_repository_token():
    steps = load_workflow()["jobs"]["update-candle-reader"]["steps"]
    create_pr = next(step for step in steps if step.get("name") == "Create Pull Request")

    assert create_pr["uses"] == "peter-evans/create-pull-request@v6"
    assert create_pr["with"]["token"] == "${{ secrets.GITHUB_TOKEN }}"
