"""The launcher accepts only role-correct, exact-revision review evidence."""

import importlib.util
import json
import os
import shutil
import subprocess
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


def test_failed_corrections_require_diagnosis_despite_new_commits(tmp_path):
    ledger = tmp_path / "reviews.json"
    for index in range(3):
        review = tmp_path / f"review-{index}.json"
        review.write_text(
            result(
                tmp_path,
                status="changes_requested",
                findings=["F1: defect"],
                reviewed_head=f"new-doc-commit-{index}",
            ).read_text()
        )
        MODULE.review_progress(ledger, "PLAN", review)
    assert "DIAGNOSIS REQUIRED" in MODULE.review_context(ledger, "PLAN")
    assert MODULE.review_progress(ledger, "PLAN")["unsuccessful_reviews"] == 3
    # Retrying wrapper bookkeeping after interruption is not another review round.
    MODULE.review_progress(ledger, "PLAN", review)
    assert MODULE.review_progress(ledger, "PLAN")["unsuccessful_reviews"] == 3
    approved = tmp_path / "approved.json"
    approved.write_text(result(tmp_path).read_text())
    record = MODULE.review_progress(ledger, "PLAN", approved)
    assert record["unsuccessful_reviews"] == 0
    assert len(record["history"]) == 4
    assert "DIAGNOSIS REQUIRED" not in MODULE.review_context(ledger, "PLAN")


def test_review_history_is_stage_specific_and_rejects_author_approval(tmp_path):
    ledger = tmp_path / "reviews.json"
    MODULE.review_progress(
        ledger, "PLAN", result(tmp_path, status="changes_requested", findings=["F1: plan blocker"])
    )
    assert MODULE.review_progress(ledger, "BUILD")["history"] == []
    with pytest.raises(ValueError, match="assigned role"):
        MODULE.review_progress(ledger, "PLAN", result(tmp_path, status="complete"))
    assert MODULE.review_progress(ledger, "PLAN")["unsuccessful_reviews"] == 1


@pytest.mark.parametrize(
    "mode,stage,failure,cached,recovery,expected",
    [
        (
            "PLAN",
            "author",
            "quota",
            False,
            False,
            ["claude-fable-5-1 medium 0", "claude-opus-5 high 0"],
        ),
        (
            "INTEGRATION",
            "reviewer",
            "quota",
            False,
            False,
            ["claude-fable-5-1 high 1", "claude-opus-5 high 1"],
        ),
        (
            "BUILD",
            "author",
            "quota",
            False,
            True,
            ["claude-fable-5-1 medium 0", "claude-opus-5 high 0"],
        ),
        ("PLAN", "author", "quota", True, False, ["claude-opus-5 high 0"]),
        ("BUILD", "author", "quota", False, False, ["claude-opus-5 medium 0"]),
        ("PLAN", "author", "auth", False, False, ["claude-fable-5-1 medium 0"]),
        ("PLAN", "reviewer", "quota", False, False, ["gpt-6-astra high 1"]),
    ],
)
def test_runner_routes_quota_without_changing_role_or_codex(
    tmp_path, mode, stage, failure, cached, recovery, expected
):
    """Run the real wrapper with model, git and shared helper boundaries stubbed.

    Shared helper expiry/classification has its own harness tests; these checks
    cover BTC calling those interfaces, immediate retry and startup recovery.
    """
    root = tmp_path / "project"
    shutil.copytree(SCRIPT.parent, root / "scripts")
    shutil.copytree(
        SCRIPT.parents[1] / "docs" / "autopilot-prompts", root / "docs" / "autopilot-prompts"
    )
    shutil.copyfile(SCRIPT.parents[1] / "docs" / "autopilot.md", root / "docs" / "autopilot.md")
    state = root / ".autopilot"
    state.mkdir()
    (state / "INBOX.md").write_text("Synthetic authorized task\n")
    (state / "mode").write_text(mode + "\n")
    (state / "stage").write_text(stage + "\n")
    marker = state / "limited-claude-fable-5-1"
    if cached:
        marker.write_text("cached quota\n")
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "lib.sh").write_text(
        """
log() { printf '%s\n' "$*" >> "$STATE/test.log"; }
kill_tree() { :; }
claude_route() {
  if [ "$1" = claude-fable-5-1 ] && [ -f "$STATE/limited-$1" ]; then
    echo 'claude-opus-5 high'
  else printf '%s %s\n' "$1" "$2"; fi
}
claude_quota_fallback() {
  [ "$2" = claude-fable-5-1 ] || return 1
  echo quota > "$STATE/limited-$2"
}
failed_call() {
  printf '%s %s %s\n' "$1" "$2" "$STAGE_READ_ONLY" >> "$STATE/calls"
  printf '%s\n' "$TEST_FAILURE" > "$3"
  [ "$(wc -l < "$STATE/calls")" -lt 2 ] || touch "$STATE/STOP"
  return 1
}
run_claude() { failed_call "$CLAUDE_MODEL" "$CLAUDE_EFFORT" "$3"; }
run_codex() { failed_call "$CODEX_MODEL" "$CODEX_EFFORT" "$3"; }
"""
    )
    (shared / "events.py").write_text(
        "import pathlib, sys; print(pathlib.Path(sys.argv[-1]).read_text().strip())\n"
    )
    (shared / "wip.py").write_text(
        "import os; raise SystemExit(int(os.environ['TEST_RECOVERY']) * 3)\n"
    )
    fake = tmp_path / "bin"
    fake.mkdir()
    commands = {
        "git": """#!/bin/bash
case "$3" in
  show)
    case "$4" in
      *:lib.sh) cat "$TEST_SHARED/lib.sh" ;;
      *:scripts/*_events.py) cat "$TEST_SHARED/events.py" ;;
      *:scripts/wip_preflight.py) cat "$TEST_SHARED/wip.py" ;;
    esac ;;
  branch) echo chore/btc-autopilot ;;
  rev-parse) echo head-a ;;
esac
exit 0
""",
        "gh": "#!/bin/sh\nprintf '{}\\n'\n",
        "sleep": '#!/bin/sh\ntouch "$TEST_STATE/STOP"\n',
    }
    for name, content in commands.items():
        executable = fake / name
        executable.write_text(content)
        executable.chmod(0o755)
    run = subprocess.run(
        ["bash", str(root / "scripts" / "autopilot.sh"), "run"],
        env=dict(
            os.environ,
            PATH=str(fake) + os.pathsep + os.environ["PATH"],
            TEST_SHARED=str(shared),
            TEST_STATE=str(state),
            TEST_FAILURE=failure,
            TEST_RECOVERY=str(int(recovery)),
        ),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert run.returncode == 0, run.stderr
    assert (state / "calls").read_text().splitlines() == expected
    assert marker.exists() == (cached or len(expected) == 2)
    log = (state / "test.log").read_text()
    if len(expected) == 2:
        assert "retrying in 10 minutes" not in log
    elif failure == "auth":
        assert "authentication required" in log
    else:
        assert "retrying in 10 minutes" in log
