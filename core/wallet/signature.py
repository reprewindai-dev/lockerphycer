"""Verify an EIP-191 ``personal_sign`` signature for a wallet address.

Order (ERC-6492 requires the magic-suffix check before ecrecover):
  1. Signature ends with the ERC-6492 magic suffix -> onchain check.
  2. Plain 65-byte signature that ecrecovers to the address -> valid EOA.
  3. Otherwise -> onchain check with the deployless ERC-6492 universal
     validator (also covers deployed ERC-1271 smart wallets such as Base
     Account / CDP smart accounts).

The onchain check is a read-only eth_call; nothing is deployed or sent.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import defunct_hash_message, encode_defunct
from eth_utils import to_checksum_address

from core.wallet.erc6492_bytecode import ERC6492_MAGIC_SUFFIX, ERC6492_VALIDATOR_BYTECODE
from core.wallet.rpc import BaseRpc, RpcError, RpcUnavailable


class SignatureInvalid(ValueError):
    pass


@dataclass(frozen=True)
class SignatureResult:
    kind: str  # "eoa" | "contract"


def _hex_to_bytes(value: str) -> bytes:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise SignatureInvalid("signature must be 0x-prefixed hex")
    try:
        return bytes.fromhex(value[2:])
    except ValueError as exc:
        raise SignatureInvalid("signature is not hex") from exc


def message_hash(message: str) -> bytes:
    return bytes(defunct_hash_message(text=message))


def _recover(message: str, signature: bytes) -> str | None:
    try:
        return Account.recover_message(encode_defunct(text=message), signature=signature)
    except Exception:
        return None


async def verify_personal_signature(rpc: BaseRpc | None, address: str, message: str, signature_hex: str) -> SignatureResult:
    address = to_checksum_address(address)
    signature = _hex_to_bytes(signature_hex)
    if not signature or len(signature) > 16_384:
        raise SignatureInvalid("signature length out of range")

    is_6492 = signature.endswith(ERC6492_MAGIC_SUFFIX)
    if not is_6492 and len(signature) == 65:
        recovered = _recover(message, signature)
        if recovered is not None and recovered == address:
            return SignatureResult("eoa")

    if rpc is None:
        raise SignatureInvalid("smart-wallet signature needs an RPC endpoint")
    data = ERC6492_VALIDATOR_BYTECODE + abi_encode(
        ["address", "bytes32", "bytes"], [address, message_hash(message), signature]
    ).hex()
    try:
        result = await rpc.eth_call({"data": data})
    except RpcUnavailable:
        raise
    except RpcError as exc:  # a revert means "not valid"
        raise SignatureInvalid("signature rejected by the onchain validator") from exc
    if isinstance(result, str) and result.lower() in ("0x01", "0x" + "0" * 63 + "1"):
        return SignatureResult("contract")
    raise SignatureInvalid("signature does not match the address")
