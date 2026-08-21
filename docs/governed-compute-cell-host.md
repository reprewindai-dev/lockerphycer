# Lockerphycer Governed Cell Host — P0

**Evidence status:** `UNVERIFIED` until the exact-head source checks execute successfully and a production-equivalent host produces the required runtime/adversarial evidence. Source presence is not a live deployment claim.

## Responsibility

Lockerphycer owns the physical execution-security boundary for one disposable governed action. CAPPO remains the sole consequence authority. GnomLedger/PGL remains the durable evidence system. The workload is untrusted.

The P0 deliberately supports two different containment classes without conflating their claims:

- **Level 2 / `os-enforced`** — Podman/Docker cell with a shared host kernel, no workload network, read-only root, dropped Linux capabilities, `no-new-privileges`, non-root UID/GID, CPU/RAM/PID/wall-time limits, tmpfs-only writable areas, no provider credential, explicit teardown and brokered effects.
- **Level 3 / `microvm`** — Firecracker/KVM cell with a separate guest kernel, measured kernel/rootfs, read-only rootfs, **no guest network interface**, vsock-only host/guest communication, no provider credential, host-enforced wall time and positive VMM-process teardown.

A CAPPO-signed `required_isolation=microvm` authority must never silently downgrade to the OCI runtime. If KVM, Firecracker, or the measured artifacts are unavailable, execution fails closed.

## Host boundary

Run `cell_host.app:app` on the execution host and bind Uvicorn to a Unix-domain socket, not a TCP listener. The host API key authenticates the local controller call; it does not replace CAPPO's signed consequence authority.

Use an explicitly writable private replay-state directory. Do not rely on `/var/lib` being writable under a rootless service account:

```bash
install -d -m 0750 /run/lockerphycer
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/lockerphycer"
install -d -m 0700 "$STATE_DIR"

export LOCKERPHYCER_REPLAY_DB="$STATE_DIR/cell-host-replay.sqlite3"

uvicorn cell_host.app:app \
  --uds /run/lockerphycer/cell-host.sock \
  --workers 1
```

Only the trusted CAPPO/execution-control process should receive filesystem access to the UDS. Do **not** mount `/var/run/docker.sock`, `/run/podman/podman.sock`, `/dev/kvm`, or unrestricted host-runtime control into an application/agent container. The cell-host process itself owns the narrow execution-host capability.

## Required common configuration

```text
LOCKERPHYCER_CELL_HOST_API_KEY=<deployment secret; >=32 chars>
LOCKERPHYCER_CELL_HOST_INSTANCE=<stable audience id for this exact execution host>
LOCKERPHYCER_CAPPO_AUTHORITY_KEYS_JSON={"<kid>":"<base64url raw Ed25519 public key>"}
LOCKERPHYCER_REPLAY_DB=<private writable host-state path>
```

`LOCKERPHYCER_CELL_HOST_INSTANCE` must equal the CAPPO-signed `runtime_instance`. A valid authority for another Lockerphycer host is rejected.

## Level 2 OCI configuration

```text
LOCKERPHYCER_OCI_RUNTIME=/usr/bin/podman   # optional; auto-detected if omitted
```

The signed authority must bind the exact OCI image digest used by the request. The workload gets `--network none`; this removes normal IP/DNS/metadata routes at the container-runtime boundary, but the OCI class still shares the host kernel and is therefore not a Level-3 hard-isolation claim.

## Level 3 Firecracker configuration

Build the minimal credential-less guest rootfs with:

```bash
sudo ./scripts/build_firecracker_rootfs.sh
```

The script builds the Rust vsock agent, creates a small read-only ext4 rootfs, and emits its SHA-256 measurement. Supply a separately controlled Firecracker-compatible kernel and measure it as well.

Required host configuration:

```text
LOCKERPHYCER_FIRECRACKER_BINARY=/usr/local/bin/firecracker
LOCKERPHYCER_FIRECRACKER_KERNEL=/opt/lockerphycer/vmlinux
LOCKERPHYCER_FIRECRACKER_KERNEL_SHA256=sha256:<64 hex>
LOCKERPHYCER_FIRECRACKER_ROOTFS=/opt/lockerphycer/lockerphycer-rootfs.ext4
LOCKERPHYCER_FIRECRACKER_ROOTFS_SHA256=sha256:<64 hex>
LOCKERPHYCER_FIRECRACKER_STATE_DIR=/run/lockerphycer/firecracker
LOCKERPHYCER_FIRECRACKER_GUEST_PORT=5000
```

