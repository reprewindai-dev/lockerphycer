#!/usr/bin/env python3
"""
create_all_templates.py — Upload all 5 Veklom email templates to Resend.

Usage:
    RESEND_API_KEY=re_xxxxx python scripts/create_all_templates.py

Requires:
    pip install resend

This script reads each HTML file from apps/email/templates/, creates (or
updates) the corresponding email template in Resend, and prints a summary.
"""

import os
import sys
from pathlib import Path

try:
    import resend
except ImportError:
    print("ERROR: 'resend' package not installed. Run: pip install resend")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "apps" / "email" / "templates"

TEMPLATES = [
    {
        "file": "welcome.html",
        "name": "Veklom — Welcome",
        "subject": "Welcome to Veklom, {{FIRST_NAME}}",
    },
    {
        "file": "verify-email.html",
        "name": "Veklom — Email Verification",
        "subject": "Verify your email address",
    },
    {
        "file": "password-reset.html",
        "name": "Veklom — Password Reset",
        "subject": "Reset your password",
    },
    {
        "file": "subscription-confirmation.html",
        "name": "Veklom — Subscription Confirmed",
        "subject": "Your {{PLAN_NAME}} subscription is confirmed",
    },
    {
        "file": "team-invite.html",
        "name": "Veklom — Team Invitation",
        "subject": "{{INVITER_NAME}} invited you to {{TEAM_NAME}}",
    },
]

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("ERROR: Set the RESEND_API_KEY environment variable before running.")
        print("       RESEND_API_KEY=re_xxxxx python scripts/create_all_templates.py")
        sys.exit(1)

    resend.api_key = api_key

    print("=" * 60)
    print("  Veklom — Resend Email Template Uploader")
    print("=" * 60)
    print()

    created = 0
    failed = 0

    for tmpl in TEMPLATES:
        html_path = TEMPLATES_DIR / tmpl["file"]
        if not html_path.exists():
            print(f"  SKIP  {tmpl['file']} — file not found at {html_path}")
            failed += 1
            continue

        html_content = html_path.read_text(encoding="utf-8")

        print(f"  UPLOADING  {tmpl['file']}  →  \"{tmpl['name']}\"")

        try:
            # Resend Emails API — create a batch-send-ready template.
            # The Resend Python SDK exposes resend.Emails for sending;
            # for template management we use the lower-level HTTP client
            # since the SDK may not expose the /emails/templates endpoint
            # in every version.  We try the SDK method first, then fall
            # back to a direct HTTP call.
            _create_via_sdk(tmpl, html_content)
            print(f"  OK     {tmpl['name']}")
            created += 1
        except Exception as exc:
            print(f"  FAIL   {tmpl['name']} — {exc}")
            failed += 1

    print()
    print("-" * 60)
    print(f"  Done.  Created: {created}  |  Failed: {failed}")
    print("-" * 60)


def _create_via_sdk(tmpl: dict, html_content: str) -> None:
    """Attempt to create the template via the Resend SDK or HTTP fallback."""
    import json
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError

    url = "https://api.resend.com/emails/templates"
    payload = json.dumps(
        {
            "name": tmpl["name"],
            "subject": tmpl["subject"],
            "html": html_content,
        }
    ).encode("utf-8")

    req = Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {resend.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            template_id = body.get("id", "unknown")
            print(f"           template_id: {template_id}")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend API {exc.code}: {error_body}") from exc


if __name__ == "__main__":
    main()
