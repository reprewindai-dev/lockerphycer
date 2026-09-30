from typing import Any, Dict, List
from datetime import datetime
import json
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

import nacl.signing
import nacl.encoding
import nacl.exceptions
from cryptography.fernet import Fernet

# Hardcoded KMS abstraction key for the M1P2 proof
_KMS_KEY = b'xR1n_eS9L2gHjK9q4A_l5Fv8Xk2YvN8Pj9D7bF8XbZg='
_fernet = Fernet(_KMS_KEY)

from core.database.database import get_db
from core.security.auth import get_current_user
from db.models import User, AuthorityKey, KeyStatus

router = APIRouter(tags=["Capability OS Keys"])

class RegisterHolderRequest(BaseModel):
    holder_id: str
    lineage_id: str

class RotateKeyRequest(BaseModel):
    pass

class RevokeKeyRequest(BaseModel):
    pass

class SignRequest(BaseModel):
    key_id: str
    operation_id: str
    epoch: int
    command: str

class KeyResponse(BaseModel):
    id: str
    holder_id: str
    lineage_id: str
    algorithm: str
    public_key: str
    status: KeyStatus
    generation: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class SignResponse(BaseModel):
    signature: str
    canonical_message: str


def _generate_ed25519_keypair():
    signing_key = nacl.signing.SigningKey.generate()
    private_hex = signing_key.encode(encoder=nacl.encoding.HexEncoder).decode('utf-8')
    public_hex = signing_key.verify_key.encode(encoder=nacl.encoding.HexEncoder).decode('utf-8')
    return private_hex, public_hex


@router.post("/register", response_model=KeyResponse)
async def register_holder(
    request: RegisterHolderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Register a new holder with a new Ed25519 keypair."""
    # Check if active key already exists
    stmt = select(AuthorityKey).where(
        AuthorityKey.holder_id == request.holder_id,
        AuthorityKey.status == KeyStatus.ACTIVE
    )
    result = await db.execute(stmt)
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Holder already has an active key")
        
    private_hex, public_hex = _generate_ed25519_keypair()
    
    # Real encryption of private key using Fernet (KMS abstraction)
    encrypted_private = f"enc_v1:{_fernet.encrypt(private_hex.encode()).decode()}"
    
    key = AuthorityKey(
        holder_id=request.holder_id,
        lineage_id=request.lineage_id,
        algorithm="ed25519",
        public_key=public_hex,
        encrypted_private_key=encrypted_private,
        status=KeyStatus.ACTIVE,
        generation=1,
        activated_at=datetime.utcnow()
    )
    
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


@router.get("/bindings/{holder_id}", response_model=List[KeyResponse])
async def get_holder_bindings(
    holder_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get public keys for a holder."""
    stmt = select(AuthorityKey).where(
        AuthorityKey.holder_id == holder_id
    ).order_by(AuthorityKey.generation.desc())
    result = await db.execute(stmt)
    keys = result.scalars().all()
    if not keys:
        raise HTTPException(status_code=404, detail="Holder not found")
    return keys


@router.post("/{key_id}/rotate", response_model=KeyResponse)
async def rotate_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Rotate an active key."""
    key = await db.get(AuthorityKey, key_id)
    if not key or key.status != KeyStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Active key not found")
        
    # Mark old key as ROTATED
    key.status = KeyStatus.ROTATED
    key.revoked_at = datetime.utcnow()
    
    private_hex, public_hex = _generate_ed25519_keypair()
    encrypted_private = f"enc_v1:{_fernet.encrypt(private_hex.encode()).decode()}"
    
    new_key = AuthorityKey(
        holder_id=key.holder_id,
        lineage_id=key.lineage_id,
        algorithm="ed25519",
        public_key=public_hex,
        encrypted_private_key=encrypted_private,
        status=KeyStatus.ACTIVE,
        generation=key.generation + 1,
        rotation_parent_key_id=key.id,
        activated_at=datetime.utcnow()
    )
    
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)
    return new_key


@router.post("/{key_id}/revoke")
async def revoke_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Revoke a key."""
    key = await db.get(AuthorityKey, key_id)
    if not key or key.status in [KeyStatus.REVOKED, KeyStatus.ROTATED]:
        raise HTTPException(status_code=404, detail="Valid key not found")
        
    key.status = KeyStatus.REVOKED
    key.revoked_at = datetime.utcnow()
    await db.commit()
    return {"message": "Key revoked successfully"}


@router.post("/sign", response_model=SignResponse)
async def request_signature(
    request: SignRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Request a signature for an operation."""
    key = await db.get(AuthorityKey, request.key_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    if key.status != KeyStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="Key is not active")
        
    # In production, decrypt using KMS
    if not key.encrypted_private_key.startswith("enc_v1:"):
        raise HTTPException(status_code=500, detail="Invalid encrypted key format")
    encrypted_payload = key.encrypted_private_key[7:]
    try:
        private_hex = _fernet.decrypt(encrypted_payload.encode()).decode()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt key")
    
    canonical = f"{request.operation_id}|{request.epoch}|{key.holder_id}|{key.lineage_id}|{request.command}"
    
    signing_key = nacl.signing.SigningKey(private_hex, encoder=nacl.encoding.HexEncoder)
    signed = signing_key.sign(canonical.encode("utf-8"))
    
    return SignResponse(
        signature=signed.signature.hex(),
        canonical_message=canonical
    )
