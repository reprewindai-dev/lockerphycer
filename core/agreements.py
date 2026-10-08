"""The agreements a person accepts to open an account.

The server decides which documents and versions are current; a client only says which
ones the person ticked. Changing a version here means new signups accept the new text.
"""

CURRENT_AGREEMENTS: dict[str, str] = {
    "terms": "2026-08-28",
    "privacy": "2026-08-28",
    "acceptable_use": "2026-08-28",
    "github_boundary": "2026-08-28",
    "device_flow": "2026-08-28",
}
