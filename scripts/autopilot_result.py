#!/usr/bin/env python3
"""Validate configuration and role/revision evidence without third-party dependencies."""

from __future__ import annotations

import json
import sys
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


def main() -> int:
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
