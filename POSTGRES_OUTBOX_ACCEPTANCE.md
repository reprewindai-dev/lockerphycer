# Isolated PostgreSQL outbox acceptance — 2026-09-23

Base: b4d0e86; includes local username-exchange retirement and test script.
No production database or delivery provider was accessed by these tests.

Database: dedicated `veklom-outbox-durable-test-20260923`, postgres:16-alpine,
network disabled, Docker-managed database volume (not tmpfs). Application test
containers share only this test container network namespace. Source mounted
read-only at /src, PYTHONPATH=/src; work directory /tmp; disposable tmpfs /tmp.

Executed `python -m scripts.test_outbox_postgres seed`, restarted the database
with `docker restart veklom-outbox-durable-test-20260923`, then executed
`python -m scripts.test_outbox_postgres verify` in a fresh application process.

Observed:
- PASS: inactive identity and intent persisted without transport invocation.
- PASS: both survived the real database container restart.
- PASS: 12 concurrent enqueuers retained one intent with the same ID.
- PASS: 12 concurrent workers produced one test-transport call and ACCEPTED.
- PASS: a persisted INDETERMINATE claim was not replayed.

Limits: registration here uses the database enqueue path, not public HTTP;
SMTP is replaced with a local callable for worker concurrency testing. The
indeterminate claim is injected, not produced by killing a sending worker.
This is not inbox-delivery proof, production acceptance, or a VLink seal.
The separate HTTP registration regression uses SQLite, not PostgreSQL.

Still required: HTTP registration against PostgreSQL, production backup and
additive migration, safe deployment, real controlled-inbox delivery, full
workspace/VLink/governed-consequence/revocation acceptance.
