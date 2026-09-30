"""Minimal read-only JSON-RPC client for Base (eth_call, receipts, block number).

Uses httpx (already a dependency); the transport is injectable for tests so no
test request leaves the process. No method here can sign or send anything.
"""

from __future__ import annotations

import itertools
from typing import Any

import httpx

from core.wallet.config import get_wallet_settings


class RpcError(RuntimeError):
    """The node answered with a JSON-RPC error (e.g. an eth_call revert)."""


class RpcUnavailable(RpcError):
    """The node could not be reached or answered with a non-200 status."""


class BaseRpc:
    def __init__(self, url: str, *, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 15.0) -> None:
        self._url = url
        self._transport = transport
        self._timeout = timeout
        self._ids = itertools.count(1)

    async def call(self, method: str, params: list[Any]) -> Any:
        body = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
                resp = await client.post(self._url, json=body)
        except httpx.HTTPError as exc:
            raise RpcUnavailable(f"{method}: rpc unreachable") from exc
        if resp.status_code != 200:
            raise RpcUnavailable(f"{method}: rpc http {resp.status_code}")
        data = resp.json()
        if "error" in data and data["error"] is not None:
            err = data["error"]
            raise RpcError(f"{method}: {err.get('message') if isinstance(err, dict) else err}")
        return data.get("result")

    async def eth_call(self, tx: dict[str, str], block: str = "latest") -> str:
        return await self.call("eth_call", [tx, block])

    async def get_transaction_receipt(self, tx_hash: str) -> dict | None:
        return await self.call("eth_getTransactionReceipt", [tx_hash])

    async def block_number(self) -> int:
        return int(await self.call("eth_blockNumber", []), 16)

    async def chain_id(self) -> int:
        return int(await self.call("eth_chainId", []), 16)


def default_rpc() -> BaseRpc:
    return BaseRpc(get_wallet_settings().rpc_url)


# Swappable in tests.
rpc_factory = default_rpc
