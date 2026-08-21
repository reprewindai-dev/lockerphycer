# Lockerphycer Governed Cell Host — P0

**Evidence status:** `VERIFIED_REPO` only after this branch's exact-head tests pass. This document does not claim a live deployment.

## Responsibility

Lockerphycer owns the physical execution-security boundary for one disposable governed action. CAPPO remains the sole consequence authority. GnomLedger/PGL remains the durable evidence system. The workload is untrusted.

The P0 cell host enforces:

- immutable image digest required (`@sha256:`);
- cryptographically verified CAPPO authority before spawn;
- authority expiry check;
- `--network none` for the workload;
- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- CPU, RAM, PID and wall-time limits;
- tmpfs-only `/tmp` and `/workspace`;
- non-root workload UID/GID;
- no upstream/provider credential in workload environment;
- explicit teardown plus post-teardown runtime inspection;
- brokered GitHub effect with exact operation + intent digest + current blob SHA binding;
- repository-scoped GitHub App installation token minted just in time and explicitly revoked after the attempt.

## Host boundary

Run `cell_host.app:app` on the execution host. Prefer rootless Podman. Bind Uvicorn to a Unix-domain socket, not a TCP listener:

```bash
install -d -m 0750 /run/lockerphycer
uvicorn cell_host.app:app \
  --uds /run/lockerphycer/cell-host.sock \
  --workers 1
```

Only the trusted CAPPO/execution-control process should receive filesystem access to this socket. Do **not** mount `/var/run/docker.sock`, `/run/podman/podman.sock`, or another unrestricted container-engine socket into an application or agent container.

Required deployment configuration:

```text
LOCKERPHYCER_CELL_HOST_API_KEY=<deployment secret; >=32 chars>
LOCKERPHYCER_CAPPO_AUTHORITY_KEYS_JSON={"<kid>":"<base64url raw Ed25519 public key>"}
LOCKERPHYCER_OCI_RUNTIME=/usr/bin/podman   # optional; auto-detected otherwise
```

For the GitHub P0 broker:

```text
LOCKERPHYCER_GITHUB_APP_ID=<app id>
LOCKERPHYCER_GITHUB_INSTALLATION_ID=<installation id>
LOCKERPHYCER_GITHUB_APP_PRIVATE_KEY_PEM=<deployment-held GitHub App private key>
LOCKERPHYCER_GITHUB_API_BASE=https://api.github.com
```

The GitHub App private key is broker material. It must never be put in a cell request, cell environment, model context, repository, log, or receipt.

## P0 consequence flow

```text
cAPI request
  -> CAPPO final authorization
  -> signed immutable authority envelope
  -> Lockerphycer cell host verifies signature + expiry
  -> offline disposable cell runs untrusted planning/transformation code
  -> cell returns structured effect intent only
  -> host broker verifies exact semantic-intent digest
  -> broker mints repo-scoped GitHub installation token
  -> broker re-reads target blob SHA
       mismatch -> deny, revoke token, no mutation
       match    -> perform exact file update
  -> revoke installation token
  -> destroy cell and verify teardown
  -> persist effect/result evidence to GnomLedger/PGL
```

## Still required before `VERIFIED_LIVE`

1. CAPPO must emit the exact signed envelope consumed here on the real consequence path.
2. A live host must run the cell host over a Unix-domain socket using the intended OCI runtime.
3. A real immutable executor image must be used.
4. Adversarial host/runtime tests must prove no network from the cell, no ambient credentials, quota enforcement, timeout kill, stale-state denial, replay denial and teardown.
5. GnomLedger/PGL must durably bind the authority digest, cell result, effect result and final target state.
6. Exact deployed SHAs and runtime evidence must agree before production claims.

The current P0 deliberately uses `network none` rather than a user-space allowlist. That makes raw IP, DNS, IPv6 and metadata-endpoint bypasses unavailable inside the cell itself. External access exists only in the trusted host broker.
