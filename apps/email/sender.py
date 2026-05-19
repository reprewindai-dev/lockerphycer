"""
Veklom Email Sender — Resend integration for transactional emails.

Usage:
    from apps.email.sender import send_welcome, send_verify_email, ...

Each function loads the matching HTML template from apps/email/templates/,
substitutes {{VARIABLE}} placeholders, and sends via Resend.
"""

import html as html_lib
import logging
import os
from pathlib import Path
from typing import Optional

try:
    import resend
except ImportError:
    resend = None  # type: ignore[assignment]

from core.config.settings import settings

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _init_resend() -> bool:
    """Ensure the Resend SDK is configured. Returns True if ready."""
    if resend is None:
        logger.warning("resend package not installed — email sending disabled")
        return False
    api_key = settings.RESEND_API_KEY or os.environ.get("RESEND_API_KEY")
    if not api_key:
        logger.warning("RESEND_API_KEY not set — email sending disabled")
        return False
    resend.api_key = api_key
    return True


def _render(template_name: str, variables: dict) -> str:
    """Load an HTML template and substitute {{KEY}} placeholders."""
    path = TEMPLATES_DIR / template_name
    html = path.read_text(encoding="utf-8")
    for key, value in variables.items():
        html = html.replace("{{" + key + "}}", html_lib.escape(str(value), quote=True))
    return html


def _send(to: str, subject: str, html: str) -> Optional[str]:
    """Send an email via Resend. Returns the message ID or None on failure."""
    if not _init_resend():
        return None
    try:
        params = {
            "from": settings.EMAIL_FROM,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        resp = resend.Emails.send(params)
        msg_id = resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None)
        logger.info("Email sent — id=%s", msg_id)
        return msg_id
    except Exception:
        logger.exception("Failed to send email")
        return None


# ---------------------------------------------------------------------------
# Public helpers — one per template
# ---------------------------------------------------------------------------


def send_welcome(to: str, first_name: str) -> Optional[str]:
    html = _render("welcome.html", {"FIRST_NAME": first_name})
    return _send(to, f"Welcome to Veklom, {first_name}", html)


def send_verify_email(to: str, first_name: str, verify_url: str) -> Optional[str]:
    html = _render(
        "verify-email.html", {"FIRST_NAME": first_name, "VERIFY_URL": verify_url}
    )
    return _send(to, "Verify your email address", html)


def send_password_reset(to: str, first_name: str, reset_url: str) -> Optional[str]:
    html = _render(
        "password-reset.html", {"FIRST_NAME": first_name, "RESET_URL": reset_url}
    )
    return _send(to, "Reset your password", html)


def send_subscription_confirmation(
    to: str,
    first_name: str,
    plan_name: str,
    billing_period: str,
    amount: str,
    next_billing_date: str,
) -> Optional[str]:
    html = _render(
        "subscription-confirmation.html",
        {
            "FIRST_NAME": first_name,
            "PLAN_NAME": plan_name,
            "BILLING_PERIOD": billing_period,
            "AMOUNT": amount,
            "NEXT_BILLING_DATE": next_billing_date,
        },
    )
    return _send(to, f"Your {plan_name} subscription is confirmed", html)


def send_team_invite(
    to: str,
    inviter_name: str,
    team_name: str,
    team_initial: str,
    team_member_count: int,
    team_plan: str,
    invite_url: str,
) -> Optional[str]:
    html = _render(
        "team-invite.html",
        {
            "INVITER_NAME": inviter_name,
            "TEAM_NAME": team_name,
            "TEAM_INITIAL": team_initial,
            "TEAM_MEMBER_COUNT": str(team_member_count),
            "TEAM_PLAN": team_plan,
            "INVITE_URL": invite_url,
        },
    )
    return _send(to, f"{inviter_name} invited you to {team_name}", html)
