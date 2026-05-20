"""
W5H2 Structured Intent Canonicalization
Decomposes any agent query into structured fields and produces
a canonical cache key using (What, Where) as the primary key.

This is the core mechanism that enables NabaOS to reuse cached
execution plans across semantically similar but textually different queries.
"""
from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class W5H2Intent:
    what: str           # Action-Target  e.g. "check_email"
    where: str          # Platform       e.g. "gmail"
    who: Optional[str] = None   # Subject
    when: Optional[str] = None  # Time expression
    why: Optional[str] = None   # Context / goal
    how: Optional[str] = None   # Parameters / method
    how_much: Optional[str] = None  # Quantitative bound

    def cache_key(self) -> str:
        """Primary cache key — (What, Where) pair only."""
        return f"{self.what.lower()}::{self.where.lower()}"

    def full_key(self) -> str:
        """Full structured key for exact-match fingerprinting."""
        parts = [
            self.what, self.where,
            self.who or "",
            self.when or "",
            self.how or "",
            self.how_much or "",
        ]
        return "::".join(p.lower().strip() for p in parts)


class W5H2Canonicalizer:
    """
    Converts a raw natural-language query into a W5H2Intent.

    In production: replace the rule-based extraction stubs with
    a fine-tuned NER / slot-filling model or a cheap LLM call
    that is itself cached at Tier 1.
    """

    # Simple keyword maps — extend as needed
    PLATFORM_KEYWORDS = {
        "gmail": "gmail", "email": "email", "outlook": "outlook",
        "slack": "slack", "github": "github", "jira": "jira",
        "notion": "notion", "drive": "gdrive", "calendar": "calendar",
    }

    ACTION_KEYWORDS = {
        "check": "read", "read": "read", "fetch": "read", "get": "read",
        "send": "send", "write": "send", "reply": "send", "compose": "send",
        "create": "create", "make": "create", "add": "create",
        "delete": "delete", "remove": "delete", "trash": "delete",
        "list": "list", "show": "list", "find": "search", "search": "search",
        "summarize": "summarize", "analyze": "analyze", "compare": "compare",
    }

    TIME_PATTERNS = [
        r"\b(today|yesterday|tomorrow|this week|last week|next week)",
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        r"\b(\d{1,2}[:/]\d{2}(?:am|pm)?)",
        r"\b(\d+\s*(?:hours?|days?|weeks?|months?)\s*ago)",
        r"\b(in the last \d+ (?:hours?|days?))",
    ]

    def canonicalize(self, query: str) -> W5H2Intent:
        q = query.lower().strip()

        what = self._extract_action(q)
        where = self._extract_platform(q)
        who = self._extract_subject(q)
        when = self._extract_time(q)
        how_much = self._extract_quantity(q)

        return W5H2Intent(
            what=what,
            where=where,
            who=who,
            when=when,
            how_much=how_much,
        )

    def _extract_action(self, q: str) -> str:
        for kw, canonical in self.ACTION_KEYWORDS.items():
            if re.search(rf"\b{kw}\b", q):
                return canonical
        return "unknown_action"

    def _extract_platform(self, q: str) -> str:
        for kw, canonical in self.PLATFORM_KEYWORDS.items():
            if kw in q:
                return canonical
        return "unknown_platform"

    def _extract_subject(self, q: str) -> Optional[str]:
        # Extract name after possessive or "from/to"
        match = re.search(
            r"(?:from|to|by|about|for)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            q,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    def _extract_time(self, q: str) -> Optional[str]:
        for pattern in self.TIME_PATTERNS:
            match = re.search(pattern, q, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _extract_quantity(self, q: str) -> Optional[str]:
        match = re.search(r"\b(\d+)\s*(?:items?|results?|records?|rows?|messages?)", q, re.IGNORECASE)
        return match.group(0) if match else None
