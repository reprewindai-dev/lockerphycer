"""EIP-4361 (Sign-In with Ethereum) message parsing and field validation.

Spec: https://eips.ethereum.org/EIPS/eip-4361. Base's "Sign in with Base" guide
(https://docs.cdp.coinbase.com/coinbase-wallet/guides/authenticate-users) uses
this standard, so one verifier serves embedded, Base Account and any EIP-1193
wallet. The frontend builds the message with viem's ``createSiweMessage``.

Only the exact signed text is ever trusted: the signature is verified over the
raw message, and every field used here is parsed from that same text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from eth_utils import is_checksum_address

_HEADER = re.compile(
    r"^(?:(?P<scheme>[a-zA-Z][a-zA-Z0-9+\-.]*)://)?(?P<domain>[^\s/?#]+) wants you to sign in with your Ethereum account:$"
)
_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
_NONCE = re.compile(r"^[a-zA-Z0-9]{8,}$")
# Field order is fixed by the EIP-4361 ABNF.
_FIELDS = ("URI", "Version", "Chain ID", "Nonce", "Issued At", "Expiration Time", "Not Before", "Request ID")
_REQUIRED = {"URI", "Version", "Chain ID", "Nonce", "Issued At"}


class SiweError(ValueError):
    """The message is malformed or fails a field check (reason in args[0])."""


@dataclass(frozen=True)
class SiweMessage:
    domain: str
    address: str
    uri: str
    version: str
    chain_id: int
    nonce: str
    issued_at: datetime
    scheme: str | None = None
    statement: str | None = None
    expiration_time: datetime | None = None
    not_before: datetime | None = None
    request_id: str | None = None
    resources: tuple[str, ...] = field(default_factory=tuple)


def _parse_time(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SiweError(f"invalid {name}") from exc
    if parsed.tzinfo is None:
        raise SiweError(f"{name} must carry a timezone")
    return parsed.astimezone(timezone.utc)


def parse_message(message: str) -> SiweMessage:
    if not isinstance(message, str) or len(message) > 4096:
        raise SiweError("message missing or too long")
    lines = message.split("\n")
    if len(lines) < 7:
        raise SiweError("message too short")
    header = _HEADER.match(lines[0])
    if not header:
        raise SiweError("invalid header line")
    address = lines[1]
    if not _ADDRESS.match(address) or not is_checksum_address(address):
        raise SiweError("address must be an EIP-55 checksummed address")
    if lines[2] != "":
        raise SiweError("expected a blank line after the address")

    # ABNF: address LF LF [ statement LF ] LF "URI: " ...
    idx = 3
    statement = None
    if lines[idx] == "":
        idx += 1  # no statement
    else:
        statement = lines[idx]
        if idx + 1 >= len(lines) or lines[idx + 1] != "":
            raise SiweError("statement must be one line followed by a blank line")
        idx += 2
    if idx >= len(lines) or not lines[idx].startswith("URI: "):
        raise SiweError("expected the URI field")

    values: dict[str, str] = {}
    order = 0
    resources: list[str] = []
    while idx < len(lines):
        line = lines[idx]
        if line == "Resources:":
            resources = [r[2:] for r in lines[idx + 1:]]
            if any(not r.startswith("- ") for r in lines[idx + 1:]):
                raise SiweError("invalid resources list")
            break
        key, sep, value = line.partition(": ")
        if not sep or key not in _FIELDS:
            raise SiweError(f"unexpected line: {line[:40]!r}")
        position = _FIELDS.index(key)
        if position < order or key in values:
            raise SiweError("fields out of order or repeated")
        order = position
        values[key] = value
        idx += 1

    missing = _REQUIRED - set(values)
    if missing:
        raise SiweError(f"missing field(s): {', '.join(sorted(missing))}")
    if values["Version"] != "1":
        raise SiweError("unsupported SIWE version")
    try:
        chain_id = int(values["Chain ID"])
    except ValueError as exc:
        raise SiweError("invalid Chain ID") from exc
    if not _NONCE.match(values["Nonce"]):
        raise SiweError("invalid nonce")

    return SiweMessage(
        domain=header.group("domain"),
        scheme=header.group("scheme"),
        address=address,
        statement=statement,
        uri=values["URI"],
        version=values["Version"],
        chain_id=chain_id,
        nonce=values["Nonce"],
        issued_at=_parse_time(values["Issued At"], "Issued At"),
        expiration_time=_parse_time(values["Expiration Time"], "Expiration Time") if "Expiration Time" in values else None,
        not_before=_parse_time(values["Not Before"], "Not Before") if "Not Before" in values else None,
        request_id=values.get("Request ID"),
        resources=tuple(resources),
    )


def check_fields(
    msg: SiweMessage,
    *,
    allowed_domains: set[str],
    chain_id: int,
    now: datetime,
    max_age_seconds: int,
    clock_skew_seconds: int = 60,
) -> None:
    """Domain binding, chain, and time-window checks (nonce is checked by the caller)."""
    now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if msg.domain.lower() not in allowed_domains:
        raise SiweError("domain is not accepted by this server")
    if msg.chain_id != chain_id:
        raise SiweError(f"wrong chain: expected {chain_id}")
    if (msg.issued_at - now).total_seconds() > clock_skew_seconds:
        raise SiweError("Issued At is in the future")
    if (now - msg.issued_at).total_seconds() > max_age_seconds:
        raise SiweError("message is too old; sign again")
    if msg.expiration_time is not None and msg.expiration_time <= now:
        raise SiweError("message has expired")
    if msg.not_before is not None and (msg.not_before - now).total_seconds() > clock_skew_seconds:
        raise SiweError("message is not valid yet")
