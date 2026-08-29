# Veklom Cross-System Predator — Live Proof Contract

**Evidence status:** SOURCE_IMPLEMENTED. This document does not promote Lockerphycer L2, A17, or the foundational baseline. Runtime status changes only after a real substrate run produces independently reviewable evidence.

## Purpose

`scripts/predator_composition_probe.py` is the fail-closed witness for the live chain:

```text
independently signed CAPPO authority
  -> Lockerphycer cell-host
  -> real OCI cell
  -> real GitHub consequence broker
  -> real PGL event persistence
  -> exact event readback
  -> real PGL chain verification
```

There is no mock target, mock ledger, locally forged authority, or success fallback in this proof path.

## Required runtime services

1. Lockerphycer `cell_host.app` reachable at `LOCKERPHYCER_CELL_HOST_URL` (default `http://127.0.0.1:8765`).
2. Podman or Docker runtime selected by the cell host with the existing L2 `os-enforced` profile.
3. Real GitHub broker credentials configured on the cell host. Provider credentials must never be passed to the untrusted workload.
4. Real GnomLedger/PGL reachable at `PGL_BASE_URL` (default `http://127.0.0.1:8001`).
5. A real PGL agent ID and API key with permission to persist and verify ledger events.
6. CAPPO public verification key configured on the cell host.

## Required non-secret fixtures

The harness consumes four distinct, independently signed CAPPO authority files. It does not mint or repair them:

- `PREDATOR_AUTHORITY_FILE`: current authority for A00/A01/A04/A06/A10/A17.
- `PREDATOR_A02_AUTHORITY_FILE`: fresh current authority for the resource-widening test.
- `PREDATOR_A03_AUTHORITY_FILE`: validly signed but expired authority for the expiration test.
- `PREDATOR_A09_AUTHORITY_FILE`: fresh current authority for runtime-image substitution.

All four fixtures must bind the exact same immutable runtime image and exact intended GitHub effect, while using distinct execution IDs. The A03 fixture must already be expired when the probe begins.

The GitHub effect fixture is supplied as `PREDATOR_GITHUB_INTENT_FILE` and must match the signed `semantic_intent_digest`.

`PREDATOR_IMAGE` must use an immutable reference containing `@sha256:` and its digest must equal each fixture's signed `runtime_image_digest`.

## Secrets

Secrets belong only in process environment or the platform secret store. Never commit:

- `LOCKERPHYCER_CELL_HOST_API_KEY`
- `PGL_API_KEY`
- provider/GitHub App private keys or installation tokens
- CAPPO private signing keys

The probe requires only verifier-consumable signed authority documents, not the CAPPO private key.

## Current test IDs

| ID | Property | Evidence mechanism |
|---|---|---|
| A00 | Positive governed consequence | real cell -> real GitHub before/after state -> target confirmation |
| A01 | Capability widening | tamper signed capability; Ed25519 verification must reject |
| A02 | Resource widening | fresh successful cell, then mutated resource at effect boundary; successful-cell/effect binding must reject |
| A03 | Expired authority | independently signed expired fixture must be rejected before execution |
| A04 | Identity substitution | tamper signed subject identity; signature verification must reject |
| A06 | Tenant substitution | tamper signed tenant; signature verification must reject |
| A09 | Runtime-image substitution | fresh authority plus wrong immutable image digest must be rejected before cell execution |
| A10 | Replay | exact successful effect is redelivered; durable replay store must reject |
| A17 | PGL consequence binding | exact consequence details persisted to real PGL, read back, and chain verified |

The wider A00–A19 conformance matrix remains open until each property has a real boundary-specific witness. A passing subset must never be described as the complete Predator profile.

## L2 hostile witness inside A00

The A00 workload attempts and records:

- public IPv4 connection
- DNS resolution
- metadata endpoint access
- raw socket creation
- Docker socket access
- Podman socket access
- access to a host-created sentinel file
- write to the read-only root filesystem
- effective capability mask (`CapEff`)
- bounding capability mask (`CapBnd`)
- namespace PID data (`NSpid`)
- UID/GID
- declared network and credential contracts

The controller must separately return `teardown_confirmed=true`. A workload claim is not accepted as teardown proof.

## A17 acceptance rule

A17 passes only if all of the following happen through the real PGL HTTP API:

1. `POST /api/v1/ledger/events` returns HTTP 201 and `persisted=true`.
2. The returned `event_id` is fetched with `GET /api/v1/ledger/events/{event_id}`.
3. Canonical digest of the read-back `details` exactly matches the submitted consequence evidence.
4. The returned event hash is unchanged between persistence and readback.
5. `GET /api/v1/ledger/agents/{agent_id}/verify` returns `status=verified` and `valid=true`.

Any missing service, malformed response, readback mismatch, or unverified chain is a hard failure. `RealPGLClient` has no mock fallback.

## Run

From the repository root after the cell host and PGL are healthy:

```powershell
$env:LOCKERPHYCER_CELL_HOST_URL = "http://127.0.0.1:8765"
$env:LOCKERPHYCER_CELL_HOST_API_KEY = "<secret-from-local-secret-store>"
$env:PGL_BASE_URL = "http://127.0.0.1:8001"
$env:PGL_API_KEY = "<secret-from-local-secret-store>"
$env:PGL_AGENT_ID = "<existing-real-agent-id>"
$env:PREDATOR_IMAGE = "docker.io/library/python@sha256:<exact-digest>"
$env:PREDATOR_GITHUB_INTENT_FILE = "<path-to-intent.json>"
$env:PREDATOR_AUTHORITY_FILE = "<path-to-a00-authority.json>"
$env:PREDATOR_A02_AUTHORITY_FILE = "<path-to-a02-authority.json>"
$env:PREDATOR_A03_AUTHORITY_FILE = "<path-to-expired-a03-authority.json>"
$env:PREDATOR_A09_AUTHORITY_FILE = "<path-to-a09-authority.json>"
$env:PREDATOR_EVIDENCE_OUT = "predator_composition_evidence.json"
python scripts/predator_composition_probe.py
```

Do not paste secrets into evidence reports or commit them to Git.

## Status transition rule

A zero exit code is necessary but not sufficient for a proof-status change. Before promotion, review the raw run, target commit/before-after facts, cell runtime facts, PGL event/readback/chain facts, and failure traces. The harness emits `VERIFIED_LOCAL_CANDIDATE` deliberately so the code cannot seal its own proof.
