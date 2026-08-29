#!/usr/bin/env python3
"""Live L3 Firecracker/KVM Predator probe — real boundaries only.

This runner never creates authority, never substitutes mocks, and never marks the
profile sealed.  It requires independently signed CAPPO microVM authorities, a
real Lockerphycer cell-host backed by /dev/kvm + Firecracker, a real GitHub target
broker, and real PGL HTTP persistence/readback/chain verification.

A zero exit code means only that the tests executed by this invocation passed.
The emitted artifact remains VERIFIED_LOCAL_CANDIDATE until the raw substrate
facts and target/PGL evidence are independently reviewed.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.execution_cells.authority import authority_digest
from core.execution_cells.effects import GitHubFileUpdateIntent, effect_digest
from core.execution_cells.models import SignedAuthority
from core.execution_cells.pgl_client import PGLEvidenceError, RealPGLClient
from core.execution_cells.predator_contract import assert_canonical_result_ids


class ProbeFailure(RuntimeError):
    pass


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProbeFailure(f"required environment variable is missing: {name}")
    return value


def read_json(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProbeFailure(f"{path} must contain one JSON object")
    return value


def authority_from(env_name: str) -> tuple[dict[str, Any], SignedAuthority]:
    raw = read_json(required(env_name))
    return raw, SignedAuthority.model_validate(raw)


def assert_microvm_fixture(
    authority: SignedAuthority,
    *,
    image: str,
    intent: GitHubFileUpdateIntent,
    name: str,
    current: bool = True,
) -> None:
    envelope = authority.envelope
    if envelope.required_isolation != "microvm":
        raise ProbeFailure(f"{name} is not a microvm authority")
    if not envelope.runtime_kernel_digest:
        raise ProbeFailure(f"{name} does not bind a runtime kernel digest")
    if envelope.runtime_image_digest != image.rsplit("@", 1)[1].lower():
        raise ProbeFailure(f"{name} rootfs/image digest does not match PREDATOR_L3_IMAGE")
    if envelope.semantic_intent_digest != effect_digest(intent):
        raise ProbeFailure(f"{name} is not bound to the exact effect")
    if current:
        try:
            envelope.assert_current()
        except ValueError as exc:
            raise ProbeFailure(f"{name} is not currently usable: {exc}") from exc


class CellHost:
    def __init__(self, base_url: str, key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"x-cell-host-key": key, "content-type": "application/json"}
        self.client = httpx.Client(timeout=90.0, follow_redirects=False)

    def close(self) -> None:
        self.client.close()

    def health(self) -> dict[str, Any]:
        response = self.client.get(f"{self.base_url}/health")
        if response.status_code != 200:
            raise ProbeFailure(f"cell-host health returned HTTP {response.status_code}")
        body = response.json()
        if not isinstance(body, dict) or body.get("status") != "healthy":
            raise ProbeFailure("cell-host process health is not healthy")
        if body.get("microvm_configured") is not True:
            raise ProbeFailure("cell-host does not report Firecracker microVM configuration")
        return body

    def run(self, authority: dict[str, Any], image: str, intent: GitHubFileUpdateIntent) -> httpx.Response:
        return self.client.post(
            f"{self.base_url}/v1/cells/run",
            headers=self.headers,
            json={
                "authority": authority,
                "image": image,
                "command": ["/usr/local/bin/lockerphycer-cell-agent"],
                "input_payload": intent.model_dump(mode="json"),
                "safe_environment": {},
                "expected_effect_digest": effect_digest(intent),
            },
        )

    def effect(self, authority: dict[str, Any], intent: dict[str, Any]) -> httpx.Response:
        body = dict(intent)
        body["authority"] = authority
        return self.client.post(
            f"{self.base_url}/v1/effects/github/file-update",
            headers=self.headers,
            json=body,
        )


def reject(response: httpx.Response, test_id: str, *, detail: str | None = None) -> None:
    if response.status_code not in {403, 409}:
        raise ProbeFailure(f"{test_id} expected governed rejection, got HTTP {response.status_code}: {response.text[:500]}")
    if detail and detail.lower() not in response.text.lower():
        raise ProbeFailure(f"{test_id} rejected for wrong reason; expected {detail!r}, got {response.text[:500]}")
    print(f"[PASS] {test_id}: rejected with HTTP {response.status_code}")


def require_l3_result(response: httpx.Response, test_id: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise ProbeFailure(f"{test_id} microVM run failed HTTP {response.status_code}: {response.text[:1000]}")
    result = response.json()
    required_exact = {
        "runtime": "firecracker",
        "isolation_class": "microvm",
        "network_mode": "none",
        "credential_mode": "brokered_only",
        "teardown_confirmed": True,
        "timed_out": False,
        "exit_code": 0,
    }
    for field, expected in required_exact.items():
        if result.get(field) != expected:
            raise ProbeFailure(f"{test_id} invalid L3 witness {field}: expected {expected!r}, got {result.get(field)!r}")
    measurement = result.get("runtime_measurement")
    if not isinstance(measurement, str) or not measurement.startswith("sha256:"):
        raise ProbeFailure(f"{test_id} missing measured Firecracker runtime digest")
    if not isinstance(result.get("authority_digest"), str):
        raise ProbeFailure(f"{test_id} missing authority digest")
    return result


def main() -> int:
    cell = CellHost(
        os.environ.get("LOCKERPHYCER_CELL_HOST_URL", "http://127.0.0.1:8765"),
        required("LOCKERPHYCER_CELL_HOST_API_KEY"),
    )
    pgl = RealPGLClient(
        os.environ.get("PGL_BASE_URL", "http://127.0.0.1:8001"),
        required("PGL_API_KEY"),
    )
    pgl_agent = required("PGL_AGENT_ID")
    image = required("PREDATOR_L3_IMAGE")
    if "@sha256:" not in image:
        raise ProbeFailure("PREDATOR_L3_IMAGE must be immutable and pinned by @sha256")
    intent = GitHubFileUpdateIntent.model_validate(read_json(required("PREDATOR_GITHUB_INTENT_FILE")))

    a00_raw, a00 = authority_from("PREDATOR_L3_A00_AUTHORITY_FILE")
    a02_raw, a02 = authority_from("PREDATOR_L3_A02_AUTHORITY_FILE")
    a03_raw, a03 = authority_from("PREDATOR_L3_A03_AUTHORITY_FILE")
    a07_raw, a07 = authority_from("PREDATOR_L3_A07_AUTHORITY_FILE")
    for name, authority in (("A00", a00), ("A02", a02), ("A07", a07)):
        assert_microvm_fixture(authority, image=image, intent=intent, name=name)
    assert_microvm_fixture(a03, image=image, intent=intent, name="A03", current=False)
    try:
        a03.envelope.assert_current()
    except ValueError as exc:
        if "expired" not in str(exc).lower():
            raise ProbeFailure(f"A03 fixture is invalid for the wrong reason: {exc}") from exc
    else:
        raise ProbeFailure("A03 authority is not expired")

    execution_ids = {a00.envelope.execution_id, a02.envelope.execution_id, a03.envelope.execution_id, a07.envelope.execution_id}
    if len(execution_ids) != 4:
        raise ProbeFailure("L3 A00/A02/A03/A07 fixtures must use distinct execution IDs")

    passed: list[str] = []
    try:
        print("=" * 76)
        print("VEKLOM LOCKERPHYCER L3 FIRECRACKER/KVM PREDATOR — REAL BOUNDARIES")
        print("=" * 76)
        health = cell.health()
        print("[SUBSTRATE]", json.dumps(health, sort_keys=True))

        # A03 — signed but expired authority must fail before microVM allocation.
        reject(cell.run(a03_raw, image, intent), "A03 expired authority", detail="expired")
        passed.append("A03")

        # A07 — immutable rootfs/image substitution; a fresh authority prevents replay
        # from masquerading as digest-binding proof.
        wrong_image = image.rsplit("@sha256:", 1)[0] + "@sha256:" + ("0" * 64)
        reject(cell.run(a07_raw, wrong_image, intent), "A07 runtime-image digest mutation", detail="runtime image")
        passed.append("A07")

        # Signed-field substitutions are rejected by detached signature verification.
        a01 = copy.deepcopy(a00_raw)
        a01["envelope"]["capability_id"] = "admin-action"
        reject(cell.run(a01, image, intent), "A01 capability widening", detail="signature")
        passed.append("A01")

        a04 = copy.deepcopy(a00_raw)
        a04["envelope"]["subject_id"] = "substituted-principal"
        reject(cell.run(a04, image, intent), "A04 identity substitution", detail="signature")
        passed.append("A04")

        a05 = copy.deepcopy(a00_raw)
        a05["envelope"]["tenant_id"] = "substituted-tenant"
        reject(cell.run(a05, image, intent), "A05 tenant/workspace substitution", detail="signature")
        passed.append("A05")

        a06 = copy.deepcopy(a00_raw)
        a06["envelope"]["runtime_instance"] = "wrong-lockerphycer-host"
        reject(cell.run(a06, image, intent), "A06 audience/runtime-instance substitution", detail="signature")
        passed.append("A06")

        # A00 — genuine KVM/Firecracker execution, then one real target consequence.
        l3 = require_l3_result(cell.run(a00_raw, image, intent), "A00")
        target_response = cell.effect(a00_raw, intent.model_dump(mode="json"))
        if target_response.status_code != 200:
            raise ProbeFailure(f"A00 brokered target consequence failed HTTP {target_response.status_code}: {target_response.text[:1000]}")
        target = target_response.json()
        if target.get("mutation_succeeded") is not True or target.get("target_result_confirmed") is not True:
            raise ProbeFailure("A00 target did not independently confirm the mutation")
        if target.get("credential_revoked") is not True:
            raise ProbeFailure("A00 provider credential revocation was not positively confirmed")
        before_sha = target.get("before_sha")
        after_sha = target.get("after_blob_sha")
        if not isinstance(before_sha, str) or not isinstance(after_sha, str) or before_sha == after_sha:
            raise ProbeFailure("A00 target before/after state is not a confirmed physical change")
        passed.append("A00")

        # A08 — exact effect redelivery under the consumed authority must not create
        # another target consequence.
        reject(cell.effect(a00_raw, intent.model_dump(mode="json")), "A08 nonce/lease replay")
        passed.append("A08")

        # A02 — run a distinct real microVM successfully, then widen the resource at
        # the effect boundary.  The successful-cell digest binding must fail closed.
        require_l3_result(cell.run(a02_raw, image, intent), "A02 setup")
        widened = intent.model_dump(mode="json")
        widened["path"] = "unauthorized/" + str(widened["path"])
        reject(cell.effect(a02_raw, widened), "A02 resource widening")
        passed.append("A02")

        # A16 — the successful A00 result must positively report VMM teardown, and
        # the already-dead authority cannot be reused for another consequence.
        if l3.get("teardown_confirmed") is not True:
            raise ProbeFailure("A16 microVM teardown was not confirmed")
        reject(cell.run(a00_raw, image, intent), "A16 post-death authority reuse")
        passed.append("A16")

        # A17 — exact composed consequence crosses the real PGL network boundary.
        details = {
            "schema_version": "veklom.composition_consequence.v1",
            "profile": "L3-Firecracker-KVM-v1",
            "execution_id": a00.envelope.execution_id,
            "origin_identity": a00.envelope.subject_id,
            "tenant_id": a00.envelope.tenant_id,
            "workspace_id": a00.envelope.workspace_id,
            "authority_digest": authority_digest(a00),
            "capability_id": a00.envelope.capability_id,
            "semantic_intent_digest": a00.envelope.semantic_intent_digest,
            "runtime_image_digest": a00.envelope.runtime_image_digest,
            "runtime_kernel_digest": a00.envelope.runtime_kernel_digest,
            "runtime_measurement": l3.get("runtime_measurement"),
            "cell_id": l3.get("cell_id"),
            "isolation_class": "microvm",
            "network_mode": "none",
            "credential_mode": "brokered_only",
            "teardown_confirmed": True,
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
        pgl_witness = pgl.persist_and_verify(
            agent_id=pgl_agent,
            actor="lockerphycer-l3-predator",
            execution_id=a00.envelope.execution_id,
            idempotency_key=f"composition:l3:{a00.envelope.execution_id}",
            details=details,
        )
        if not pgl_witness.ledger_verification or not pgl_witness.event_readback_verified:
            raise ProbeFailure("A17 real PGL witness is incomplete")
        passed.append("A17")

        assert_canonical_result_ids(passed)
        evidence = {
            "status": "VERIFIED_LOCAL_CANDIDATE",
            "profile": "L3-Firecracker-KVM-v1",
            "execution_id": a00.envelope.execution_id,
            "authority_digest": authority_digest(a00),
            "cell_id": l3.get("cell_id"),
            "runtime_measurement": l3.get("runtime_measurement"),
            "runtime_image_digest": a00.envelope.runtime_image_digest,
            "runtime_kernel_digest": a00.envelope.runtime_kernel_digest,
            "network_mode": "none",
            "credential_mode": "brokered_only",
            "teardown_confirmed": True,
            "target_before": before_sha,
            "target_after": after_sha,
            "target_commit": target.get("commit_sha"),
            "credential_revoked": True,
            "pgl_event_id": pgl_witness.event_id,
            "pgl_event_hash": pgl_witness.event_hash,
            "pgl_chain_head": pgl_witness.chain_head,
            "pgl_chain_verified": True,
            "tests": passed,
            "not_executed_by_this_runner": ["A09", "A10", "A11", "A12", "A13", "A14", "A15", "A18", "A19"],
            "proof_boundary": "Candidate only; raw KVM/Firecracker, target, and PGL evidence must be independently reviewed before promotion.",
        }
        out = Path(os.environ.get("PREDATOR_L3_EVIDENCE_OUT", "predator_l3_evidence.json"))
        out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[DONE] L3 candidate evidence written to {out}")
        return 0
    except PGLEvidenceError as exc:
        raise ProbeFailure(f"A17 real PGL verification failed: {exc}") from exc
    finally:
        pgl.close()
        cell.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeFailure as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
