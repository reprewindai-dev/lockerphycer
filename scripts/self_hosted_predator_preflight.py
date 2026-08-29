#!/usr/bin/env python3
"""Secret-safe substrate preflight for the Lockerphycer Predator campaign.

This script reports only host capability facts and the *presence* of required
configuration variables. It never prints secret values. It is suitable for a
self-hosted GitHub Actions runner or direct local execution.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx


def run(command: list[str], timeout: int = 15) -> dict[str, Any]:
    try:
        cp = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "available": True,
            "returncode": cp.returncode,
            "stdout": cp.stdout.strip()[:4000],
            "stderr": cp.stderr.strip()[:2000],
        }
    except FileNotFoundError:
        return {"available": False, "returncode": None, "stdout": "", "stderr": "not found"}
    except subprocess.TimeoutExpired:
        return {"available": True, "returncode": None, "stdout": "", "stderr": "timeout"}


def health(url: str) -> dict[str, Any]:
    try:
        response = httpx.get(url, timeout=3.0, follow_redirects=False)
        body: Any
        try:
            body = response.json()
        except ValueError:
            body = response.text[:500]
        return {"reachable": True, "status_code": response.status_code, "body": body}
    except Exception as exc:
        return {"reachable": False, "error": type(exc).__name__}


def main() -> int:
    system = platform.system().lower()
    report: dict[str, Any] = {
        "schema": "veklom.predator_preflight.v1",
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "executables": {
            "podman": shutil.which("podman") is not None,
            "docker": shutil.which("docker") is not None,
            "wsl": shutil.which("wsl") is not None,
            "firecracker": shutil.which("firecracker") is not None,
        },
        "configuration_presence": {
            name: bool(os.environ.get(name, "").strip())
            for name in (
                "LOCKERPHYCER_CELL_HOST_API_KEY",
                "CAPPO_AUTHORITY_PUBLIC_KEYS",
                "PGL_API_KEY",
                "PGL_AGENT_ID",
                "GITHUB_APP_ID",
                "GITHUB_APP_PRIVATE_KEY",
                "GITHUB_INSTALLATION_ID",
            )
        },
        "services": {
            "cell_host": health(os.environ.get("LOCKERPHYCER_CELL_HOST_URL", "http://127.0.0.1:8765") + "/health"),
            "pgl": health(os.environ.get("PGL_BASE_URL", "http://127.0.0.1:8001") + "/health"),
        },
    }

    if system == "windows" and shutil.which("wsl"):
        report["wsl"] = {
            "status": run(["wsl", "sh", "-lc", "uname -a; printf '\\nPODMAN='; command -v podman || true; printf '\\nKVM='; test -e /dev/kvm && echo yes || echo no"]),
            "podman_version": run(["wsl", "sh", "-lc", "podman version --format '{{.Client.Version}}' 2>/dev/null || podman --version 2>/dev/null || true"]),
            "podman_info": run(["wsl", "sh", "-lc", "podman info --format 'host={{.Host.OS}} arch={{.Host.Arch}} rootless={{.Host.Security.Rootless}} cgroup={{.Host.CgroupVersion}}' 2>/dev/null || true"]),
        }
    else:
        report["linux_substrate"] = {
            "kvm_device": Path("/dev/kvm").exists(),
            "podman_version": run(["podman", "--version"]) if shutil.which("podman") else {"available": False},
            "podman_info": run(["podman", "info", "--format", "host={{.Host.OS}} arch={{.Host.Arch}} rootless={{.Host.Security.Rootless}} cgroup={{.Host.CgroupVersion}}"])
            if shutil.which("podman")
            else {"available": False},
            "firecracker_version": run(["firecracker", "--version"])
            if shutil.which("firecracker")
            else {"available": False},
        }

    print(json.dumps(report, indent=2, sort_keys=True))
    # Preflight is observational. Missing infrastructure is represented in the
    # report rather than converted into a false CI failure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
