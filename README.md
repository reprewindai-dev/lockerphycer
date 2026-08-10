# Locker Phycer

Locker Phycer is a Veklom security, key, and identity service. This repository contains a FastAPI application, security/authentication utilities, persistence integrations, health/protocol surfaces, and integration points for other Veklom services.

> [!IMPORTANT]
> Repository source describes intended behavior; it is not proof of a live deployment. Runtime state remains `NOT_VERIFIED` until the deployed commit SHA, HTTP/protocol identity, container listener, and Traefik routing agree.

## Current responsibility

### Observed current responsibility

Locker Phycer currently provides the Veklom **governed security/key/identity surface**. Source includes authentication/security utilities, API routes, database/Redis configuration, protocol and dependency-health routes, and configuration for cAPI/CAPPO/Gnomledger/BYOS integration.

This repository does **not** become the source of truth for responsibilities owned elsewhere:

- **cAPI** — canonical Interlink / cross-service connection layer;
- **CAPPO** — governance and execution authorization;
- **Gnomledger** — durable evidence and provenance;
- **BYOS** — tenant/workspace execution substrate.

### Target responsibility

Future security capabilities may expand, but target architecture must not be documented as implemented or verified until source, tests, deployment configuration, and runtime evidence support the claim.

## Runtime contract

- canonical Locker Phycer application port: **8092**;
- canonical cAPI service port: **3003**;
- ports **3000** and **8000** are forbidden as Locker Phycer production/root application listeners or examples;
- deployment/runtime configuration is supplied by the deployment environment;
- secrets and internal credentials must not be committed.

Local API documentation, when the application is running on the canonical development/default port, is available at:

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
├── core/database/            # Database integration
├── core/utils/               # Shared/integration utilities
├── db/                       # Models and migrations
├── tests/                    # Test suite
├── docs/                     # Documentation
├── docker-compose.yml        # Container composition
└── .env.example              # Non-secret configuration examples
```

## Configuration

Start from `.env.example` and provide real deployment values through the deployment environment. In particular, do not commit production values for `SECRET_KEY`, database/Redis credentials, provider keys, cAPI/CAPPO credentials, or other secrets.

Current configuration defaults include Locker Phycer `8092` and cAPI `3003`. CAPPO, Gnomledger, and BYOS integration URLs are deployment-configured and must not be promoted to `VERIFIED` merely because a URL is configured or reachable.

## Development

Install repository dependencies using the dependency files committed for the current branch, then run the configured test and lint/security workflows before merge. A typical local application invocation is:

```bash
uvicorn apps.api.main:app --reload --port 8092
```

For container use, inspect the current Docker/Compose files rather than copying historical port or credential examples.

## Security and compliance truth boundary

The repository must not claim that the following are implemented, deployed, certified, or operational unless there is current attributable evidence:

- OAuth2, SAML, or LDAP/Active Directory integrations;
- HSM-backed key custody or key rotation;
- AES-256-at-rest or TLS-version guarantees for the deployed environment;
- predictive/behavioral threat analysis or automated incident response;
- auto-scaling, failover, backup/disaster-recovery, or multi-cloud operation;
- SOC 2 Type II, ISO 27001, HIPAA, GDPR, or other certification/compliance status;
- production uptime, latency, security posture, active deployment state, or other measured runtime claims.

Code presence is not deployment evidence, a health response is not protocol identity, and dependency reachability is not authorization/security verification. Where evidence is missing, use `NOT_VERIFIED`, `UNAVAILABLE`, or `NOT_IMPLEMENTED` as appropriate.

## Commercial truth boundary

Pricing, plan limits, seat counts, quotas, and commercial availability are not defined by this repository unless an explicitly designated commercial source-of-truth is introduced. Do not hard-code realistic pricing or customer-plan claims into architecture/runtime documentation.

## Verification before production claims

A production claim requires the relevant evidence chain, including as applicable:

1. exact deployed commit SHA;
2. application listener on canonical port `8092`;
3. expected Locker Phycer HTTP/protocol identity;
4. Traefik route targeting the same listener;
5. required cAPI/CAPPO/Gnomledger/BYOS integration handshakes;
6. current test, dependency, and security workflow results.

Until those agree, `verified_runtime_state` remains empty / `NOT_VERIFIED`.

## License

See [LICENSE](LICENSE).
