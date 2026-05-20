"""
Tool Execution Receipt System
Implements cryptographically-signed HMAC receipts for every tool call.
Detects 94.2% of fabricated tool references at < 15ms overhead.

Based on: arXiv 2603.10060 — Tool Receipts, Not Zero-Knowledge Proofs
"""
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Optional
import os

# Load from env in production
RECEIPT_SECRET = os.getenv("RECEIPT_HMAC_SECRET", "change-me-in-production")


@dataclass
class ToolReceipt:
    receipt_id: str
    tool_name: str
    input_hash: str
    output_hash: str
    timestamp_ms: int
    signature: str
    agent_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def verify(self) -> bool:
        """Re-compute HMAC and compare to stored signature."""
        payload = self._build_payload(
            self.tool_name, self.input_hash, self.output_hash, self.timestamp_ms
        )
        expected = hmac.new(
            RECEIPT_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, self.signature)

    @staticmethod
    def _build_payload(
        tool_name: str, input_hash: str, output_hash: str, timestamp_ms: int
    ) -> str:
        return f"{tool_name}:{input_hash}:{output_hash}:{timestamp_ms}"


class ToolReceiptRuntime:
    """
    Wraps every tool call and produces a signed receipt.
    The LLM never calls tools directly — this runtime does,
    then cross-references LLM claims against receipts.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._receipts: dict[str, ToolReceipt] = {}

    def execute_tool(self, tool_name: str, tool_fn, **kwargs) -> tuple[Any, ToolReceipt]:
        """Execute a tool and return (result, receipt)."""
        input_hash = self._hash(json.dumps(kwargs, sort_keys=True, default=str))
        result = tool_fn(**kwargs)
        output_hash = self._hash(json.dumps(result, sort_keys=True, default=str))
        timestamp_ms = int(time.time() * 1000)

        payload = ToolReceipt._build_payload(tool_name, input_hash, output_hash, timestamp_ms)
        signature = hmac.new(
            RECEIPT_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()

        receipt = ToolReceipt(
            receipt_id=str(uuid.uuid4()),
            tool_name=tool_name,
            input_hash=input_hash,
            output_hash=output_hash,
            timestamp_ms=timestamp_ms,
            signature=signature,
            agent_id=self.agent_id,
        )
        self._receipts[receipt.receipt_id] = receipt
        return result, receipt

    def verify_claim(self, tool_name: str, claimed_output: Any) -> dict:
        """
        Cross-reference an LLM claim against stored receipts.
        Returns {verified: bool, receipt_id: str|None, reason: str}
        """
        claimed_hash = self._hash(json.dumps(claimed_output, sort_keys=True, default=str))

        for rid, receipt in self._receipts.items():
            if receipt.tool_name == tool_name and receipt.output_hash == claimed_hash:
                if receipt.verify():
                    return {"verified": True, "receipt_id": rid, "reason": "receipt_match"}
                else:
                    return {"verified": False, "receipt_id": rid, "reason": "tampered_receipt"}

        return {
            "verified": False,
            "receipt_id": None,
            "reason": "no_matching_receipt — possible hallucination",
        }

    def get_all_receipts(self) -> list[dict]:
        return [r.to_dict() for r in self._receipts.values()]

    @staticmethod
    def _hash(data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()
