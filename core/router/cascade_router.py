"""
NabaOS 5-Tier Cascade Router
Routes every request to the cheapest tier that can handle it.
Tier 1: Fingerprint (exact hash match)
Tier 2: BERT-Large intent classification
Tier 3: SetFit few-shot (long-tail)
Tier 4: Cheap LLM
Tier 5: Full deep agent
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Tier(IntEnum):
    FINGERPRINT = 1
    BERT = 2
    SETFIT = 3
    CHEAP_LLM = 4
    DEEP_AGENT = 5


@dataclass
class RouteDecision:
    tier: Tier
    cache_hit: bool
    intent: Optional[str]
    confidence: float
    estimated_cost_usd: float


class CascadeRouter:
    """
    Routes requests through the 5-tier hierarchy.
    < 2% of traffic should ever reach Tier 5.
    """

    # Tier cost estimates in USD per request
    TIER_COSTS = {
        Tier.FINGERPRINT: 0.0,
        Tier.BERT: 0.0001,
        Tier.SETFIT: 0.0001,
        Tier.CHEAP_LLM: 0.001,
        Tier.DEEP_AGENT: 0.075,
    }

    def __init__(self, fingerprint_cache: dict, intent_threshold: float = 0.85):
        self._cache: dict[str, Any] = fingerprint_cache
        self._intent_threshold = intent_threshold
        self._tier_counters = {t: 0 for t in Tier}

    def route(self, w5h2_key: str, raw_input: str) -> RouteDecision:
        """Determine which tier handles this request."""

        # --- Tier 1: Exact fingerprint match ---
        fingerprint = self._fingerprint(w5h2_key)
        if fingerprint in self._cache:
            self._tier_counters[Tier.FINGERPRINT] += 1
            logger.debug("Tier1 cache hit: %s", fingerprint)
            return RouteDecision(
                tier=Tier.FINGERPRINT,
                cache_hit=True,
                intent=self._cache[fingerprint].get("intent"),
                confidence=1.0,
                estimated_cost_usd=0.0,
            )

        # --- Tier 2: BERT intent classification ---
        bert_result = self._bert_classify(raw_input)
        if bert_result and bert_result["confidence"] >= self._intent_threshold:
            self._tier_counters[Tier.BERT] += 1
            return RouteDecision(
                tier=Tier.BERT,
                cache_hit=False,
                intent=bert_result["intent"],
                confidence=bert_result["confidence"],
                estimated_cost_usd=self.TIER_COSTS[Tier.BERT],
            )

        # --- Tier 3: SetFit few-shot for long-tail intents ---
        setfit_result = self._setfit_classify(raw_input)
        if setfit_result and setfit_result["confidence"] >= 0.75:
            self._tier_counters[Tier.SETFIT] += 1
            return RouteDecision(
                tier=Tier.SETFIT,
                cache_hit=False,
                intent=setfit_result["intent"],
                confidence=setfit_result["confidence"],
                estimated_cost_usd=self.TIER_COSTS[Tier.SETFIT],
            )

        # --- Tier 4: Cheap LLM for simple reasoning ---
        complexity = self._estimate_complexity(raw_input)
        if complexity < 0.6:
            self._tier_counters[Tier.CHEAP_LLM] += 1
            return RouteDecision(
                tier=Tier.CHEAP_LLM,
                cache_hit=False,
                intent=None,
                confidence=0.0,
                estimated_cost_usd=self.TIER_COSTS[Tier.CHEAP_LLM],
            )

        # --- Tier 5: Full deep agent ---
        self._tier_counters[Tier.DEEP_AGENT] += 1
        return RouteDecision(
            tier=Tier.DEEP_AGENT,
            cache_hit=False,
            intent=None,
            confidence=0.0,
            estimated_cost_usd=self.TIER_COSTS[Tier.DEEP_AGENT],
        )

    def get_tier_distribution(self) -> dict:
        total = sum(self._tier_counters.values()) or 1
        return {
            t.name: {
                "count": self._tier_counters[t],
                "pct": round(self._tier_counters[t] / total * 100, 2),
            }
            for t in Tier
        }

    # ------------------------------------------------------------------ #
    # Internal helpers — replace stubs with real models in production
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fingerprint(w5h2_key: str) -> str:
        return hashlib.sha256(w5h2_key.encode()).hexdigest()

    def _bert_classify(self, text: str) -> Optional[dict]:
        # TODO: plug in sentence-transformers BERT-Large classifier
        # Return {"intent": str, "confidence": float} or None
        return None

    def _setfit_classify(self, text: str) -> Optional[dict]:
        # TODO: plug in SetFit 22M few-shot classifier
        return None

    @staticmethod
    def _estimate_complexity(text: str) -> float:
        """Heuristic complexity score 0-1 based on token count + question depth."""
        words = len(text.split())
        has_multi_step = any(
            kw in text.lower()
            for kw in ["then", "after", "before", "compare", "analyze", "synthesize"]
        )
        score = min(words / 200, 1.0)
        if has_multi_step:
            score = min(score + 0.3, 1.0)
        return score
