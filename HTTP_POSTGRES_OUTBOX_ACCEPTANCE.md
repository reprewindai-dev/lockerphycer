# Isolated HTTP registration durability — 2026-09-23

Result: PASS for the narrowly defined offline registration boundary. NOT live
production acceptance, email delivery proof, or a VLink seal.

Application source tested: bb4d63e. Dependency runtime:
`veklom/lockerphycer:rc1-candidate`, with source mounted read-only at /src.
API: `veklom-outbox-http-test-20260923`, uvicorn listening only on loopback 18092,
production mode, EMAIL_TRANSPORT=disabled. It shared the network namespace of
`veklom-outbox-durable-test-20260923`, whose network is none. No outbox worker was
started. No external mail call was possible. Database: dedicated `outbox_test`.
No production database, secret, service, or account was modified.

Procedure: `scripts/test_outbox_http_postgres.py seed` made actual HTTP requests
to the full FastAPI application (not TestClient, route overrides, or ORM signup).
Registration returned 201; login returned 403. Independent PostgreSQL query found:

- User 570752f8-d046-4d41-85fb-bd9933c71f30: INACTIVE.
- Outbox ef421831-5ec2-4b47-a885-8b5014108ae1: QUEUED, attempts=0.

Stopped the isolated API, restarted the dedicated PostgreSQL container, started
the API, and ran the script's verify phase with both original IDs. Login remained
403 and the exact same user/outbox IDs and states persisted. Both phases exited 0.
The first seed invocation preceded API readiness and failed connection-refused;
no registration occurred until startup was confirmed and seed was retried.

Limitations: this does not prove migrations against production, real SMTP,
delivery, activation, frontend handoff, or any downstream VLink/consequence gate.
The test uses a controlled operator address in an isolated test database only.
