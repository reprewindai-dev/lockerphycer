# Transactional email provider profiles

Status: implementation guide for the provider-neutral SMTP sender and durable
identity outbox. These profiles are not live-account verification, DNS
verification, or evidence of inbox delivery. Only the generic SMTP transport is
implemented in this branch; provider-specific event webhooks are not.

The Veklom auth contract stays constant: account eligibility, one-time token
minting, expiry, and activation remain Veklom-owned. A relay's acceptance is
only `ACCEPTED`, never `DELIVERED`. A transport timeout after message
submission is `INDETERMINATE`; do not automatically switch vendors on an
ambiguous result, because that can send duplicate verification or reset links.

## First-wave providers

| Provider | SMTP host | Port / TLS | Authentication | Sender prerequisite |
| --- | --- | --- | --- | --- |
| Amazon SES | Region-specific SES SMTP endpoint | 587 / STARTTLS | Region-specific SES SMTP username and password; the SMTP password is not the AWS secret access key | Verify the sending identity in the same SES region; check sandbox/production sending status |
| Postmark | `smtp.postmarkapp.com` | 587 / STARTTLS | Prefer the SMTP token for the transactional message stream; keep transactional and broadcast streams separate | Verify the sender signature/domain and use the transactional stream |
| Mailgun | `smtp.mailgun.org` (use the regional endpoint provided for the account) | 587 / STARTTLS | SMTP credentials configured for the sending domain | Verify/authenticate that sending domain |
| Twilio SendGrid | `smtp.sendgrid.net` | 587 / STARTTLS | Username exactly `apikey`; password is a restricted SendGrid API key | Verify a sender identity/domain before sending |

All profiles use the same Veklom SMTP code path; no provider-specific SDK is
required. Provider docs and configuration details can change, so follow the
linked official setup page and verify the selected endpoint/credentials in the
provider account before use:

- Amazon SES: [SMTP endpoint and TLS](https://docs.aws.amazon.com/ses/latest/dg/smtp-connect.html), [SMTP credential requirements](https://docs.aws.amazon.com/ses/latest/dg/smtp-credentials.html)
- Postmark: [SMTP integration](https://postmarkapp.com/developer/user-guide/send-email-with-smtp)
- Mailgun: [SMTP sending](https://documentation.mailgun.com/docs/mailgun/user-manual/sending-messages/send-smtp)
- Twilio SendGrid: [SMTP API integration](https://www.twilio.com/docs/sendgrid/for-developers/sending-email/integrating-with-the-smtp-api)

## Configuration and qualification

1. Choose a provider account, region, transactional stream/domain, and sender
   address. No provider is presumed more reliable or more permissive than
   another.
2. Add the provider-issued SPF/DKIM records in Cloudflare exactly as supplied.
   Do not publish multiple SPF records at the same DNS name. Add DMARC only
   after checking the existing policy and reporting mailbox.
3. Inject the selected relay credentials through the deployment's secret
   mechanism. Do not place keys in source, support tickets, logs, or this file.
4. Set `EMAIL_FROM` to the sender identity that this provider verified, and
   set the SMTP fields for that account. Keep the optional fallback on a
   separate provider/account only after it passes the same acceptance tests.
5. Run the focused outbox and SMTP tests, then send one message to an
   operator-controlled inbox. Verify the link host, token expiry and
   single-use behavior, and check the provider activity/event record.
6. Only after those checks may the profile be called qualified. A local mock
   test or SMTP `250` response is not proof of inbox delivery.

## Provider competition without lock-in

The competitive asset is a tested, portable identity-delivery contract—not a
claim that one vendor is bad. Veklom can let operators switch relays using
configuration, preserve queued verification/reset intent across a provider
outage, avoid unsafe duplicate fallback after ambiguous acceptance, and keep
account authority independent from vendor status. Provider-specific APIs,
webhook authentication, event normalization, suppression, and delivery
reconciliation remain separate adapters to implement and test before claiming
those capabilities.

## Current rollout limit

The deployed LockerPhycer source revision still uses the Resend SDK directly;
this branch's provider-neutral outbox is not present in that release image.
This guide and the code change must be reviewed, integrated, deployed, and
qualified before it can restore public signup/reset mail. No account,
Cloudflare DNS, production secret, database, container, or public endpoint has
been changed by this branch.
