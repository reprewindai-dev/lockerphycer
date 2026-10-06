"""Entitlement settings.

Kept in its own settings object (same env/.env source as core.config.settings)
so the commercial knobs are grouped and do not collide with unrelated settings.

Values marked PLACEHOLDER are owner-unconfirmed defaults. They are configurable
through the environment and must be confirmed before they are treated as final.
"""

from functools import lru_cache

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - pydantic v1 fallback
    from pydantic import BaseSettings
    SettingsConfigDict = dict


class EntitlementSettings(BaseSettings):
    # --- Welcome (locked: 14 days from workspace creation, automatic, no card) ---
    WELCOME_DAYS: int = 14
    # PLACEHOLDER: "very high ceiling", never "unlimited".
    WELCOME_CREDIT_CEILING: int = 100_000
    # PLACEHOLDER abuse limit: max credits consumable per rolling 24h during Welcome.
    WELCOME_DAILY_CREDIT_CAP: int = 20_000
    # PLACEHOLDER: Welcome user/agent/retention limits ("full access, safe-use limits").
    WELCOME_USER_LIMIT: int = 25
    WELCOME_AGENT_LIMIT: int = 25
    WELCOME_RETENTION_DAYS: int = 90

    # --- Plans ---
    # Locked: allowance resets monthly. Period length reuses the reference
    # orchestrator's 30-day cycle until billing-cycle anchoring (Stripe) exists.
    ENTITLEMENT_PERIOD_DAYS: int = 30
    # PLACEHOLDER: Team retention ("longer retention"; 180 per instruction).
    TEAM_RETENTION_DAYS: int = 180

    # --- Paywall routing (no hard-coded URLs; /pricing does not exist yet) ---
    ENTITLEMENTS_UPGRADE_PATH: str | None = None
    ENTITLEMENTS_TOPUP_PATH: str | None = None

    # --- Stripe (TEST mode only; keys come from core.config.settings STRIPE_*) ---
    # PLACEHOLDER / OPEN DECISION: internal conversion used only to stamp
    # credits=<n> into top-up price metadata. Never shown publicly as a peg.
    # 50/USD matches Pro/Team (~2¢ per credit); the live Stripe test prices carry
    # the same credits=<n> metadata, which the webhook reads first.
    TOPUP_CREDITS_PER_USD: int = 50
    STRIPE_API_BASE: str = "https://api.stripe.com"
    # Live keys are refused unless this is explicitly enabled (it is not, for now).
    STRIPE_ALLOW_LIVE: bool = False
    STRIPE_WEBHOOK_TOLERANCE_SECONDS: int = 300

    # --- Service-to-service (CAPPO -> LockerPhycer metering) ---
    # Empty disables the internal endpoints (they answer 503, fail closed).
    ENTITLEMENTS_INTERNAL_TOKEN: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


PLACEHOLDER_SETTINGS = (
    "WELCOME_CREDIT_CEILING",
    "WELCOME_DAILY_CREDIT_CAP",
    "WELCOME_USER_LIMIT",
    "WELCOME_AGENT_LIMIT",
    "WELCOME_RETENTION_DAYS",
    "TEAM_RETENTION_DAYS",
    "TOPUP_CREDITS_PER_USD",
)


@lru_cache
def get_entitlement_settings() -> EntitlementSettings:
    return EntitlementSettings()
