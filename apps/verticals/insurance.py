"""
LockerSphere Insurance Vertical

Compliance-ready AI security platform for insurance companies.
Covers Solvency II, NAIC model laws, IFRS 17, and privacy regulations.
Includes claims processing AI safety, actuarial model governance,
underwriting fairness monitoring, and policyholder data protection.
"""

from apps.verticals.base import (
    VerticalConfig,
    VerticalType,
    ComplianceFramework,
    AICapability,
    SecurityPolicy,
)


def build_insurance_config() -> VerticalConfig:
    return VerticalConfig(
        vertical_type=VerticalType.INSURANCE,
        display_name="LockerSphere Insurance",
        tagline="AI Security & Compliance for Insurance Carriers",
        description=(
            "Enterprise security platform for insurance carriers, brokers, and "
            "MGAs. Enforces Solvency II, NAIC model laws, IFRS 17, and data "
            "privacy regulations. Provides AI-powered claims fraud detection, "
            "actuarial model governance, underwriting fairness monitoring, and "
            "policyholder data protection."
        ),
        icon="shield-check",
        primary_color="#7C3AED",
        accent_color="#14B8A6",
        security=SecurityPolicy(
            mfa_required=True,
            min_password_length=14,
            session_timeout_minutes=60,
            max_failed_logins=5,
            ip_allowlist_enabled=True,
            data_encryption_at_rest=True,
            data_encryption_in_transit=True,
            audit_log_retention_days=2555,  # 7 years
            zero_trust_enabled=True,
            rbac_enabled=True,
        ),
        compliance_frameworks=[
            ComplianceFramework(
                name="Solvency-II",
                description="EU Solvency II Directive — risk-based capital and governance",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="NAIC-Model-Laws",
                description="National Association of Insurance Commissioners model laws",
                required=True,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="IFRS-17",
                description="International Financial Reporting Standard 17 — insurance contracts",
                required=True,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="GDPR",
                description="General Data Protection Regulation — policyholder data rights",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="CCPA",
                description="California Consumer Privacy Act — US consumer data rights",
                required=False,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="AI-Act",
                description="EU AI Act — high-risk AI system governance for insurance",
                required=True,
                auto_enforced=True,
            ),
        ],
        ai_capabilities=[
            AICapability(
                name="claims_fraud_detection",
                description="AI-powered claims fraud pattern detection and scoring",
                enabled=True,
                model_type="anomaly",
                requires_approval=False,
            ),
            AICapability(
                name="actuarial_model_governance",
                description="Governance and audit trails for actuarial AI models",
                enabled=True,
                model_type="governance",
                requires_approval=True,
            ),
            AICapability(
                name="underwriting_fairness",
                description="Bias detection and fairness monitoring in underwriting AI",
                enabled=True,
                model_type="fairness",
                requires_approval=True,
            ),
            AICapability(
                name="document_extraction",
                description="AI extraction of policy documents, medical records, claims forms",
                enabled=True,
                model_type="nlp_extraction",
                requires_approval=False,
            ),
            AICapability(
                name="risk_scoring",
                description="AI-assisted risk assessment for policy pricing",
                enabled=True,
                model_type="predictive",
                requires_approval=True,
            ),
            AICapability(
                name="catastrophe_modeling",
                description="Natural disaster and catastrophe exposure analysis",
                enabled=True,
                model_type="simulation",
                requires_approval=True,
            ),
        ],
        features={
            "claims_processing_ai": True,
            "fraud_detection": True,
            "actuarial_governance": True,
            "underwriting_fairness_monitor": True,
            "policyholder_data_protection": True,
            "regulatory_reporting": True,
            "catastrophe_modeling": True,
            "reinsurance_tracking": True,
            "complaint_analysis": True,
            "agent_broker_access_control": True,
            "policy_document_vault": True,
            "ai_explainability_reports": True,
        },
        modules=[
            "claims_sentinel",
            "fraud_engine",
            "actuarial_governance",
            "underwriting_fairness",
            "policyholder_vault",
            "regulatory_reporter",
            "catastrophe_modeler",
            "document_extraction",
            "complaint_analyzer",
            "reinsurance_tracker",
        ],
        rate_limit_rpm=200,
        default_tier="enterprise",
        metadata={
            "target_audience": "insurance carriers, brokers, MGAs, reinsurers",
            "certifications": "SOC 2 Type II, ISO 27001, Solvency II",
            "regions": "global",
            "data_residency": "configurable per jurisdiction",
        },
    )
