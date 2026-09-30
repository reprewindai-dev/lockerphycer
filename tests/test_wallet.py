"""Veklom Wallet on Base: SIWE binding, signature verification, onchain top-ups.

No request leaves the process: the Base RPC is an httpx.MockTransport. EOA
signatures are real (eth_account, throwaway keys generated per test run).
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DEBUG", "true")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"

from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402

TREASURY = "0x000000000000000000000000000000000000dEaD"
USDC_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


def run(coro):
    return asyncio.run(coro)


def siwe_message(address, nonce, *, domain="localhost:8092", chain_id=84532, statement="Bind this wallet to your Veklom workspace.",
                 issued_at=None, expiration=None):
    """Same layout as viem createSiweMessage."""
    issued = (issued_at or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    stmt = f"{statement}\n" if statement else ""
    msg = (f"{domain} wants you to sign in with your Ethereum account:\n{address}\n\n{stmt}\n"
           f"URI: http://{domain}/os/onboarding\nVersion: 1\nChain ID: {chain_id}\nNonce: {nonce}\nIssued At: {issued}")
    if expiration:
        msg += f"\nExpiration Time: {expiration.strftime('%Y-%m-%dT%H:%M:%S.000Z')}"
    return msg


def sign(account, message):
    return "0x" + account.sign_message(encode_defunct(text=message)).signature.hex().removeprefix("0x")


class FakeBase:
    """In-memory Base JSON-RPC: chain id, block number, receipts, eth_call."""

    def __init__(self, chain_id=84532):
        self.chain_id = chain_id
        self.head = 1000
        self.receipts = {}
        self.eth_call_result = "0x00"
        self.eth_calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method, params = body["method"], body["params"]
        if method == "eth_chainId":
            result = hex(self.chain_id)
        elif method == "eth_blockNumber":
            result = hex(self.head)
        elif method == "eth_getTransactionReceipt":
            result = self.receipts.get(params[0])
        elif method == "eth_call":
            self.eth_calls.append(params[0])
            if self.eth_call_result == "revert":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": {"code": 3, "message": "execution reverted"}})
            result = self.eth_call_result
        else:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32601, "message": "nope"}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    def rpc(self):
        from core.wallet.rpc import BaseRpc

        return BaseRpc("https://rpc.base.test", transport=httpx.MockTransport(self.handler))

    def add_transfer(self, tx_hash, *, sender, recipient=TREASURY, value=50_000_000, token=USDC_SEPOLIA, block=990, status="0x1"):
        def topic(addr):
            return "0x" + "0" * 24 + addr.lower()[2:]
        self.receipts[tx_hash] = {
            "transactionHash": tx_hash, "status": status, "blockNumber": hex(block),
            "logs": [{
                "address": token.lower(), "logIndex": "0x1", "removed": False, "data": hex(value),
                "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef", topic(sender), topic(recipient)],
            }],
        }


@pytest.fixture()
def base(monkeypatch):
    from core.wallet import rpc as wallet_rpc
    from core.wallet.config import get_wallet_settings

    fake = FakeBase()
    monkeypatch.setattr(wallet_rpc, "rpc_factory", fake.rpc)
    monkeypatch.setenv("WALLET_NETWORK", "base-sepolia")
    monkeypatch.setenv("WALLET_TREASURY_ADDRESS", TREASURY)
    monkeypatch.setenv("WALLET_SIWE_DOMAINS", "localhost:8092")
    get_wallet_settings.cache_clear()
    yield fake
    get_wallet_settings.cache_clear()


def _seed():
    from core.database.database import Base, SessionLocal, engine
    from core.security.auth import create_access_token, create_refresh_token, get_password_hash
    from db.models import SubscriptionTier, User, UserRole, UserSession, UserStatus, Workspace

    email = f"wallet-{uuid.uuid4().hex}@example.com"
    ws_id = str(uuid.uuid4())

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as db:
            user = User(email=email, username=f"w-{uuid.uuid4().hex[:10]}",
                        hashed_password=get_password_hash("CorrectHorseBatteryStaple1"),
                        role=UserRole.USER, status=UserStatus.ACTIVE)
            db.add(user)
            await db.flush()
            token = create_access_token({"sub": email, "workspace_id": ws_id})
            db.add(UserSession(user_id=user.id, session_token=token, refresh_token=create_refresh_token({"sub": email}),
                               expires_at=datetime.utcnow() + timedelta(hours=1)))
            db.add(Workspace(id=ws_id, owner_id=email, name="w", slug=f"w-{uuid.uuid4().hex[:10]}",
                             tier=SubscriptionTier.FREE, created_at=datetime.utcnow()))
            await db.commit()
        return {"Authorization": f"Bearer {token}"}, ws_id

    return run(seed())


def _events(ws_id):
    from sqlalchemy import select

    from core.database.database import SessionLocal
    from db.models import ActivationEvent

    async def go():
        async with SessionLocal() as db:
            return [e.event_name for e in (await db.execute(
                select(ActivationEvent).where(ActivationEvent.workspace_id == ws_id))).scalars()]
    return run(go())


def _bind(client, headers, account, source="created", provider="cdp_embedded"):
    nonce = client.post("/api/v1/wallet/nonce", headers=headers).json()["nonce"]
    msg = siwe_message(account.address, nonce)
    return client.post("/api/v1/wallet/register", headers=headers,
                       json={"message": msg, "signature": sign(account, msg), "source": source, "wallet_provider": provider})


# ---------------------------------------------------------------------------
# SIWE parsing
# ---------------------------------------------------------------------------


def test_siwe_parses_viem_layout_with_and_without_statement():
    from core.wallet.siwe import parse_message

    acct = Account.create()
    with_stmt = parse_message(siwe_message(acct.address, "abcdef0123456789"))
    assert with_stmt.address == acct.address and with_stmt.chain_id == 84532
    assert with_stmt.statement.startswith("Bind this wallet")
    no_stmt = parse_message(siwe_message(acct.address, "abcdef0123456789", statement=None))
    assert no_stmt.statement is None and no_stmt.nonce == "abcdef0123456789"


def test_siwe_rejects_bad_fields():
    from core.wallet.siwe import SiweError, check_fields, parse_message

    acct = Account.create()
    with pytest.raises(SiweError):
        parse_message(siwe_message(acct.address.lower(), "abcdef0123456789"))  # not EIP-55
    with pytest.raises(SiweError):
        parse_message(siwe_message(acct.address, "short"))
    now = datetime.now(timezone.utc)
    ok = dict(allowed_domains={"localhost:8092"}, chain_id=84532, now=now, max_age_seconds=900)
    check_fields(parse_message(siwe_message(acct.address, "abcdef0123456789")), **ok)
    for bad in (
        siwe_message(acct.address, "abcdef0123456789", domain="evil.example"),
        siwe_message(acct.address, "abcdef0123456789", chain_id=8453),
        siwe_message(acct.address, "abcdef0123456789", issued_at=now - timedelta(hours=2)),
        siwe_message(acct.address, "abcdef0123456789", expiration=now - timedelta(seconds=5)),
    ):
        with pytest.raises(SiweError):
            check_fields(parse_message(bad), **ok)


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_eoa_signature_verifies_locally_without_rpc():
    from core.wallet.signature import verify_personal_signature

    acct = Account.create()
    msg = siwe_message(acct.address, "abcdef0123456789")
    assert run(verify_personal_signature(None, acct.address, msg, sign(acct, msg))).kind == "eoa"


def test_wrong_signer_falls_back_to_onchain_check_and_fails(base):
    from core.wallet.signature import SignatureInvalid, verify_personal_signature

    acct, other = Account.create(), Account.create()
    msg = siwe_message(acct.address, "abcdef0123456789")
    base.eth_call_result = "0x00"
    with pytest.raises(SignatureInvalid):
        run(verify_personal_signature(base.rpc(), acct.address, msg, sign(other, msg)))
    base.eth_call_result = "revert"
    with pytest.raises(SignatureInvalid):
        run(verify_personal_signature(base.rpc(), acct.address, msg, sign(other, msg)))


def test_erc6492_signature_goes_to_deployless_validator(base):
    from core.wallet.erc6492_bytecode import ERC6492_MAGIC_SUFFIX, ERC6492_VALIDATOR_BYTECODE
    from core.wallet.signature import verify_personal_signature

    smart = "0x1111111111111111111111111111111111111111"
    wrapped = "0x" + (b"\x01" * 96 + ERC6492_MAGIC_SUFFIX).hex()
    base.eth_call_result = "0x01"
    result = run(verify_personal_signature(base.rpc(), smart, siwe_message(smart, "abcdef0123456789"), wrapped))
    assert result.kind == "contract"
    call = base.eth_calls[-1]
    assert "to" not in call and call["data"].startswith(ERC6492_VALIDATOR_BYTECODE)
    assert smart[2:].lower() in call["data"].lower()


# ---------------------------------------------------------------------------
# Routes: bind, rebind, nonce replay, onboarding
# ---------------------------------------------------------------------------


def test_register_binds_wallet_and_emits_event(base):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    headers, ws_id = _seed()
    acct = Account.create()
    with TestClient(app) as client:
        assert client.get("/api/v1/wallet", headers=headers).json()["wallet"] is None
        r = _bind(client, headers, acct)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["wallet"]["address"] == acct.address and body["chain_id"] == 84532 and body["testnet"] is True
        assert body["wallet"]["source"] == "created" and body["wallet"]["signature_kind"] == "eoa"
        got = client.get("/api/v1/wallet", headers=headers).json()
        assert got["wallet"]["address"] == acct.address
        state = client.get("/api/v1/wallet/onboarding", headers=headers).json()
        assert state["identity"] and state["wallet"] and not state["capability"]
        assert client.get("/api/v1/wallet").status_code == 401
    assert "wallet_created" in _events(ws_id)


def test_nonce_is_single_use_and_workspace_bound(base):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    headers, _ = _seed()
    other_headers, _ = _seed()
    acct = Account.create()
    with TestClient(app) as client:
        nonce = client.post("/api/v1/wallet/nonce", headers=headers).json()["nonce"]
        msg = siwe_message(acct.address, nonce)
        payload = {"message": msg, "signature": sign(acct, msg), "source": "connected"}
        # Another operator cannot use this workspace's nonce.
        assert client.post("/api/v1/wallet/register", headers=other_headers, json=payload).status_code == 400
        assert client.post("/api/v1/wallet/register", headers=headers, json=payload).status_code == 200
        assert client.post("/api/v1/wallet/register", headers=headers, json=payload).status_code == 400
        # A signature from a different key is refused.
        nonce2 = client.post("/api/v1/wallet/nonce", headers=headers).json()["nonce"]
        msg2 = siwe_message(acct.address, nonce2)
        base.eth_call_result = "0x00"
        bad = {"message": msg2, "signature": sign(Account.create(), msg2), "source": "connected"}
        assert client.post("/api/v1/wallet/register", headers=headers, json=bad).status_code == 400


def test_rebinding_revokes_previous_wallet(base):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    headers, ws_id = _seed()
    first, second = Account.create(), Account.create()
    with TestClient(app) as client:
        assert _bind(client, headers, first).status_code == 200
        assert _bind(client, headers, second, source="connected", provider="walletconnect").status_code == 200
        wallet = client.get("/api/v1/wallet", headers=headers).json()["wallet"]
        assert wallet["address"] == second.address and wallet["wallet_provider"] == "walletconnect"
    events = _events(ws_id)
    assert "wallet_created" in events and "wallet_connected" in events


# ---------------------------------------------------------------------------
# Onchain top-ups
# ---------------------------------------------------------------------------


def _tx():
    return "0x" + uuid.uuid4().hex + uuid.uuid4().hex


def test_transfer_topic_is_keccak_of_signature():
    from eth_utils import keccak

    from core.wallet.topup import TRANSFER_TOPIC

    assert TRANSFER_TOPIC == "0x" + keccak(text="Transfer(address,address,uint256)").hex().removeprefix("0x")


def test_onchain_topup_credits_once(base):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    headers, ws_id = _seed()
    acct = Account.create()
    tx = _tx()
    base.add_transfer(tx, sender=acct.address, value=50_000_000)  # 50 USDC
    with TestClient(app) as client:
        assert _bind(client, headers, acct).status_code == 200
        cfg = client.get("/api/v1/wallet/config", headers=headers).json()
        assert cfg["onchain_topup_enabled"] and cfg["credit_tokens"][0]["address"] == USDC_SEPOLIA
        r = client.post("/api/v1/wallet/topups/onchain", headers=headers, json={"tx_hash": tx})
        assert r.status_code == 200, r.text
        assert r.json()["credited"] is True and r.json()["credits"] == 50 * 100
        again = client.post("/api/v1/wallet/topups/onchain", headers=headers, json={"tx_hash": tx})
        assert again.status_code == 200 and again.json()["replay"] is True
        assert r.json()["balance"]["topup_balance"] == 5000
        snapshot = client.get("/api/v1/entitlements", headers=headers).json()
        assert snapshot["balances"]["topup_balance"] == 5000  # credited exactly once
    assert "funding_method_added" in _events(ws_id)


def test_onchain_topup_rejections(base):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    headers, _ = _seed()
    acct, stranger = Account.create(), Account.create()
    unbound, failed, fresh, wrong_to = _tx(), _tx(), _tx(), _tx()
    base.add_transfer(unbound, sender=stranger.address)
    base.add_transfer(failed, sender=acct.address, status="0x0")
    base.add_transfer(fresh, sender=acct.address, block=base.head)
    base.add_transfer(wrong_to, sender=acct.address, recipient=stranger.address)
    with TestClient(app) as client:
        post = lambda h: client.post("/api/v1/wallet/topups/onchain", headers=headers, json={"tx_hash": h})  # noqa: E731
        assert post(unbound).status_code == 409  # no wallet bound yet
        assert _bind(client, headers, acct).status_code == 200
        assert post(unbound).status_code == 422  # sender is not a bound wallet
        assert post(failed).status_code == 422
        assert post(fresh).status_code == 409  # not enough confirmations
        assert post(wrong_to).status_code == 422
        assert post(_tx()).status_code == 409  # not mined / unknown
        assert client.post("/api/v1/wallet/topups/onchain", headers=headers, json={"tx_hash": "0x" + "zz" * 32}).status_code == 400
        base.chain_id = 8453
        assert post(unbound).status_code == 422  # RPC on the wrong chain


def test_onchain_topup_disabled_without_treasury(base, monkeypatch):
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from core.wallet.config import get_wallet_settings

    monkeypatch.setenv("WALLET_TREASURY_ADDRESS", "")
    get_wallet_settings.cache_clear()
    headers, _ = _seed()
    with TestClient(app) as client:
        assert client.post("/api/v1/wallet/topups/onchain", headers=headers, json={"tx_hash": _tx()}).status_code == 503
        assert client.get("/api/v1/wallet/config", headers=headers).json()["onchain_topup_enabled"] is False
