#!/usr/bin/env python3
"""Veklom cross-system Predator probe using only real network/runtime boundaries.

Required chain:
    signed CAPPO authority -> Lockerphycer cell-host -> real GitHub consequence
    -> real PGL persistence/readback/chain verification

There is deliberately no MockTarget, MockPGL, or synthetic success path here.
Missing infrastructure is a hard failure and never earns a proof status.
"""

from __future__ import annotations

import copy
import json
import os
import platform
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.execution_cells.authority import authority_digest, canonical_json_bytes
from core.execution_cells.effects import GitHubFileUpdateIntent, effect_digest
from core.execution_cells.models import SignedAuthority
from core.execution_cells.pgl_client import PGLEvidenceError, RealPGLClient


class ProbeFailure(RuntimeError):
    pass


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProbeFailure(f"required environment variable is missing: {name}")
    return value


def read_json_file(path: str) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProbeFailure(f"{path} must contain one JSON object")
    return raw


def _host_sentinel_create(secret: str) -> tuple[str, callable]:
    """Create a host-only sentinel in the Podman host's /tmp namespace."""
    sentinel = f"/tmp/veklom-host-sentinel-{uuid.uuid4().hex}.txt"
    if platform.system().lower() == "windows":
        result = subprocess.run(
            ["wsl", "sh", "-lc", f"umask 077; printf '%s' {json.dumps(secret)} > {sentinel}; test -f {sentinel}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise ProbeFailure(f"could not create WSL host sentinel: {result.stderr.strip()}")

        def cleanup() -> None:
            subprocess.run(["wsl", "rm", "-f", sentinel], timeout=10, check=False)

        return sentinel, cleanup

    Path(sentinel).write_text(secret, encoding="utf-8")
    os.chmod(sentinel, 0o600)

    def cleanup() -> None:
        Path(sentinel).unlink(missing_ok=True)

    return sentinel, cleanup


def hostile_program() -> str:
    """Cell program: hostile observations go to stderr; exact effect JSON to stdout."""
    return r'''
import json, os, socket, sys, urllib.request
payload=json.load(sys.stdin)
checks={}
def denied(name, fn):
    try:
        fn(); checks[name]={"denied":False,"error":None}
    except Exception as exc:
        checks[name]={"denied":True,"error":type(exc).__name__}

denied("public_ipv4", lambda: socket.create_connection(("1.1.1.1",53),0.5))
denied("dns", lambda: socket.getaddrinfo("example.com",443))
denied("metadata", lambda: urllib.request.urlopen("http://169.254.169.254/",timeout=0.5).read(1))
denied("raw_socket", lambda: socket.socket(socket.AF_INET,socket.SOCK_RAW,socket.IPPROTO_ICMP))
denied("docker_socket", lambda: open("/var/run/docker.sock","rb").read(1))
denied("podman_socket", lambda: open("/run/podman/podman.sock","rb").read(1))
denied("host_sentinel", lambda: open(payload["host_sentinel"],"rb").read(1))
denied("rootfs_write", lambda: open("/etc/veklom-predator-write","w").write("x"))
status={}
for line in open("/proc/self/status",encoding="utf-8",errors="replace"):
    if line.startswith(("CapEff:","CapBnd:","NSpid:")):
        k,v=line.split(":",1); status[k]=v.strip()
checks["cap_eff_zero"] = status.get("CapEff") == "0000000000000000"
checks["nspid"] = status.get("NSpid")
checks["uid"] = os.getuid()
checks["gid"] = os.getgid()
checks["network_contract"] = os.environ.get("VEKLOM_CELL_NETWORK")
checks["credential_contract"] = os.environ.get("VEKLOM_CREDENTIAL_MODE")
print(json.dumps({"l2_witness":checks},sort_keys=True),file=sys.stderr,flush=True)
print(json.dumps(payload["intent"],sort_keys=True,separators=(",",":")),flush=True)
'''.strip()


class CellHostClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"x-cell-host-key": api_key, "content-type": "application/json"}
        self.client = httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        self.client.close()

    def health(self) -> dict[str, Any]:
        response = self.client.get(f"{self.base_url}/health")
        if response.status_code != 200:
            raise ProbeFailure(f"Lockerphycer health failed: HTTP {response.status_code}")
        body = response.json()
        if not isinstance(body, dict) or body.get("status") != "healthy":
            raise ProbeFailure("Lockerphycer cell host is not healthy")
        return body

    def run_cell(self, *, authority: dict[str, Any], image: str, intent: dict[str, Any], sentinel: str) -> httpx.Response:
        return self.client.post(
            f"{self.base_url}/v1/cells/run",
            headers=self.headers,
            json={
                "authority": authority,
                "image": image,
                "command": ["python", "-c", hostile_program()],
                "input_payload": {"intent": intent, "host_sentinel": sentinel},
                "safe_environment": {},
                "expected_effect_digest": effect_digest(GitHubFileUpdateIntent.model_validate(intent)),
            },
        )

    def execute_effect(self, *, authority: dict[str, Any], intent: dict[str, Any]) -> httpx.Response:
        payload = dict(intent)
        payload["authority"] = authority
        return self.client.post(
            f"{self.base_url}/v1/effects/github/file-update",
            headers=self.headers,
            json=payload,
        )


def expect_rejected(response: httpx.Response, *, test_id: str, allowed: set[int] = {403, 409}) -> None:
    if response.status_code not in allowed:
        raise ProbeFailure(f"{test_id} expected governed rejection, got HTTP {response.status_code}: {response.text[:500]}")
    print(f"[PASS] {test_id}: governed rejection HTTP {response.status_code}")


def validate_witness(stderr: str) -> dict[str, Any]:
    lines = [line for line in stderr.splitlines() if line.strip()]
    if not lines:
        raise ProbeFailure("A00 cell did not emit L2 witness evidence")
    try:
        record = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise ProbeFailure("A00 L2 witness was not valid JSON") from exc
    witness = record.get("l2_witness") if isinstance(record, dict) else None
    if not isinstance(witness, dict):
        raise ProbeFailure("A00 L2 witness object missing")
    denied = ["public_ipv4", "dns", "metadata", "raw_socket", "docker_socket", "podman_socket", "host_sentinel", "rootfs_write"]
    for name in denied:
        item = witness.get(name)
        if not isinstance(item, dict) or item.get("denied") is not True:
            raise ProbeFailure(f"L2 containment witness failed: {name}")
    if witness.get("cap_eff_zero") is not True:
        raise ProbeFailure("L2 capability witness did not observe CapEff=0")
    if witness.get("network_contract") != "none":
        raise ProbeFailure("L2 workload did not observe network=none contract")
    if witness.get("credential_contract") != "brokered_only":
        raise ProbeFailure("L2 workload did not observe brokered-only credential contract")
    return witness


def main() -> int:
    cell_url = os.environ.get("LOCKERPHYCER_CELL_HOST_URL", "http://127.0.0.1:8765")
    cell_key = required("LOCKERPHYCER_CELL_HOST_API_KEY")
    image = required("PREDATOR_IMAGE")
    authority_path = required("PREDATOR_AUTHORITY_FILE")
    intent_path = required("PREDATOR_GITHUB_INTENT_FILE")
    pgl_url = os.environ.get("PGL_BASE_URL", "http://127.0.0.1:8001")
    pgl_key = required("PGL_API_KEY")
    pgl_agent = required("PGL_AGENT_ID")

    if "@sha256:" not in image:
        raise ProbeFailure("PREDATOR_IMAGE must be immutable and pinned with @sha256")

    authority_raw = read_json_file(authority_path)
    authority = SignedAuthority.model_validate(authority_raw)
    intent = GitHubFileUpdateIntent.model_validate(read_json_file(intent_path))
    expected_effect = effect_digest(intent)
    if authority.envelope.semantic_intent_digest != expected_effect:
        raise ProbeFailure("CAPPO authority is not bound to the exact GitHub effect fixture")
    if authority.envelope.runtime_image_digest != image.rsplit("@", 1)[1].lower():
        raise ProbeFailure("CAPPO authority runtime_image_digest does not match PREDATOR_IMAGE")

    sentinel_secret = uuid.uuid4().hex
    sentinel, cleanup_sentinel = _host_sentinel_create(sentinel_secret)
    cell = CellHostClient(cell_url, cell_key)
    pgl = RealPGLClient(pgl_url, pgl_key)
    try:
        print("=" * 72)
        print("VEKLOM CROSS-SYSTEM PREDATOR — REAL BOUNDARIES ONLY")
        print("=" * 72)
        print("[PRECHECK]", json.dumps(cell.health(), sort_keys=True))

        # A00 — one real isolated cell followed by one real target mutation.
        print("\n[A00] positive governed chain")
        run = cell.run_cell(authority=authority_raw, image=image, intent=intent.model_dump(mode="json"), sentinel=sentinel)
        if run.status_code != 200:
            raise ProbeFailure(f"A00 cell run failed: HTTP {run.status_code}: {run.text[:1000]}")
        cell_result = run.json()
        if cell_result.get("exit_code") != 0 or cell_result.get("teardown_confirmed") is not True:
            raise ProbeFailure("A00 cell did not complete with confirmed teardown")
        witness = validate_witness(str(cell_result.get("stderr", "")))
        cell_id = cell_result.get("cell_id")
        if not isinstance(cell_id, str) or not cell_id:
            raise ProbeFailure("A00 cell_id missing")

        effect = cell.execute_effect(authority=authority_raw, intent=intent.model_dump(mode="json"))
        if effect.status_code != 200:
            raise ProbeFailure(f"A00 target consequence failed: HTTP {effect.status_code}: {effect.text[:1000]}")
        target = effect.json()
        if target.get("mutation_succeeded") is not True or target.get("target_result_confirmed") is not True:
            raise ProbeFailure("A00 target did not independently confirm the consequence")
        if target.get("credential_revoked") is not True:
            raise ProbeFailure("A00 JIT provider credential revocation was not positively confirmed")
        if target.get("originating_cell_id") != cell_id:
            raise ProbeFailure("A00 target consequence is not bound to the originating cell")
        before_sha, after_sha = target.get("before_sha"), target.get("after_blob_sha")
        if not isinstance(before_sha, str) or not isinstance(after_sha, str) or before_sha == after_sha:
            raise ProbeFailure("A00 target before/after state is not a confirmed mutation")
        print(f"[PASS] A00 target state {before_sha} -> {after_sha}")

        # A10 — exact authority/effect replay must be durably fenced.
        replay = cell.execute_effect(authority=authority_raw, intent=intent.model_dump(mode="json"))
        expect_rejected(replay, test_id="A10 replay", allowed={409})

        # A01 — widening capability invalidates the CAPPO signature before execution.
        a01 = copy.deepcopy(authority_raw)
        a01["envelope"]["capability_id"] = "admin-action"
        expect_rejected(cell.run_cell(authority=a01, image=image, intent=intent.model_dump(mode="json"), sentinel=sentinel), test_id="A01 capability widening", allowed={403})

        # A04 — identity substitution invalidates signed lineage.
        a04 = copy.deepcopy(authority_raw)
        a04["envelope"]["subject_id"] = "substituted-principal"
        expect_rejected(cell.run_cell(authority=a04, image=image, intent=intent.model_dump(mode="json"), sentinel=sentinel), test_id="A04 identity substitution", allowed={403})

        # A02 — target/resource mutation keeps signed authority intact, so effect digest check must reject it.
        a02_intent = intent.model_dump(mode="json")
        a02_intent["path"] = "unauthorized/" + str(a02_intent["path"])
        expect_rejected(cell.execute_effect(authority=authority_raw, intent=a02_intent), test_id="A02 resource widening", allowed={409})

        # A09 — immutable runtime measurement cannot be substituted under a valid signature.
        a09_image = image.rsplit("@sha256:", 1)[0] + "@sha256:" + ("0" * 64)
        # New authority would be required to consume cell_run again.  We attack the signed artifact
        # binding here with the already-consumed lease; either replay fencing or artifact mismatch is
        # governed rejection.  A dedicated fresh fixture is required before calling this A09 sealed.
        a09 = cell.run_cell(authority=authority_raw, image=a09_image, intent=intent.model_dump(mode="json"), sentinel=sentinel)
        expect_rejected(a09, test_id="A09 image digest substitution", allowed={409})

        composition_details = {
            "schema_version": "veklom.composition_consequence.v1",
            "execution_id": authority.envelope.execution_id,
            "grant_id": authority.envelope.grant_id,
            "origin_identity": authority.envelope.subject_id,
            "tenant_id": authority.envelope.tenant_id,
            "workspace_id": authority.envelope.workspace_id,
            "authority_digest": authority_digest(authority),
            "capability_id": authority.envelope.capability_id,
            "semantic_intent_digest": authority.envelope.semantic_intent_digest,
            "runtime_image_digest": authority.envelope.runtime_image_digest,
            "cell_id": cell_id,
            "isolation_class": cell_result.get("isolation_class"),
            "teardown_confirmed": True,
            "l2_witness": witness,
            "target": {
                "provider": target.get("provider"),
                "repository": target.get("repository"),
                "branch": target.get("branch"),
                "path": target.get("path"),
                "before_sha": before_sha,
                "after_blob_sha": after_sha,
                "commit_sha": target.get("commit_sha"),
                "effect_digest": target.get("effect_digest"),
                "target_result_confirmed": True,
                "credential_revoked": True,
            },
            "finality_state": "COMPLETED_SUCCESS",
        }
        print("\n[A17] persist exact consequence into real PGL")
        pgl_witness = pgl.persist_and_verify(
            agent_id=pgl_agent,
            actor="lockerphycer-predator",
            execution_id=authority.envelope.execution_id,
            idempotency_key=f"composition:{authority.envelope.execution_id}",
            details=composition_details,
        )
        print("[PASS] A17", json.dumps(pgl_witness.__dict__, sort_keys=True))

        evidence = {
            "status": "VERIFIED_LOCAL_CANDIDATE",
            "execution_id": authority.envelope.execution_id,
            "authority_digest": authority_digest(authority),
            "cell_id": cell_id,
            "target_before": before_sha,
            "target_after": after_sha,
            "target_commit": target.get("commit_sha"),
            "pgl_event_id": pgl_witness.event_id,
            "pgl_event_hash": pgl_witness.event_hash,
            "pgl_chain_head": pgl_witness.chain_head,
            "pgl_chain_verified": pgl_witness.ledger_verification,
            "teardown_confirmed": True,
            "credential_revoked": True,
            "tests": ["A00", "A01", "A02", "A04", "A09-partial", "A10", "A17"],
            "note": "A09 requires a fresh independently signed fixture before it may be promoted from partial.",
        }
        output = Path(os.environ.get("PREDATOR_EVIDENCE_OUT", "predator_composition_evidence.json"))
        output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n[DONE] evidence written to {output}")
        return 0
    except PGLEvidenceError as exc:
        raise ProbeFailure(f"real PGL verification failed: {exc}") from exc
    finally:
        pgl.close()
        cell.close()
        cleanup_sentinel()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeFailure as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
