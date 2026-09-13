# Resend Production Setup for LockerPhycer

This document outlines the required production environment configuration to enable secure, authenticated transactional emails via Resend.

## Required Environment Variables

To operate the LockerPhycer identity layer in a production environment with Resend, you must supply the following environment variables in your .env or deployment configuration:

`env
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxx
EMAIL_FROM="Veklom <noreply@auth.veklom.com>"
FRONTEND_URL=https://veklom.com
EMAIL_VERIFICATION_EXPIRE_MINUTES=30
PASSWORD_RESET_EXPIRE_MINUTES=20
SECRET_KEY=<STABLE-PRODUCTION-SECRET-32+-CHARS>
`

## Critical Production Notes

1. **Domain Setup**: It is highly recommended to use a dedicated subdomain like uth.veklom.com as the sender (EMAIL_FROM) to protect the primary domain's reputation. You must register and verify this domain within your Resend dashboard.
2. **Stable Secret Key**: Do NOT generate a new SECRET_KEY on every deployment. Verification links and password reset JWTs are cryptographically signed using this key. Changing it will immediately invalidate all outstanding email verification and password reset links.
3. **Frontend URL**: Ensure FRONTEND_URL exactly matches the production domain (e.g., https://veklom.com with no trailing slash) as it is used to generate the callback URLs embedded in the emails.

## Operational Proof Checklist

To verify Resend is operationally sealed, run one full lifecycle test:

1. Sign up for a new account.
2. Verify you receive the verification email.
3. Click the verification link and ensure the account status changes to ACTIVE.
4. Log in successfully.
5. Request a password reset ("Forgot Password").
6. Verify you receive the reset email.
7. Complete the password reset flow.
8. Confirm that the old active session is invalidated.
9. Confirm that the old reset token cannot be reused (single-use token enforcement).

Once this cycle passes cleanly against the live Resend API, the authentication layer is operationally proven.
