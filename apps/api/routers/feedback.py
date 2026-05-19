"""Feedback, suggestions, and bug-report routes"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional
from datetime import datetime
import uuid

from core.database.database import get_db
from db.models import Feedback

router = APIRouter()


@router.post("/")
async def submit_feedback(
    category: str,
    subject: str,
    body: str,
    user_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Submit feedback, bug report, or suggestion (public)"""
    fb = Feedback(
        id=str(uuid.uuid4()),
        user_id=user_id,
        category=category,
        subject=subject,
        body=body,
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return {"id": fb.id, "message": "Thank you for your feedback"}


@router.get("/")
async def list_feedback(
    category: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(Feedback).order_by(desc(Feedback.created_at))
    if category:
        query = query.where(Feedback.category == category)
    if status:
        query = query.where(Feedback.status == status)
    result = await db.execute(query.offset(skip).limit(limit))
    items = result.scalars().all()
    total = await db.execute(select(func.count()).select_from(Feedback))
    return {
        "items": [
            {
                "id": f.id,
                "category": f.category,
                "subject": f.subject,
                "body": f.body,
                "status": f.status,
                "priority": f.priority,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in items
        ],
        "total": total.scalar() or 0,
    }


@router.get("/{feedback_id}")
async def get_feedback(feedback_id: str, db: AsyncSession = Depends(get_db)):
    fb = await db.get(Feedback, feedback_id)
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return {
        "id": fb.id,
        "category": fb.category,
        "subject": fb.subject,
        "body": fb.body,
        "status": fb.status,
        "priority": fb.priority,
        "created_at": fb.created_at.isoformat() if fb.created_at else None,
    }


@router.put("/{feedback_id}/resolve")
async def resolve_feedback(
    feedback_id: str,
    resolution: str = "resolved",
    db: AsyncSession = Depends(get_db),
):
    fb = await db.get(Feedback, feedback_id)
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")
    fb.status = resolution
    fb.resolved_at = datetime.utcnow()
    await db.commit()
    return {"id": fb.id, "status": fb.status}
