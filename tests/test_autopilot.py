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


@pytest.mark.parametrize("check_status", [0, 3, 2])
def test_startup_inventory_controls_replanning_before_model_calls(tmp_path, check_status):
    import os
    import subprocess

    state = tmp_path / "state"
    state.mkdir()
    (state / "mode").write_text("BUILD\n")
    (state / "stage").write_text("reviewer\n")
    # Inventory itself is tested in the pinned shared harness. Exercise the actual
    # BTC transition with successful, outstanding-work and failed-inventory results.
    fake = tmp_path / "bin"
    fake.mkdir()
    executable = fake / "python3"
    executable.write_text(f"#!/bin/sh\nexit {check_status}\n")
    executable.chmod(0o755)
    helper = SCRIPT.parent / "autopilot-wip.sh"
    run = subprocess.run(
        ["bash", "-c", 'source "$HELPER"; log() { :; }; btc_wip_startup'],
        env=dict(
            os.environ,
            PATH=str(fake) + os.pathsep + os.environ["PATH"],
            HELPER=str(helper),
            STATE=str(state),
            ROOT=str(tmp_path),
            DIR=str(tmp_path),
        ),
        capture_output=True,
        text=True,
    )
    assert run.returncode == (2 if check_status == 2 else 0)
    assert (state / "mode").read_text().strip() == ("PLAN" if check_status == 3 else "BUILD")
    assert (state / "stage").read_text().strip() == ("author" if check_status == 3 else "reviewer")


def test_author_session_key_survives_retries_and_rotates_at_stage_boundaries(tmp_path):
    path = tmp_path / "state" / "author-session-stage.json"
    plan = MODULE.author_session_key(path, "PLAN")
    assert MODULE.author_session_key(path, "PLAN") == plan
    build = MODULE.author_session_key(path, "BUILD")
    assert build != plan
    assert MODULE.author_session_key(path, "BUILD") == build
    integration = MODULE.author_session_key(path, "INTEGRATION")
    assert integration not in {plan, build}
    assert MODULE.author_session_key(path, "PLAN") not in {plan, build, integration}


def test_invalid_stage_cannot_replace_saved_author_session(tmp_path):
    path = tmp_path / "stage.json"
    plan = MODULE.author_session_key(path, "PLAN")
    with pytest.raises(ValueError, match="invalid author stage"):
        MODULE.author_session_key(path, "reviewer")
    assert MODULE.author_session_key(path, "PLAN") == plan
