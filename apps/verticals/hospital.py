"""
LockerSphere Hospital Vertical

HIPAA-grade AI security platform for hospitals and healthcare organizations.
Global compliance: HIPAA (US), GDPR (EU), PIPEDA (CA), LGPD (BR), POPI (ZA).
Includes HL7/FHIR integration, patient data protection, clinical AI safety,
and real-time threat detection for medical systems.
"""

from apps.verticals.base import (
    VerticalConfig,
    VerticalType,
    ComplianceFramework,
    AICapability,
    SecurityPolicy,
)


def build_hospital_config() -> VerticalConfig:
    return VerticalConfig(
        vertical_type=VerticalType.HOSPITAL,
        display_name="LockerSphere Hospital",
        tagline="HIPAA-Grade AI Security for Global Healthcare",
        description=(
            "Enterprise-grade security platform purpose-built for hospitals, "
            "clinics, and healthcare networks. Enforces HIPAA, GDPR, and "
            "regional health data regulations with HL7/FHIR-aware threat "
            "detection, clinical AI safety guardrails, and real-time PHI "
            "leakage prevention."
        ),
        icon="hospital",
        primary_color="#0EA5E9",
        accent_color="#06B6D4",
        security=SecurityPolicy(
            mfa_required=True,
            min_password_length=14,
            session_timeout_minutes=30,
            max_failed_logins=3,
            ip_allowlist_enabled=True,
            data_encryption_at_rest=True,
            data_encryption_in_transit=True,
            audit_log_retention_days=2555,  # 7 years (HIPAA requirement)
            zero_trust_enabled=True,
            rbac_enabled=True,
        ),
        compliance_frameworks=[
            ComplianceFramework(
                name="HIPAA",
                description="Health Insurance Portability and Accountability Act — US federal PHI protection",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="HITECH",
                description="Health Information Technology for Economic and Clinical Health Act",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="GDPR",
                description="General Data Protection Regulation — EU patient data rights",
                required=True,
                auto_enforced=True,
            ),
            ComplianceFramework(
                name="PIPEDA",
                description="Personal Information Protection and Electronic Documents Act — Canada",
                required=False,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="LGPD",
                description="Lei Geral de Protecao de Dados — Brazil data protection",
                required=False,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="POPI",
                description="Protection of Personal Information Act — South Africa",
                required=False,
                auto_enforced=False,
            ),
            ComplianceFramework(
                name="HL7-FHIR",
                description="Health Level Seven / Fast Healthcare Interoperability Resources",
                required=True,
                auto_enforced=True,
            ),
        ],
        ai_capabilities=[
            AICapability(
                name="phi_detection",
                description="Detect and redact Protected Health Information in AI inputs/outputs",
                enabled=True,
                model_type="nlp_ner",
                requires_approval=False,
            ),
            AICapability(
                name="clinical_decision_support",
                description="AI-assisted clinical decision support with safety guardrails",
                enabled=True,
                model_type="clinical_ai",
                requires_approval=True,
            ),
            AICapability(
                name="medical_image_analysis",
                description="Radiology and pathology image analysis with audit trails",
                enabled=True,
                model_type="vision",
                requires_approval=True,
            ),
            AICapability(
                name="anomaly_detection_ehr",
                description="Detect anomalous access patterns in Electronic Health Records",
                enabled=True,
                model_type="anomaly",
                requires_approval=False,
            ),
            AICapability(
                name="drug_interaction_check",
                description="AI-powered drug interaction and contraindication alerts",
                enabled=True,
                model_type="clinical_ai",
                requires_approval=False,
            ),
            AICapability(
                name="patient_risk_scoring",
                description="Risk stratification for readmission, sepsis, falls",
                enabled=True,
                model_type="predictive",
                requires_approval=True,
            ),
        ],
        features={
            "phi_leak_prevention": True,
            "hl7_fhir_gateway": True,
            "clinical_ai_guardrails": True,
            "ehr_access_monitoring": True,
            "hipaa_audit_trail": True,
            "consent_management": True,
            "break_the_glass_access": True,
            "minimum_necessary_enforcement": True,
            "de_identification_pipeline": True,
            "medical_device_security": True,
            "telehealth_encryption": True,
            "pandemic_response_mode": True,
        },
        modules=[
            "phi_protection",
            "hl7_fhir_adapter",
            "clinical_ai_safety",
            "ehr_sentinel",
            "medical_device_ids",
            "consent_engine",
            "hipaa_reporter",
            "telehealth_security",
            "patient_identity_verification",
        ],
        rate_limit_rpm=200,
        default_tier="enterprise",
        metadata={
            "target_audience": "hospitals, clinics, health networks, telehealth providers",
            "certifications": "HIPAA, SOC 2 Type II, ISO 27001, ISO 27799",
            "regions": "global",
            "data_residency": "configurable per jurisdiction",
        },
    )
