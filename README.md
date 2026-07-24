# Lockerphycer: branch findings + real MFA implementation

## Which branch to actually use

`main` and `devin/1779224412-enterprise-hardening` were compared directly
against the source, not the README. Use the enterprise-hardening branch —
it has real, wired-in code `main` doesn't:

| | main | enterprise-hardening |
|---|---|---|
| `core/security/auth.py` | 90 lines, JWT+session only | 280 lines: adds encryption, API key hashing, password strength, CSRF, input sanitization |
| Middleware | none of this | `SecurityMiddleware` (registered in `main.py` — confirmed active), `RateLimiter`, `RequestTracker`, `SecurityHeaders`, `IntrusionDetectionSystem` |
| Intrusion detection | none | Real: signature-matches URL/params/headers against SQLi, XSS, path-traversal, command-injection patterns, computes a risk score |
| "AI model" loading | 5-line honest placeholder, self-labeled as such | Real `torch`/`transformers` code exists, but is never called from any actual route — orphaned, not reachable by a real request |
| MFA / OAuth2 / SAML / LDAP / HSM | none | none |

Neither branch has any MFA, OAuth2, SAML, LDAP, or HSM code — that part of
the README's claims wasn't a "wrong branch" problem, it just wasn't built
anywhere. See below.

## Real, unrelated finding while testing: bcrypt/passlib version landmine

`passlib==1.7.4` (as pinned) breaks against `bcrypt>=4.1` — a known
ecosystem incompatibility, not something introduced here. If your
deployment ever resolves a newer bcrypt, password hashing breaks
everywhere it's used, not just in the new MFA code. Pin `bcrypt<4.1` in
requirements before this bites you in production.

## What's in this delivery

- `core/security/mfa.py` — real TOTP MFA. Built against the User model's
  existing `mfa_enabled`/`mfa_secret` columns, which were already in the
  schema and completely unused until now — this wasn't an absent feature,
  it was a half-built one.
- `apps/api/routers/mfa.py` — thin FastAPI routes over the tested service,
  using the same `get_current_user` dependency pattern already used
  elsewhere in the repo.
- `tests/test_mfa.py` — 18 checks, all passing, run against the **real**
  `User`/`Base` models copied from the actual repo and real bcrypt hashing
  — not stand-ins. Covers: secret + QR generation, rejecting a wrong code
  at setup, accepting a real time-based code, backup codes working exactly
  once each, and disable requiring a valid code rather than a bare flag
  flip.

```bash
pip install pyotp qrcode
PYTHONPATH=. python tests/test_mfa.py
```

## What wasn't built, and why that's a decision, not a shortcut

**OAuth2, SAML, LDAP/Active Directory, HSM** — these only mean anything
against a real external system: a real Google/Okta OAuth app, a real SAML
IdP, a real LDAP/AD server, a real HSM device. Writing integration code
against no real counterpart produces something that looks finished and
has never actually authenticated against anything — the exact failure
mode this whole audit was for. Building these for real needs you to name
the actual provider(s) you want first.

**SOC 2 Type II, ISO 27001, HIPAA compliance** — these aren't code. SOC 2
Type II specifically requires a licensed third-party auditor observing
your actual controls over a period of months; ISO 27001 requires an
accredited certification body audit; HIPAA compliance is signed BAAs,
policies, and workforce training, not a feature flag. No branch and no
amount of code changes this. The honest fix is removing those three
specific claims from the README until they're actually true, not writing
code to chase them — they were never a code problem.
