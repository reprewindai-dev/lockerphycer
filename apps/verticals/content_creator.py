"""
LockerSphere Content Creator Vertical

AI security platform for content creators, influencers, studios, and media companies.
Covers DMCA, copyright protection, content moderation, monetization security,
and creator safety tools.
"""

from apps.verticals.base import (
    VerticalConfig,
    VerticalType,
    ComplianceFramework,
    AICapability,
    SecurityPolicy,
)


def build_content_creator_config() -> VerticalConfig:
    return VerticalConfig(
        vertical_type=VerticalType.CONTENT_CREATOR,
        display_name="LockerSphere Content Creator",
        tagline="AI Security for Creators, Studios & Media",
        description=(
            "Security platform purpose-built for content creators, influencers, "
            "studios, and media companies. Protects intellectual property with "
            "AI-powered content fingerprinting, DMCA management, brand safety "
            "monitoring, and monetization protection. Includes creator safety "
            "tools for harassment detection and audience analytics security."
        ),
        icon="palette",
        primary_color="#EC4899",
        accent_color="#F97316",
        security=SecurityPolicy(
            mfa_required=True,
            min_password_length=10,
            session_timeout_minutes=120,
            max_failed_logins=5,
            ip_allowlist_enabled=False,
            data_encryption_at_rest=True,
            data_encryption_in_transit=True,
            audit_log_retention_days=730,  # 2 years
            zero_trust_enabled=True,
            rbac_enabled=True,
        ),
        compliance_frameworks=[
            ComplianceFramework(
                name="DMCA",
                description="Digital Millennium Copyright Act — copyright protection",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="COPPA",
                description="Children's Online Privacy Protection Act — if audience includes minors",
                required=False,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="GDPR",
                description="General Data Protection Regulation — audience data rights",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="DSA",
                description="EU Digital Services Act — content moderation obligations",
                required=False,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="FTC-Guidelines",
                description="FTC endorsement and disclosure guidelines",
                required=True,
                auto_enforced=False,
            ),
        ],
        ai_capabilities=[
            AICapability(
                name="content_fingerprinting",
                description="AI-powered content fingerprinting for IP protection",
                enabled=True,
                model_type="vision",
                requires_approval=False,
            ),
            AICapability(
                name="plagiarism_detection",
                description="Detect unauthorized use of creative content across platforms",
                enabled=True,
                model_type="nlp_similarity",
                requires_approval=False,
            ),
            AICapability(
                name="content_moderation",
                description="AI moderation for comments, DMs, and community content",
                enabled=True,
                model_type="classification",
                requires_approval=False,
            ),
            AICapability(
                name="harassment_detection",
                description="Real-time harassment and threat detection in interactions",
                enabled=True,
                model_type="nlp_classification",
                requires_approval=False,
            ),
            AICapability(
                name="brand_safety_scoring",
                description="AI scoring of content brand safety for sponsors",
                enabled=True,
                model_type="classification",
                requires_approval=False,
            ),
            AICapability(
                name="deepfake_detection",
                description="Detect AI-generated deepfakes using creator likeness",
                enabled=True,
                model_type="vision",
                requires_approval=False,
            ),
            AICapability(
                name="revenue_anomaly_detection",
                description="Detect anomalous monetization patterns (click fraud, etc.)",
                enabled=True,
                model_type="anomaly",
                requires_approval=False,
            ),
        ],
        features={
            "content_fingerprinting": True,
            "dmca_management": True,
            "plagiarism_detection": True,
            "content_moderation": True,
            "harassment_shield": True,
            "brand_safety_monitor": True,
            "deepfake_detection": True,
            "revenue_protection": True,
            "sponsor_disclosure_tracker": True,
            "audience_data_privacy": True,
            "multi_platform_security": True,
            "collaboration_access_control": True,
        },
        modules=[
            "ip_protection",
            "dmca_manager",
            "content_moderator",
            "harassment_shield",
            "brand_safety",
            "deepfake_detector",
            "revenue_sentinel",
            "disclosure_tracker",
            "audience_privacy",
            "platform_connector",
        ],
        rate_limit_rpm=300,
        default_tier="standard",
        metadata={
            "target_audience": "content creators, influencers, studios, media companies, agencies",
            "certifications": "SOC 2 Type II",
            "regions": "global",
            "platforms_supported": "YouTube, TikTok, Instagram, Twitch, X, Patreon, Substack",
        },
    )
