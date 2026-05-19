"""
Base Vertical Configuration

All LockerSphere verticals inherit from this base. Each vertical overrides
specific settings to specialize the platform for its industry niche while
reusing the same core security, AI, and monitoring infrastructure.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VerticalType(str, Enum):
    SECURITY = "security"
    HOSPITAL = "hospital"
    BANK = "bank"
    INSURANCE = "insurance"
    CONTENT_CREATOR = "content_creator"
    GENERAL = "general"


@dataclass
class ComplianceFramework:
    """A compliance standard or regulation the vertical must meet."""
    name: str
    description: str
    required: bool = True
    auto_enforced: bool = False


@dataclass
class AICapability:
    """An AI capability available in the vertical."""
    name: str
    description: str
    enabled: bool = True
    model_type: str = "general"
    requires_approval: bool = False


@dataclass
class SecurityPolicy:
    """Security policy configuration for the vertical."""
    mfa_required: bool = True
    min_password_length: int = 12
    session_timeout_minutes: int = 120
    max_failed_logins: int = 5
    ip_allowlist_enabled: bool = False
    data_encryption_at_rest: bool = True
    data_encryption_in_transit: bool = True
    audit_log_retention_days: int = 365
    zero_trust_enabled: bool = True
    rbac_enabled: bool = True


@dataclass
class VerticalConfig:
    """Base configuration for a LockerSphere vertical."""

    vertical_type: VerticalType
    display_name: str
    tagline: str
    description: str
    icon: str = "shield"

    # Branding
    primary_color: str = "#3B82F6"
    accent_color: str = "#10B981"
    logo_path: Optional[str] = None

    # Security
    security: SecurityPolicy = field(default_factory=SecurityPolicy)

    # Compliance
    compliance_frameworks: list[ComplianceFramework] = field(default_factory=list)

    # AI Capabilities
    ai_capabilities: list[AICapability] = field(default_factory=list)

    # Feature flags
    features: dict[str, bool] = field(default_factory=dict)

    # Industry-specific modules
    modules: list[str] = field(default_factory=list)

    # API rate limits (requests per minute)
    rate_limit_rpm: int = 100

    # Default pricing tier
    default_tier: str = "standard"

    # Metadata
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to dictionary for API responses."""
        return {
            "vertical_type": self.vertical_type.value,
            "display_name": self.display_name,
            "tagline": self.tagline,
            "description": self.description,
            "icon": self.icon,
            "primary_color": self.primary_color,
            "accent_color": self.accent_color,
            "logo_path": self.logo_path,
            "security": {
                "mfa_required": self.security.mfa_required,
                "min_password_length": self.security.min_password_length,
                "session_timeout_minutes": self.security.session_timeout_minutes,
                "max_failed_logins": self.security.max_failed_logins,
                "ip_allowlist_enabled": self.security.ip_allowlist_enabled,
                "data_encryption_at_rest": self.security.data_encryption_at_rest,
                "data_encryption_in_transit": self.security.data_encryption_in_transit,
                "audit_log_retention_days": self.security.audit_log_retention_days,
                "zero_trust_enabled": self.security.zero_trust_enabled,
                "rbac_enabled": self.security.rbac_enabled,
            },
            "compliance_frameworks": [
                {"name": f.name, "description": f.description, "required": f.required, "auto_enforced": f.auto_enforced}
                for f in self.compliance_frameworks
            ],
            "ai_capabilities": [
                {"name": c.name, "description": c.description, "enabled": c.enabled, "model_type": c.model_type, "requires_approval": c.requires_approval}
                for c in self.ai_capabilities
            ],
            "features": self.features,
            "modules": self.modules,
            "rate_limit_rpm": self.rate_limit_rpm,
            "default_tier": self.default_tier,
            "metadata": self.metadata,
        }
