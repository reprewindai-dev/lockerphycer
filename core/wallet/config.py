"""Wallet settings.

Testnet by default: WALLET_NETWORK=base-sepolia (chain 84532). The owner flips
to Base mainnet (chain 8453) by setting WALLET_NETWORK=base. Nothing here holds
a key; the treasury is a receive-only address.

Sources:
  * Chain ids and public RPC endpoints: https://docs.base.org/get-started/connect-to-base
  * USDC contract addresses on Base / Base Sepolia:
    https://developers.circle.com/stablecoins/usdc-contract-addresses (linked from
    https://docs.base.org/build-on-base/accept-payments/make-a-simple-payment)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - pydantic v1 fallback
    from pydantic import BaseSettings
    SettingsConfigDict = dict


@dataclass(frozen=True)
class Network:
    key: str
    chain_id: int
    name: str
    public_rpc: str
    explorer: str


NETWORKS: dict[str, Network] = {
    "base-sepolia": Network("base-sepolia", 84532, "Base Sepolia", "https://sepolia.base.org", "https://sepolia.basescan.org"),
    "base": Network("base", 8453, "Base", "https://mainnet.base.org", "https://basescan.org"),
}


@dataclass(frozen=True)
class CreditToken:
    """A token that converts to Veklom credits automatically at a fixed USD rate.

    Only USD stablecoins are listed by default: converting a volatile token needs a
    price source, which is not wired (see TODO in core/wallet/topup.py).
    """

    symbol: str
    address: str  # lower-case
    decimals: int
    usd_per_token: float


# Circle USDC. Same addresses as apps/api/routers/x402.py uses for mainnet.
DEFAULT_CREDIT_TOKENS: dict[int, tuple[CreditToken, ...]] = {
    8453: (CreditToken("USDC", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", 6, 1.0),),
    84532: (CreditToken("USDC", "0x036cbd53842c5426634e7929541ec2318f3dcf7e", 6, 1.0),),
}


class WalletSettings(BaseSettings):
    # "base-sepolia" (default, testnet) or "base" (mainnet).
    WALLET_NETWORK: str = "base-sepolia"
    # Optional dedicated RPC endpoint. Empty -> the public Base endpoint for the network.
    WALLET_RPC_URL: str = ""
    # Receive-only address that onchain top-ups must be sent to. Empty disables
    # onchain top-ups (the endpoint answers 503, fail closed).
    WALLET_TREASURY_ADDRESS: str = ""
    # Comma-separated host[:port] values accepted as the SIWE "domain". Empty ->
    # the host of FRONTEND_URL.
    WALLET_SIWE_DOMAINS: str = ""
    WALLET_NONCE_TTL_SECONDS: int = 600
    # Maximum age of the SIWE Issued At timestamp.
    WALLET_SIWE_MAX_AGE_SECONDS: int = 900
    # Confirmations required before an onchain top-up is credited.
    WALLET_MIN_CONFIRMATIONS: int = 3
    # Optional JSON list overriding the credit tokens for the active chain:
    # [{"symbol":"USDC","address":"0x...","decimals":6,"usd_per_token":1.0}]
    WALLET_CREDIT_TOKENS_JSON: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def network(self) -> Network:
        key = (self.WALLET_NETWORK or "base-sepolia").strip().lower()
        if key not in NETWORKS:
            raise ValueError(f"WALLET_NETWORK must be one of {sorted(NETWORKS)}")
        return NETWORKS[key]

    @property
    def rpc_url(self) -> str:
        return self.WALLET_RPC_URL.strip() or self.network.public_rpc

    def credit_tokens(self) -> tuple[CreditToken, ...]:
        if self.WALLET_CREDIT_TOKENS_JSON.strip():
            raw = json.loads(self.WALLET_CREDIT_TOKENS_JSON)
            return tuple(
                CreditToken(str(t["symbol"]), str(t["address"]).lower(), int(t["decimals"]), float(t["usd_per_token"]))
                for t in raw
            )
        return DEFAULT_CREDIT_TOKENS.get(self.network.chain_id, ())

    def siwe_domains(self, frontend_url: str) -> set[str]:
        values = {d.strip().lower() for d in self.WALLET_SIWE_DOMAINS.split(",") if d.strip()}
        if not values:
            host = urlparse(frontend_url).netloc.lower()
            if host:
                values.add(host)
        return values


@lru_cache
def get_wallet_settings() -> WalletSettings:
    return WalletSettings()
