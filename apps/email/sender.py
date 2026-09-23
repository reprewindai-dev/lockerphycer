"""Provider-neutral transactional email delivery.

Veklom verification semantics must not depend on one delivery vendor. This module
uses standard SMTP and can fail over to a second independently configured relay.
"""

from __future__ import annotations

import html as html_lib
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Optional

from core.config.settings import settings

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _render(template_name: str, variables: dict) -> str:
    """Load an HTML template and substitute {{KEY}} placeholders."""
    path = TEMPLATES_DIR / template_name
    html = path.read_text(encoding="utf-8")
    for key, value in variables.items():
        html = html.replace("{{" + key + "}}", html_lib.escape(str(value), quote=True))
    return html


def _smtp_send(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    use_tls: bool,
    use_ssl: bool,
    to: str,
    subject: str,
    html: str,
) -> Optional[str]:
    """Send one message through a configured SMTP relay."""
    if not host:
        return None

    display_name, from_addr = parseaddr(settings.EMAIL_FROM)
    if not from_addr:
        logger.error("EMAIL_FROM is invalid")
        return None

    msg = EmailMessage()
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("This message requires an HTML-capable mail client.")
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    timeout = settings.SMTP_TIMEOUT_SECONDS

    try:
        if use_ssl:
            smtp = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            smtp = smtplib.SMTP(host, port, timeout=timeout)

        with smtp:
            smtp.ehlo()
            if use_tls and not use_ssl:
                smtp.starttls(context=context)
                smtp.ehlo()
            if user:
                smtp.login(user, password)
            refused = smtp.send_message(msg)

        if refused:
            logger.error("SMTP relay refused recipient(s): %s", sorted(refused))
            return None

        # SMTP does not provide a universal provider message ID. Generate a
        # local correlation ID from the Message-ID header if present.
        return msg.get("Message-ID") or f"smtp:{host}:{to}"
    except Exception:
        logger.exception("SMTP delivery attempt failed host=%s", host)
        return None


def _send(to: str, subject: str, html: str) -> Optional[str]:
    """Send via primary SMTP relay, then independent fallback relay."""
    if settings.EMAIL_TRANSPORT.lower() != "smtp":
        logger.error("Unsupported EMAIL_TRANSPORT=%s", settings.EMAIL_TRANSPORT)
        return None

    primary = _smtp_send(
        host=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        user=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        use_tls=settings.SMTP_TLS,
        use_ssl=settings.SMTP_SSL,
        to=to,
        subject=subject,
        html=html,
    )
    if primary:
        logger.info("Email accepted by primary SMTP transport correlation=%s", primary)
        return primary

    fallback = _smtp_send(
        host=settings.SMTP_FALLBACK_HOST,
        port=settings.SMTP_FALLBACK_PORT,
        user=settings.SMTP_FALLBACK_USER,
        password=settings.SMTP_FALLBACK_PASSWORD,
        use_tls=settings.SMTP_FALLBACK_TLS,
        use_ssl=settings.SMTP_FALLBACK_SSL,
        to=to,
        subject=subject,
        html=html,
    )
    if fallback:
        logger.warning("Primary SMTP unavailable; fallback accepted message correlation=%s", fallback)
        return fallback

    logger.error("All configured email transports unavailable")
    return None


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
