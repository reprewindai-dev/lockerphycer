#!/usr/bin/env python3
"""Minimal untrusted workload for the P0 governed GitHub consequence.

The cell cannot reach GitHub and never sees a provider credential. It validates
and canonically re-emits only the exact structured effect it received. The host
broker independently compares the result to CAPPO's signed semantic digest
before performing any external mutation.
"""

from __future__ import annotations

import base64
import json
import sys


_REQUIRED = {
    "provider",
    "operation",
    "owner",
    "repo",
    "branch",
    "path",
    "expected_blob_sha",
    "content_b64",
    "commit_message",
}


def _fail(message: str) -> int:
    sys.stderr.write(message + "\n")
    return 2


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(2_000_001)
    except Exception:
        return _fail("input read failed")
    if len(raw) > 2_000_000:
        return _fail("input exceeds governed cell limit")

    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _fail("input must be UTF-8 JSON")
    if not isinstance(value, dict):
        return _fail("effect must be a JSON object")
    if set(value) != _REQUIRED:
        return _fail("effect fields do not match the governed GitHub contract")
    if value.get("provider") != "github" or value.get("operation") != "github.file.update":
        return _fail("effect provider/operation is not authorized by this executor")

    for key in ("owner", "repo", "branch", "path", "expected_blob_sha", "content_b64", "commit_message"):
        if not isinstance(value.get(key), str) or not value[key]:
            return _fail(f"effect field {key} must be a non-empty string")
    if value["path"].startswith("/") or ".." in value["path"].split("/"):
        return _fail("repository path escape rejected")
    if len(value["expected_blob_sha"]) not in {40, 64}:
        return _fail("expected_blob_sha length is invalid")
    try:
        base64.b64decode(value["content_b64"], validate=True)
    except Exception:
        return _fail("content_b64 is invalid")

    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
