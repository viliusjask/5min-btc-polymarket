"""The launcher accepts only role-correct, exact-revision review evidence."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "autopilot_result.py"
SPEC = importlib.util.spec_from_file_location("autopilot_result", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def result(tmp_path, **changes):
    payload = {
        "status": "approved",
        "summary": "Independent review passed",
        "reviewed_head": "head-a",
        "reviewed_base": "base-a",
        "findings": [],
    }
    payload.update(changes)
    path = tmp_path / "result.json"
    path.write_text(json.dumps(payload))
    return path


def test_exact_review_approved(tmp_path):
    assert MODULE.stage_status(result(tmp_path), "reviewer", "head-a", "base-a") == "approved"


@pytest.mark.parametrize("head,base", [("head-b", "base-a"), ("head-a", "base-b")])
def test_stale_revision_rejected(tmp_path, head, base):
    with pytest.raises(ValueError, match="commits"):
        MODULE.stage_status(result(tmp_path), "reviewer", head, base)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "approved", "findings": ["Unresolved issue"]},
        {"status": "changes_requested", "findings": []},
        {"status": "complete"},
        {"summary": ""},
        {"findings": [""]},
        {"unexpected": True},
    ],
)
def test_invalid_review_rejected(tmp_path, changes):
    with pytest.raises(ValueError):
        MODULE.stage_status(result(tmp_path, **changes), "reviewer", "head-a", "base-a")


def test_author_cannot_approve(tmp_path):
    with pytest.raises(ValueError, match="assigned role"):
        MODULE.stage_status(result(tmp_path), "author", "", "")


def test_external_wait_allowed_for_author(tmp_path):
    assert MODULE.stage_status(result(tmp_path, status="waiting"), "author", "", "") == ("waiting")
