# Locker Phycer

Locker Phycer is Veklom's **secret/key security domain**. This repository contains the FastAPI application, authentication/security utilities, persistence integrations, health/protocol surfaces, and integration points used to enforce that security boundary.

> [!IMPORTANT]
> Repository source describes intended behavior; it is not proof of a live deployment. Runtime evidence remains `UNVERIFIED` until the deployed commit SHA, HTTP/protocol identity, container listener, Traefik routing, and required integration evidence agree.

## Current responsibility

Locker Phycer owns **secret/key security and execution-security controls that are actually implemented here**. Local authentication utilities may verify callers for Lockerphycer APIs, but **Veklom ID remains the canonical identity-evidence domain**.

Lockerphycer does **not** become the source of truth for responsibilities owned elsewhere:

- **Veklom ID** — identity evidence;
- **cAPI / Covenant** — governed connection and capability discovery;
- **CAPPO** — fail-closed consequence authorization;
- **GnomLedger / PGL** — durable evidence, provenance, and lineage;
- **BYOS** — execution substrate where still applicable;
- **x402 / payment rails** — settlement, never execution authority.

The governed execution-cell work in this repository extends Lockerphycer's security boundary; it does not move policy or authority ownership out of CAPPO.

## Runtime contract

- reported Lockerphycer host-facing application port: **8092**;
- internal container port **8000** is valid behind Traefik when deployment configuration maps it correctly;
- cAPI commonly reports **3003**, but deployment truth comes from the current runtime, not this README;
- host port `8000` must not be claimed for Lockerphycer where it conflicts with Coolify/runtime ownership;
- deployment/runtime configuration is supplied by the deployment environment;
- secrets and internal credentials must not be committed.

API documentation is conditional on `DEBUG=true`. For local development, for example:

```bash
DEBUG=true uvicorn apps.api.main:app --reload --port 8092
```

then visit:

```text
http://localhost:8092/docs
```

That local URL is an example only; it does not establish production health or routing.

## Source layout

```text
lockerphycer/
├── apps/api/                 # FastAPI application and routes
├── core/config/              # Runtime settings
├── core/security/            # Security/authentication utilities
├── core/execution_cells/     # Governed execution-cell security primitives
├── core/database/            # Database integration
├── core/utils/               # Shared/integration utilities
├── cell_host/                # Narrow host-side governed-cell service
├── executor_images/          # Disposable governed workload images
├── db/                       # Models and migrations
├── tests/                    # Test suite
├── docs/                     # Documentation
├── docker-compose.yml        # Container composition
└── .env.example              # Non-secret configuration examples
```

Some paths above exist only after their corresponding reviewed feature work lands. Do not interpret a target path as production deployment evidence.

## Configuration

Start from `.env.example` and provide real deployment values through the deployment environment. Do not commit production values for `SECRET_KEY`, database/Redis credentials, provider keys, cAPI/CAPPO credentials, signing material, GitHub App private keys, or other secrets.

Configured URLs and ports are `CONFIGURED` evidence only. They are not `VERIFIED_LIVE` merely because they exist in source or environment configuration.

## Development

Install repository dependencies from the committed dependency files. The checked-in `ci` workflow currently performs Python dependency installation, `compileall`, and `pytest` when GitHub Actions successfully provisions a runner. Run equivalent checks locally when CI infrastructure does not execute.

```bash
python -m compileall apps core db tests
pytest -q
```

For container use, inspect the current Docker/Compose files rather than copying historical port or credential examples.

## Security and compliance truth boundary

The repository must not claim that the following are implemented, deployed, certified, or operational unless current attributable evidence proves the exact claim:

- HSM-backed key custody or key rotation;
- SGX/TDX, TEE, or hardware-enclave guarantees;
- "secrets never enter software memory";
- AES-256-at-rest or TLS-version guarantees for the deployed environment;
- predictive/behavioral threat analysis or automated incident response;
- auto-scaling, failover, backup/disaster-recovery, or multi-cloud operation;
- SOC 2 Type II, ISO 27001, HIPAA, GDPR, or other certification/compliance status;
- production uptime, latency, security posture, active deployment state, or other measured runtime claims.

Code presence is not deployment evidence. A health response is not protocol identity. Dependency reachability is not authorization/security verification. Use the canonical evidence vocabulary from `00_VEKLOM_BIBLE.md`: `VERIFIED_LIVE`, `VERIFIED_REPO`, `CONFIGURED`, `LAST_KNOWN`, `TARGET`, `UNVERIFIED`, `DEMO`, or `ARCHIVED`.

## Commercial truth boundary

Pricing, plan limits, seat counts, quotas, and commercial availability are not defined by this repository unless an explicitly designated commercial source of truth is introduced. Do not hard-code realistic pricing or customer-plan claims into architecture/runtime documentation.

## Verification before production claims

A production claim requires the relevant evidence chain, including as applicable:

1. exact deployed commit SHA;
2. actual container/process listener;
3. expected Lockerphycer HTTP/protocol identity;
4. Traefik route targeting the same listener;
5. required cAPI/CAPPO/GnomLedger integrations for the claimed path;
6. current executable source-test results;
7. additional security/dependency/runtime evidence only when those checks actually exist and have executed.

Until the evidence for a claimed property exists, that property remains `UNVERIFIED`.

## License

See [LICENSE](LICENSE).
