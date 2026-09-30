"""Locked commercial model: plans and credit schedule.

Source: owner-locked commercial model (2026-09-30). Structure and action keys
are reused from veklom_billing_orchestrator.py (PLANS / CREDIT_SCHEDULE); the
numbers there (Free 400, Pro $29.99, ...) are superseded by the locked model.

There is deliberately no credit<->currency peg in this module.
"""

from __future__ import annotations

from core.entitlements.config import EntitlementSettings

# Credit schedule, exactly as on the owner's card. Keys match the reference
# orchestrator's CREDIT_SCHEDULE so existing references stay valid.
CREDIT_SCHEDULE: dict[str, int] = {
    "verification_read": 5,
    "standard_governed_action": 15,
    "governed_execution": 25,
    "payment_authorization": 100,
    "external_spend_orchestration": 250,
    "critical_consequence": 500,
}

# Friendly aliases accepted by the meter (card wording).
ACTION_ALIASES: dict[str, str] = {
    "governed_action": "standard_governed_action",
    "external_spend": "external_spend_orchestration",
}

# Action types that are reads: never blocked for lack of credits (fail safe).
READ_ACTIONS = frozenset({"verification_read"})

WELCOME = "welcome"
DEVELOPER = "developer"
PRO = "pro"
TEAM = "team"
ENTERPRISE = "enterprise"
PAID_PLANS = frozenset({PRO, TEAM, ENTERPRISE})
PLAN_IDS = frozenset({DEVELOPER, PRO, TEAM, ENTERPRISE})


def normalize_action(action_type: str) -> str:
    key = ACTION_ALIASES.get(action_type, action_type)
    if key not in CREDIT_SCHEDULE:
        raise KeyError(action_type)
    return key


def plan_catalog(cfg: EntitlementSettings) -> dict[str, dict]:
    """Plan limits. ``None`` means "not specified by the owner" (not unlimited)."""
    return {
        DEVELOPER: {
            "id": DEVELOPER,
            "name": "Developer",
            "price_usd_monthly": 0,
            "monthly_credits": 250,
            "users": 1,
            "agents": 1,
            "retention_days": 7,
            "outbound": "sandbox",
            "topups_allowed": True,
        },
        PRO: {
            "id": PRO,
            "name": "Pro",
            "price_usd_monthly": 99,
            "monthly_credits": 5_000,
            "users": 5,
            "agents": None,
            "retention_days": 90,
            "outbound": "production",
            "topups_allowed": True,
        },
        TEAM: {
            "id": TEAM,
            "name": "Team",
            "price_usd_monthly": 399,
            "monthly_credits": 20_000,
            "users": 25,
            "agents": None,
            "retention_days": cfg.TEAM_RETENTION_DAYS,
            "outbound": "production",
            "topups_allowed": True,
        },
        ENTERPRISE: {
            "id": ENTERPRISE,
            "name": "Enterprise",
            "price_usd_monthly": None,  # custom
            "monthly_credits": None,  # custom contract; set per workspace
            "users": None,
            "agents": None,
            "retention_days": None,
            "outbound": "custom",
            "topups_allowed": True,
        },
    }


def welcome_limits(cfg: EntitlementSettings) -> dict:
    return {
        "id": WELCOME,
        "name": "Welcome",
        "price_usd_monthly": 0,
        "monthly_credits": cfg.WELCOME_CREDIT_CEILING,
        "daily_credit_cap": cfg.WELCOME_DAILY_CREDIT_CAP,
        "users": cfg.WELCOME_USER_LIMIT,
        "agents": cfg.WELCOME_AGENT_LIMIT,
        "retention_days": cfg.WELCOME_RETENTION_DAYS,
        "outbound": "production",
        "topups_allowed": True,
    }


WELCOME_MESSAGE = "Full Veklom access for {days} days, safe-use limits apply."
