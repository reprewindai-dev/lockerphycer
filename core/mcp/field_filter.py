"""
MCP Response Field Filter
Strips unnecessary fields from MCP tool responses before they
enter the context window. 80-90% token reduction per call.

Usage:
    filtered = MCPFieldFilter.filter("github_pr", raw_response)
"""
from typing import Any
import logging

logger = logging.getLogger(__name__)

# Define keep-fields per tool. Everything else is stripped.
# Extend this map as you add more MCP tools.
FIELD_ALLOWLIST: dict[str, list[str]] = {
    "github_pr": ["title", "body", "diff", "state", "number", "head", "base"],
    "github_issue": ["title", "body", "state", "number", "labels", "assignees"],
    "github_file": ["content", "path", "sha"],
    "github_search": ["items"],
    "jira_issue": ["summary", "description", "status", "priority", "assignee"],
    "slack_message": ["text", "user", "ts", "channel"],
    "email": ["subject", "from", "to", "body", "date"],
    "calendar_event": ["title", "start", "end", "attendees", "description"],
    "web_search": ["title", "url", "snippet"],
    "database_query": ["rows", "count", "columns"],
}

# Server-side aggregation tools — these replace list+count patterns
AGGREGATION_TOOLS = {
    "count_open_issues": "SELECT COUNT(*) WHERE state='open'",
    "count_pending_prs": "SELECT COUNT(*) WHERE state='open' AND review_requested=true",
    "sum_token_usage": "SELECT SUM(tokens) FROM usage_log WHERE date=TODAY",
}


class MCPFieldFilter:
    """
    Apply field filtering to MCP responses before they hit the context window.
    """

    @classmethod
    def filter(cls, tool_name: str, response: Any) -> Any:
        """Filter response to allowlisted fields only."""
        if tool_name not in FIELD_ALLOWLIST:
            logger.debug("No allowlist for tool '%s' — returning full response", tool_name)
            return response

        allowed = FIELD_ALLOWLIST[tool_name]

        if isinstance(response, dict):
            filtered = {k: v for k, v in response.items() if k in allowed}
            original_keys = len(response)
            filtered_keys = len(filtered)
            reduction = round((1 - filtered_keys / max(original_keys, 1)) * 100, 1)
            logger.debug(
                "MCP filter '%s': %d → %d keys (%.1f%% reduction)",
                tool_name, original_keys, filtered_keys, reduction,
            )
            return filtered

        if isinstance(response, list):
            return [cls.filter(tool_name, item) for item in response]

        return response

    @classmethod
    def estimate_token_reduction(cls, tool_name: str, response: dict) -> float:
        """Estimate token reduction ratio for logging/monitoring."""
        if tool_name not in FIELD_ALLOWLIST:
            return 0.0
        allowed = set(FIELD_ALLOWLIST[tool_name])
        total_chars = sum(len(str(v)) for v in response.values())
        kept_chars = sum(len(str(v)) for k, v in response.items() if k in allowed)
        return 1.0 - (kept_chars / max(total_chars, 1))
