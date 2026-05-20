"""
SupervisorAgent LLM-Free Adaptive Filter
Triggers LLM intervention ONLY in three scenarios:
  1. Tool error or malformed output
  2. Repeated action-observation loop (same cycle >= 3x)
  3. Context length explosion (> max_obs_tokens)

Reduces token consumption by 29.68% on GAIA benchmark.
Based on: arXiv 2510.26585 — Stop Wasting Your Tokens
"""
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
import hashlib
import logging

logger = logging.getLogger(__name__)


class TriggerReason(str, Enum):
    NONE = "none"
    TOOL_ERROR = "tool_error"
    LOOP_DETECTED = "loop_detected"
    CONTEXT_OVERFLOW = "context_overflow"


@dataclass
class SupervisorDecision:
    should_intervene: bool
    trigger: TriggerReason
    action: str  # "purify" | "guide" | "none"
    message: Optional[str] = None


class SupervisorFilter:
    """
    Stateful, LLM-free filter that monitors a single agent's execution trace.
    One instance per agent per task.
    """

    def __init__(
        self,
        max_obs_tokens: int = 4096,
        loop_threshold: int = 3,
    ):
        self._max_obs_tokens = max_obs_tokens
        self._loop_threshold = loop_threshold
        self._action_hashes: list[str] = []
        self._total_tokens = 0
        self._interventions = 0

    def observe(
        self,
        action: str,
        observation: Any,
        tool_error: bool = False,
        obs_token_count: int = 0,
    ) -> SupervisorDecision:
        """Evaluate after each agent action-observation cycle."""

        # Check 1: Tool error
        if tool_error:
            self._interventions += 1
            logger.warning("Supervisor: tool error detected on action=%s", action)
            return SupervisorDecision(
                should_intervene=True,
                trigger=TriggerReason.TOOL_ERROR,
                action="guide",
                message=f"Tool error on '{action}'. Provide corrected parameters or try alternative.",
            )

        # Check 2: Repeated loop
        action_hash = hashlib.md5(str(action).encode()).hexdigest()
        self._action_hashes.append(action_hash)
        counts = Counter(self._action_hashes)
        if counts[action_hash] >= self._loop_threshold:
            self._interventions += 1
            logger.warning("Supervisor: loop detected, action repeated %d times", counts[action_hash])
            return SupervisorDecision(
                should_intervene=True,
                trigger=TriggerReason.LOOP_DETECTED,
                action="purify",
                message=f"Action '{action}' repeated {counts[action_hash]}x. Summarizing history and breaking loop.",
            )

        # Check 3: Context overflow
        self._total_tokens += obs_token_count
        if self._total_tokens > self._max_obs_tokens:
            self._interventions += 1
            logger.warning("Supervisor: context overflow at %d tokens", self._total_tokens)
            return SupervisorDecision(
                should_intervene=True,
                trigger=TriggerReason.CONTEXT_OVERFLOW,
                action="purify",
                message="Context window too large. Compressing observation history.",
            )

        return SupervisorDecision(
            should_intervene=False,
            trigger=TriggerReason.NONE,
            action="none",
        )

    def reset(self):
        self._action_hashes = []
        self._total_tokens = 0

    @property
    def intervention_count(self) -> int:
        return self._interventions
