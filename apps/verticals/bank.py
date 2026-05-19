"""
LockerSphere Bank Vertical

PCI-DSS compliant AI security platform for banks and financial institutions.
Covers SOX, Basel III/IV, AML/KYC, SWIFT CSP, and regional banking regulations.
Includes transaction monitoring, fraud detection, and financial AI safety.
"""

from apps.verticals.base import (
    VerticalConfig,
    VerticalType,
    ComplianceFramework,
    AICapability,
    SecurityPolicy,
)


def build_bank_config() -> VerticalConfig:
    return VerticalConfig(
        vertical_type=VerticalType.BANK,
        display_name="LockerSphere Bank",
        tagline="PCI-DSS Compliant AI Security for Financial Institutions",
        description=(
            "Enterprise security platform built for banks, credit unions, and "
            "fintech companies. Enforces PCI-DSS, SOX, AML/KYC, and Basel III "
            "regulations with real-time transaction monitoring, AI-powered fraud "
            "detection, and comprehensive audit trails for regulatory reporting."
        ),
        icon="landmark",
        primary_color="#1D4ED8",
        accent_color="#F59E0B",
        security=SecurityPolicy(
            mfa_required=True,
            min_password_length=16,
            session_timeout_minutes=15,
            max_failed_logins=3,
            ip_allowlist_enabled=True,
            data_encryption_at_rest=True,
            data_encryption_in_transit=True,
            audit_log_retention_days=2555,  # 7 years (SOX)
            zero_trust_enabled=True,
            rbac_enabled=True,
        ),
        compliance_frameworks=[
            ComplianceFramework(
                name="PCI-DSS",
                description="Payment Card Industry Data Security Standard v4.0",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="SOX",
                description="Sarbanes-Oxley Act — financial reporting integrity",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="Basel-III",
                description="Basel III capital and liquidity framework",
                required=True,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="AML-KYC",
                description="Anti-Money Laundering / Know Your Customer regulations",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="SWIFT-CSP",
                description="SWIFT Customer Security Programme",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="GDPR",
                description="General Data Protection Regulation — customer data rights",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="GLBA",
                description="Gramm-Leach-Bliley Act — US financial privacy",
                required=False,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="MiFID-II",
                description="Markets in Financial Instruments Directive — EU",
                required=False,
                auto_enforced=False,
            ),
        ],
        ai_capabilities=[
            AICapability(
                name="transaction_fraud_detection",
                description="Real-time ML fraud scoring on transaction streams",
                enabled=True,
                model_type="anomaly",
                requires_approval=False,
            ),
            AICapability(
                name="aml_pattern_detection",
                description="Anti-money laundering pattern recognition and SAR generation",
                enabled=True,
                model_type="graph_analysis",
                requires_approval=True,
            ),
            AICapability(
                name="credit_risk_scoring",
                description="AI-assisted credit risk assessment with explainability",
                enabled=True,
                model_type="predictive",
                requires_approval=True,
            ),
            AICapability(
                name="insider_threat_detection",
                description="Behavioral analytics for detecting insider trading/fraud",
                enabled=True,
                model_type="anomaly",
                requires_approval=False,
            ),
            AICapability(
                name="document_verification",
                description="KYC document authentication and identity verification",
                enabled=True,
                model_type="vision",
                requires_approval=False,
            ),
            AICapability(
                name="market_surveillance",
                description="AI-powered market abuse and manipulation detection",
                enabled=True,
                model_type="time_series",
                requires_approval=True,
            ),
        ],
        features={
            "transaction_monitoring": True,
            "fraud_detection_realtime": True,
            "aml_screening": True,
            "kyc_automation": True,
            "pci_dss_enforcement": True,
            "card_data_tokenization": True,
            "wire_transfer_monitoring": True,
            "insider_threat_analytics": True,
            "regulatory_reporting": True,
            "swift_message_security": True,
            "api_banking_security": True,
            "atm_network_monitoring": True,
        },
        modules=[
            "transaction_sentinel",
            "fraud_engine",
            "aml_compliance",
            "kyc_verification",
            "pci_enforcer",
            "swift_csp_gateway",
            "card_tokenization",
            "regulatory_reporter",
            "insider_threat_detector",
            "market_surveillance",
        ],
        rate_limit_rpm=500,
        default_tier="enterprise",
        metadata={
            "target_audience": "banks, credit unions, fintech, payment processors",
            "certifications": "PCI-DSS v4.0, SOC 2 Type II, ISO 27001, SOX",
            "regions": "global",
            "data_residency": "configurable per jurisdiction",
        },
    )
