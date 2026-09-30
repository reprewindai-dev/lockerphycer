"""Onchain top-up verification: a token transfer on Base -> Veklom credits.

Flow (per https://docs.base.org/build-on-base/accept-payments/make-a-simple-payment:
"Never trust the browser"; the backend reads the receipt and matches the payment):

  1. The user sends a credit token (USDC by default) from a wallet bound to the
     workspace to WALLET_TREASURY_ADDRESS, using their own wallet.
  2. The frontend posts only the transaction hash.
  3. This module reads the receipt from Base and credits the workspace only if:
       * the RPC is on the configured chain,
       * the receipt exists, succeeded (status 0x1) and has
         >= WALLET_MIN_CONFIRMATIONS confirmations,
       * it contains ERC-20 Transfer logs emitted by a configured credit-token
         contract, to the treasury, from an address this workspace proved
         ownership of with SIWE (so nobody can claim someone else's payment).
  4. Credits are granted through the existing ledger (grant_topup) with the
     idempotency key onchain:<chain>:<tx>, so a transaction credits once.

Smart-wallet (ERC-4337) transfers are covered: the bundler is the transaction
sender, but the Transfer log's "from" is the smart account itself.

TODO(owner): only fixed-rate tokens (USD stablecoins) convert to credits.
Accepting a volatile Base token as a credit top-up needs a price source and a
slippage policy; such transfers are ignored here rather than mispriced. They can
still be accepted for machine settlement over x402 (any ERC-20, see
https://docs.cdp.coinbase.com/x402/support/faq), which is a separate path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from core.wallet.config import CreditToken
from core.wallet.rpc import BaseRpc

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
_TX_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")


class TopupRejected(ValueError):
    """Permanent rejection (the transaction will never qualify)."""


class TopupPending(ValueError):
    """Not yet creditable (not mined or not enough confirmations); retry later."""


@dataclass(frozen=True)
class VerifiedTopup:
    tx_hash: str
    chain_id: int
    credits: int
    usd: Decimal
    transfers: tuple[dict, ...]
    block_number: int


def normalize_tx_hash(tx_hash: str) -> str:
    if not isinstance(tx_hash, str) or not _TX_HASH.match(tx_hash):
        raise TopupRejected("tx_hash must be a 0x-prefixed 32-byte hex string")
    return tx_hash.lower()


def _topic_address(topic: str) -> str:
    return "0x" + topic[-40:].lower()


async def verify_topup(
    rpc: BaseRpc,
    *,
    tx_hash: str,
    chain_id: int,
    treasury: str,
    payers: set[str],
    tokens: tuple[CreditToken, ...],
    min_confirmations: int,
    credits_per_usd: int,
) -> VerifiedTopup:
    tx_hash = normalize_tx_hash(tx_hash)
    treasury = treasury.lower()
    payers = {p.lower() for p in payers}
    by_address = {t.address.lower(): t for t in tokens}
    if not by_address:
        raise TopupRejected("no credit tokens are configured for this network")

    if await rpc.chain_id() != chain_id:
        raise TopupRejected("RPC endpoint is not on the configured chain")
    receipt = await rpc.get_transaction_receipt(tx_hash)
    if not receipt:
        raise TopupPending("transaction not found yet")
    if receipt.get("status") != "0x1":
        raise TopupRejected("transaction failed onchain")
    block = int(receipt["blockNumber"], 16)
    head = await rpc.block_number()
    if head - block + 1 < max(1, min_confirmations):
        raise TopupPending(f"waiting for {min_confirmations} confirmations")

    transfers: list[dict] = []
    usd_total = Decimal(0)
    for log in receipt.get("logs") or []:
        if log.get("removed"):
            continue
        token = by_address.get(str(log.get("address", "")).lower())
        topics = log.get("topics") or []
        if token is None or len(topics) != 3 or str(topics[0]).lower() != TRANSFER_TOPIC:
            continue
        sender, recipient = _topic_address(topics[1]), _topic_address(topics[2])
        if recipient != treasury or sender not in payers:
            continue
        value = int(log.get("data") or "0x0", 16)
        if value <= 0:
            continue
        usd = Decimal(value) / (Decimal(10) ** token.decimals) * Decimal(str(token.usd_per_token))
        usd_total += usd
        transfers.append({"token": token.symbol, "contract": token.address, "from": sender,
                          "value": str(value), "log_index": int(log.get("logIndex") or "0x0", 16)})

    if not transfers:
        raise TopupRejected("no credit-token transfer from a bound wallet to the Veklom treasury in this transaction")
    credits = int((usd_total * Decimal(credits_per_usd)).to_integral_value(rounding=ROUND_DOWN))
    if credits <= 0:
        raise TopupRejected("amount is below one credit")
    return VerifiedTopup(tx_hash=tx_hash, chain_id=chain_id, credits=credits, usd=usd_total,
                         transfers=tuple(transfers), block_number=block)
