"""
LockerSphere General Purpose Vertical

Out-of-the-box white-label security platform that works without any
industry-specific configuration. Suitable for SaaS companies, startups,
e-commerce, education, non-profits, and any organization that needs
AI-powered security without niche compliance requirements.
"""

from apps.verticals.base import (
    VerticalConfig,
    VerticalType,
    ComplianceFramework,
    AICapability,
    SecurityPolicy,
)


def build_general_config() -> VerticalConfig:
    return VerticalConfig(
        vertical_type=VerticalType.GENERAL,
        display_name="LockerSphere",
        tagline="AI-Powered Security — Works Out of the Box",
        description=(
            "General-purpose AI security platform ready to deploy without "
            "any industry-specific setup. Provides comprehensive security "
            "monitoring, threat detection, access control, and AI safety "
            "guardrails for any organization. Just deploy and go."
        ),
        icon="shield",
        primary_color="#3B82F6",
        accent_color="#10B981",
        security=SecurityPolicy(
            mfa_required=True,
            min_password_length=12,
            session_timeout_minutes=120,
            max_failed_logins=5,
            ip_allowlist_enabled=False,
            data_encryption_at_rest=True,
            data_encryption_in_transit=True,
            audit_log_retention_days=365,
            zero_trust_enabled=True,
            rbac_enabled=True,
        ),
        compliance_frameworks=[
            ComplianceFramework(
                name="SOC2-TypeII",
                description="Service Organization Control 2 Type II",
                required=False,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="GDPR",
                description="General Data Protection Regulation",
                required=False,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="ISO-27001",
                description="Information Security Management System",
                required=False,
                auto_enforced=False,
            ),
        ],
        ai_capabilities=[
            AICapability(
                name="threat_detection",
                description="AI-powered threat detection and classification",
                enabled=True,
                model_type="classification",
                requires_approval=False,
            ),
            AICapability(
                name="anomaly_detection",
                description="Behavioral anomaly detection for access patterns",
                enabled=True,
                model_type="anomaly",
                requires_approval=False,
            ),
            AICapability(
                name="vulnerability_scanning",
                description="AI-assisted vulnerability assessment and prioritization",
                enabled=True,
                model_type="classification",
                requires_approval=False,
            ),
            AICapability(
                name="content_safety",
                description="Content safety and moderation for user-generated content",
                enabled=True,
                model_type="classification",
                requires_approval=False,
            ),
            AICapability(
                name="incident_response",
                description="AI-assisted incident triage and response recommendations",
                enabled=True,
                model_type="nlp",
                requires_approval=False,
            ),
        ],
        features={
            "threat_detection": True,
            "anomaly_detection": True,
            "access_control": True,
            "audit_logging": True,
            "vulnerability_scanning": True,
            "content_safety": True,
            "incident_response": True,
            "api_security": True,
            "rate_limiting": True,
            "encryption_management": True,
            "security_dashboard": True,
            "alerting": True,
        },
        modules=[
            "threat_detector",
            "anomaly_engine",
            "access_control",
            "audit_logger",
            "vuln_scanner",
            "content_safety",
            "incident_responder",
            "api_guardian",
        ],
        rate_limit_rpm=100,
        default_tier="standard",
        metadata={
            "target_audience": "SaaS, startups, e-commerce, education, non-profits, general",
            "certifications": "SOC 2 Type II (optional)",
            "regions": "global",
            "setup_required": "none — works out of the box",
        },
    )
