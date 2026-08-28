from __future__ import annotations

import base64
import json
import subprocess
import sys


def _effect(**updates):
    value = {
        "provider": "github",
        "operation": "github.file.update",
        "owner": "reprewindai-dev",
        "repo": "sandbox",
        "branch": "main",
        "path": "README.md",
        "expected_blob_sha": "a" * 40,
        "content_b64": base64.b64encode(b"governed\n").decode("ascii"),
        "commit_message": "test: governed mutation",
    }
    value.update(updates)
    return value


def _run(effect):
    return subprocess.run(
        [sys.executable, "cell_executor/main.py"],
        input=json.dumps(effect).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=5,
    )


def test_executor_canonically_reemits_exact_authorized_effect():
    effect = _effect()
    result = _run(effect)

    assert result.returncode == 0
    assert json.loads(result.stdout) == effect
    assert result.stderr == b""


def test_executor_rejects_extra_authority_shaping_fields():
    result = _run(_effect(token="must-not-exist"))

    assert result.returncode != 0
    assert b"fields do not match" in result.stderr


def test_executor_rejects_repository_path_escape():
    result = _run(_effect(path="../secret"))

    assert result.returncode != 0
    assert b"path escape rejected" in result.stderr
