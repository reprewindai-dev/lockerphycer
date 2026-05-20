"""
Pramana Epistemic Verification Framework
Classifies agent claims by epistemic source and applies the most
efficient verification method — never a full second LLM pass.

Based on Nyaya Shastra epistemology integrated into NabaOS.

Categories:
  Pratyaksha  — direct tool output       → check HMAC receipt      < 1ms
  Anumana     — inference from tool data → check premises exist    < 5ms
  Sabda       — external testimony       → re-fetch URL            network
  Abhava      — claim of absence         → verify empty set        < 1ms
  Ungrounded  — opinion / no evidence   → flag to user, skip       0ms
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
import re


class PramanaType(str, Enum):
    PRATYAKSHA = "pratyaksha"   # Direct perception / tool output
    ANUMANA = "anumana"         # Inference
    SABDA = "sabda"             # Testimony / external source
    ABHAVA = "abhava"           # Absence claim
    UNGROUNDED = "ungrounded"   # No evidence base


@dataclass
class VerificationResult:
    pramana: PramanaType
    verified: bool
    overhead_ms: float
    reason: str
    flagged_to_user: bool = False


class PramanaVerifier:
    """
    Classify and verify claims from agent outputs.
    """

    URL_PATTERN = re.compile(r"https?://[^\s]+")
    ABSENCE_PHRASES = [
        "no results", "nothing found", "empty", "zero records",
        "does not exist", "not found", "none available",
    ]

    def __init__(self, receipt_runtime):
        """
        receipt_runtime: ToolReceiptRuntime instance for Pratyaksha checks.
        """
        self._runtime = receipt_runtime

    def classify(self, claim: str, supporting_data: Optional[Any] = None) -> PramanaType:
        """Classify what type of claim this is."""
        if supporting_data is not None and isinstance(supporting_data, dict):
            if supporting_data.get("_tool_receipt"):
                return PramanaType.PRATYAKSHA
            if supporting_data.get("_inferred_from"):
                return PramanaType.ANUMANA

        if self.URL_PATTERN.search(claim):
            return PramanaType.SABDA

        if any(phrase in claim.lower() for phrase in self.ABSENCE_PHRASES):
            return PramanaType.ABHAVA

        return PramanaType.UNGROUNDED

    def verify(
        self,
        claim: str,
        pramana: PramanaType,
        tool_name: Optional[str] = None,
        claimed_output: Optional[Any] = None,
        premises: Optional[list] = None,
    ) -> VerificationResult:
        """Apply the cheapest verification method for the given pramana type."""
        import time
        start = time.perf_counter()

        if pramana == PramanaType.PRATYAKSHA:
            result = self._verify_pratyaksha(tool_name, claimed_output)
        elif pramana == PramanaType.ANUMANA:
            result = self._verify_anumana(premises)
        elif pramana == PramanaType.ABHAVA:
            result = self._verify_abhava(claimed_output)
        elif pramana == PramanaType.SABDA:
            result = self._verify_sabda(claim)
        else:  # UNGROUNDED
            elapsed = (time.perf_counter() - start) * 1000
            return VerificationResult(
                pramana=pramana,
                verified=False,
                overhead_ms=elapsed,
                reason="ungrounded_opinion",
                flagged_to_user=True,
            )

        elapsed = (time.perf_counter() - start) * 1000
        result.overhead_ms = elapsed
        return result

    def _verify_pratyaksha(self, tool_name, claimed_output) -> VerificationResult:
        if not tool_name or claimed_output is None:
            return VerificationResult(PramanaType.PRATYAKSHA, False, 0, "missing_tool_or_output")
        check = self._runtime.verify_claim(tool_name, claimed_output)
        return VerificationResult(
            pramana=PramanaType.PRATYAKSHA,
            verified=check["verified"],
            overhead_ms=0,
            reason=check["reason"],
        )

    def _verify_anumana(self, premises) -> VerificationResult:
        if not premises:
            return VerificationResult(PramanaType.ANUMANA, False, 0, "no_premises_provided")
        all_exist = all(p is not None for p in premises)
        return VerificationResult(
            pramana=PramanaType.ANUMANA,
            verified=all_exist,
            overhead_ms=0,
            reason="premises_exist" if all_exist else "missing_premise",
        )

    def _verify_abhava(self, claimed_output) -> VerificationResult:
        is_empty = (
            claimed_output is None
            or claimed_output == []
            or claimed_output == {}
            or claimed_output == ""
        )
        return VerificationResult(
            pramana=PramanaType.ABHAVA,
            verified=is_empty,
            overhead_ms=0,
            reason="confirmed_empty" if is_empty else "non_empty_contradicts_absence_claim",
        )

    def _verify_sabda(self, claim: str) -> VerificationResult:
        # Sabda requires network re-fetch — return pending for async resolution
        urls = self.URL_PATTERN.findall(claim)
        return VerificationResult(
            pramana=PramanaType.SABDA,
            verified=False,
            overhead_ms=0,
            reason=f"requires_refetch:{','.join(urls[:3])}",
        )
