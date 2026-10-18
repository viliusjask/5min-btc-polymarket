#!/usr/bin/env python3
"""Validate configuration and role/revision evidence without third-party dependencies."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path


def stage_status(path: Path, role: str, head: str, base: str) -> str:
    data = json.loads(path.read_text())
    fields = {"status", "summary", "reviewed_head", "reviewed_base", "findings"}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("stage output has an invalid shape")
    for name in fields - {"findings"}:
        if not isinstance(data[name], str):
            raise ValueError(f"{name} must be a string")
    if not data["summary"].strip():
        raise ValueError("stage summary is empty")
    if not isinstance(data["findings"], list) or any(
        not isinstance(item, str) or not item.strip() for item in data["findings"]
    ):
        raise ValueError("findings must be nonempty strings")
    allowed = {
        "author": {"continue", "waiting", "complete"},
        "reviewer": {"approved", "changes_requested"},
    }
    if role not in allowed or data["status"] not in allowed[role]:
        raise ValueError("status is not valid for the assigned role")
    if role == "reviewer":
        if data["reviewed_head"] != head or data["reviewed_base"] != base:
            raise ValueError("review is not bound to the supplied commits")
        if (data["status"] == "approved") != (not data["findings"]):
            raise ValueError("review verdict contradicts its findings")
    return data["status"]


def author_session_key(path: Path, mode: str) -> str:
    """Retain a conversation within one stage, rotate when the stage changes."""
    if mode not in {"PLAN", "BUILD", "INTEGRATION"}:
        raise ValueError("invalid author stage")
    current = json.loads(path.read_text()) if path.exists() else {}
    if current.get("mode") == mode and isinstance(current.get("key"), str) and current["key"]:
        return current["key"]
    record = {"mode": mode, "key": f"btc-{mode}-{uuid.uuid4()}"}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(record, stream)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return record["key"]


def review_progress(path: Path, mode: str, result: Path | None = None) -> dict:
    """Persist reviewer-owned findings; commit churn must not reset failed rounds."""
    if mode not in {"PLAN", "BUILD", "INTEGRATION"}:
        raise ValueError("invalid review stage")
    record = json.loads(path.read_text()) if path.exists() else {}
    if record.get("mode") != mode:
        record = {"mode": mode, "unsuccessful_reviews": 0, "history": []}
    if result is not None:
        review = json.loads(result.read_text())
        stage_status(result, "reviewer", review["reviewed_head"], review["reviewed_base"])
        # An interrupted wrapper can replay a receipt; count each receipt once.
        receipt = str(result.resolve())
        if not any(item["receipt"] == receipt for item in record["history"]):
            record["unsuccessful_reviews"] = (
                record["unsuccessful_reviews"] + 1 if review["status"] == "changes_requested" else 0
            )
            record["history"].append({"receipt": receipt, **review})
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(record, indent=2) + "\n")
            temporary.replace(path)
    return record


def review_context(path: Path, mode: str) -> str:
    record = review_progress(path, mode)
    count = record["unsuccessful_reviews"]
    text = f"Reviewer-owned history: {path}. Unsuccessful reviews in this stage: {count}."
    if record["history"]:
        text += " Latest stage-specific verdict: " + json.dumps(record["history"][-1])
    if count >= 3:
        text += (
            " DIAGNOSIS REQUIRED: at least two correction rounds failed. Before another fix,"
            " identify misunderstanding, incomplete fix, contradictory requirement, or unsuitable"
            " task size for each remaining blocker, then choose a specific changed approach."
            " Record the diagnosis and verification evidence in the briefing. The reviewer must"
            " assess it; do not autoapprove or repeat unchanged instructions."
        )
    return text


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "review-context":
        print(review_context(Path(sys.argv[2]), sys.argv[3]))
        return 0
    if len(sys.argv) == 5 and sys.argv[1] == "record-review":
        review_progress(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == "author-key":
        print(author_session_key(Path(sys.argv[2]), sys.argv[3]))
        return 0
    if len(sys.argv) > 1:
        if len(sys.argv) != 6 or sys.argv[1] != "result":
            raise ValueError("usage: check_setup.py result FILE ROLE HEAD BASE")
        print(stage_status(Path(sys.argv[2]), *sys.argv[3:]))
        return 0
    raise ValueError("usage: autopilot_result.py result FILE ROLE HEAD BASE")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"setup validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
