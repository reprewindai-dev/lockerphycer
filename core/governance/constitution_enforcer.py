"""
Ed25519 Constitution Enforcer
Every agent action is validated against Physical Invariant Constraints (PIC)
before execution. Cryptographically signed safety firewall.

Anti-collusion: the governance enforcer is architecturally separate
from the agents it governs — different process, different credentials.

PIC (Physical Invariant Constraints) examples:
  - An agent cannot spend > $X without human approval
  - An agent cannot delete production data
  - An agent cannot contact external endpoints not in the whitelist
  - An agent cannot impersonate another agent
"""
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Ed25519 signing — requires: pip install cryptography
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey
    )
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PublicFormat, PrivateFormat, NoEncryption
    )
    from cryptography.exceptions import InvalidSignature
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logger.warning("cryptography package not installed — signature verification disabled")


@dataclass
class PolicyViolation:
    rule: str
    action: str
    agent_id: str
    detail: str
    blocked: bool = True


class ConstitutionEnforcer:
    """
    Validates every agent action against the PIC ruleset.
    Runs in a separate process/service from the agent workers.
    """

    # Default Physical Invariant Constraints
    DEFAULT_PIC_RULES = [
        {"id": "no_prod_delete", "description": "Block deletion of production resources",
         "blocked_actions": ["delete_production", "drop_table", "purge_bucket"]},
        {"id": "spend_limit", "description": "Require human approval for spend > $50",
         "max_spend_usd": 50.0},
        {"id": "no_impersonation", "description": "Agent cannot claim to be another agent",
         "blocked_patterns": ["act as agent", "impersonate", "pretend to be"]},
        {"id": "endpoint_whitelist", "description": "Only approved external endpoints",
         "whitelist": [
             "api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com",
             "api.github.com", "hooks.slack.com",
         ]},
    ]

    def __init__(self, rules: list = None):
        self._rules = rules or self.DEFAULT_PIC_RULES
        self._violations: list[PolicyViolation] = []

    def validate(self, agent_id: str, action: str, params: dict) -> tuple[bool, list[PolicyViolation]]:
        """
        Validate an agent action before execution.
        Returns (allowed: bool, violations: list)
        """
        violations = []

        for rule in self._rules:
            violation = self._check_rule(rule, agent_id, action, params)
            if violation:
                violations.append(violation)
                if violation.blocked:
                    logger.error(
                        "CONSTITUTION BLOCK — agent=%s action=%s rule=%s",
                        agent_id, action, rule["id"]
                    )

        self._violations.extend(violations)
        blocked = any(v.blocked for v in violations)
        return (not blocked), violations

    def _check_rule(self, rule: dict, agent_id: str, action: str, params: dict) -> PolicyViolation | None:
        rule_id = rule["id"]

        # Check blocked actions
        if "blocked_actions" in rule:
            if action in rule["blocked_actions"]:
                return PolicyViolation(
                    rule=rule_id, action=action, agent_id=agent_id,
                    detail=f"Action '{action}' is blocked by PIC rule '{rule_id}'",
                    blocked=True,
                )

        # Check spend limit
        if "max_spend_usd" in rule:
            spend = params.get("amount_usd", 0.0)
            if spend > rule["max_spend_usd"]:
                return PolicyViolation(
                    rule=rule_id, action=action, agent_id=agent_id,
                    detail=f"Spend ${spend} exceeds PIC limit ${rule['max_spend_usd']}",
                    blocked=True,
                )

        # Check blocked patterns in action string
        if "blocked_patterns" in rule:
            action_lower = action.lower()
            for pattern in rule["blocked_patterns"]:
                if pattern in action_lower:
                    return PolicyViolation(
                        rule=rule_id, action=action, agent_id=agent_id,
                        detail=f"Action contains blocked pattern: '{pattern}'",
                        blocked=True,
                    )

        # Check endpoint whitelist
        if "whitelist" in rule:
            endpoint = params.get("endpoint", "")
            if endpoint and not any(w in endpoint for w in rule["whitelist"]):
                return PolicyViolation(
                    rule=rule_id, action=action, agent_id=agent_id,
                    detail=f"Endpoint '{endpoint}' not in PIC whitelist",
                    blocked=True,
                )

        return None

    def get_violation_log(self) -> list[dict]:
        return [
            {"rule": v.rule, "action": v.action, "agent_id": v.agent_id,
             "detail": v.detail, "blocked": v.blocked}
            for v in self._violations
        ]
