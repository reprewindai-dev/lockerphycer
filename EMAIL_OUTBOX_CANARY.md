# Identity delivery outbox — PR #44 continuation

Base: PR #44 at 4a530e7. This change is not deployed, not a release seal, and
does not claim any inbox delivery. Preserve the existing signing key and users.

## Contract

Registration atomically commits an INACTIVE user and QUEUED verification intent.
If the database transaction fails, neither survives. An SMTP outage is never
consulted by the registration transaction. Verification remains mandatory.
Reset and verification resend use the same durable outbox, with generic queued
responses. A user/kind lock coalesces outstanding intents on PostgreSQL; a
one-minute cooldown covers recently completed attempts.

No tokens or rendered secret links are persisted in the outbox. The worker
mints a short-lived token at dispatch. Reset intents are bound to the password
version at enqueue. Intents expire after 24 hours; obsolete/ineligible intents
become FAILED, never activate accounts. Token lifetime text comes from settings.

QUEUED -> INDETERMINATE (durably claimed before transport) -> ACCEPTED or
QUEUED with backoff, or FAILED after five attempts. If a worker dies or SMTP
completion is ambiguous, INDETERMINATE remains for operator reconciliation.
It is never blindly replayed. This favors duplicate avoidance over automatic
recovery in the crash window. SMTP has no universal exactly-once guarantee.
ACCEPTED means relay acceptance, NOT delivery. DELIVERED requires a future
authenticated delivery-event reconciliation adapter; none is claimed here.

## Deployment prerequisites (not performed by this change)

1. Review/integrate this canary; preserve unrelated dirty work and frozen images.
2. Back up the target database and run the additive migration using the new image:
   `python -m scripts.create_identity_email_outbox`. It creates only the new table.
3. Deploy the API and a separately supervised worker from the SAME image/config:
   `python -m apps.email.outbox_worker`. Keep existing SECRET_KEY and DATABASE_URL.
4. Configure tested primary/fallback SMTP relays with TLS; remove Resend runtime
   credentials from Compose/environment. No console-success fallback is allowed.
5. Check queue age/status, worker availability, failed/indeterminate records.
   This worker has no auto-start in the API and is not yet wired into live Compose.
6. Use only an operator-controlled real inbox for deliberate delivery acceptance.
   Do not replay historical synthetic acceptance traffic. Do not bypass verification.

Production HTTPS origin validation rejects local/private IPs and localhost names.
DNS correctness/delivery still require runtime verification. No DNS, live mail,
production migrations or container changes are made by these isolated tests.

## Remaining release work

PostgreSQL multi-worker/concurrent-enqueue/crash acceptance; deploy worker with
monitoring; controlled inbox delivery and delivery evidence; public frontend
queued-state wording; full identity/workspace/VLink/consequence/revocation run.
Production is unchanged until those deployment actions are explicitly performed.