The host validates observed kernel/rootfs hashes against deployment configuration **and** against the CAPPO-signed authority before allocation. `/dev/kvm` must exist. The Firecracker API is host-local over a Unix socket.

For the first GitHub consequence, Lockerphycer does not configure a Firecracker `/network-interfaces` device. The guest has no direct IP route, DNS resolver path, or cloud metadata path. Its only operation channel is virtio-vsock. Firecracker's documented host-initiated vsock protocol is used: host connects to the configured AF_UNIX socket, sends `CONNECT <guest-port>\n`, receives the `OK ...` acknowledgement, and then exchanges a bounded length-prefixed message with the guest effect agent.

## GitHub P0 broker

```text
LOCKERPHYCER_GITHUB_APP_ID=<app id>
LOCKERPHYCER_GITHUB_INSTALLATION_ID=<installation id>
LOCKERPHYCER_GITHUB_APP_PRIVATE_KEY_PEM=<deployment-held GitHub App private key>
LOCKERPHYCER_GITHUB_API_BASE=https://api.github.com
```

The GitHub App private key is broker material. It must never be put in a cell request, cell environment, model context, guest rootfs, log, or receipt.

## P0 consequence flow

```text
cAPI request
  -> CAPPO final authorization
  -> CAPPO signs exact one-time cell authority
       identity / tenant / operation / effect digest
       target precondition / TTL / limits / host audience
       required isolation / runtime artifact measurements
  -> Lockerphycer verifies signature + current authority
  -> allocate the exact authorized containment class
  -> run credential-less / network-less untrusted executor
  -> validate exact structured effect output
  -> positively destroy the hostile cell
  -> persist successful-cell digest binding in replay fence
  -> trusted host broker verifies the exact binding
  -> mint one repo-scoped GitHub installation token
  -> re-read target blob SHA
       mismatch -> deny, revoke token, no mutation
       match    -> re-check authority immediately before write
  -> GitHub conditional update using expected blob SHA
  -> preserve accepted consequence even if response evidence is incomplete
  -> positively revoke JIT token (204 required)
  -> CAPPO/GnomLedger evidence path seals the result
```

For this P0, target credential lifetime and hostile workload lifetime intentionally do **not** overlap: the cell is destroyed before the broker mints the GitHub token.

## Level 4 acceptance contract

A cell is **not** Level 4 merely because it uses Firecracker. `VERIFIED_LIVE` requires all of the following against the production-equivalent runtime:

1. **Target-state revalidation** at the last mutation boundary, plus target-native conditional write semantics where supported.
2. **Independently signed/tamper-evident evidence** tying CAPPO authority, runtime measurement, containment facts, before/after target state, outcome and cost/resource observations into GnomLedger/PGL.
3. **Positive teardown and revocation evidence**. Cell exit alone is not teardown proof; credential expiry alone is not revocation proof.
4. **Adversarial containment testing** against raw IPv4/IPv6, DNS/proxy/redirect attempts, metadata endpoints, host filesystem/PID/IPC/device/runtime-socket escape attempts, authority tampering/replay/wrong-audience use, resource exhaustion, kill/revoke during execution, and post-termination identity/route/credential reuse.

A missing required witness, unconfirmed credential revocation, unconfirmed teardown, or evidence persistence failure must produce `FAILED_UNVERIFIED`/`UNVERIFIED` rather than a completed governed-compute claim.

## Claim boundary

Use the measured claim:

> Independently enforced, evidence-verified containment, where each action is bounded by its authorized resource, credential, network, target-state, runtime and lifetime constraints.

Do not claim zero blast radius, mathematically impossible escape, or a universally bounded consequence space. Hard isolation removes the ordinary shared-guest-kernel path; the declared threat model still includes the host kernel, VMM, hardware/firmware, supply chain, target provider and configuration.
