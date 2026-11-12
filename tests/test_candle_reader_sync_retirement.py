from pathlib import Path

import yaml


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def workflow_nodes(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from workflow_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from workflow_nodes(child)


def test_workflows_do_not_sync_upstream_candle_reader():
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "update-candle-reader" not in workflow.get("jobs", {}), path.name

        for node in workflow_nodes(workflow):
            if isinstance(node, str):
                assert node != "update-candle-reader", path.name
                assert "github.com/talebook/candle-reader" not in node, path.name
            elif isinstance(node, dict):
                assert (node.get("OWNER"), node.get("REPO")) != ("talebook", "candle-reader"), path.name
