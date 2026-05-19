"""Marketplace routes — tools, models, plugins"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional
from datetime import datetime
import uuid

from core.database.database import get_db
from db.models import MarketplaceListing

router = APIRouter()


@router.get("/listings")
async def list_marketplace(
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = Query("newest", enum=["newest", "popular", "rating"]),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(MarketplaceListing).where(MarketplaceListing.is_published == True)
    if category:
        query = query.where(MarketplaceListing.category == category)
    if search:
        query = query.where(MarketplaceListing.name.ilike(f"%{search}%"))
    if sort == "popular":
        query = query.order_by(desc(MarketplaceListing.downloads))
    elif sort == "rating":
        query = query.order_by(desc(MarketplaceListing.rating))
    else:
        query = query.order_by(desc(MarketplaceListing.created_at))
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    listings = result.scalars().all()
    count_result = await db.execute(
        select(func.count()).select_from(MarketplaceListing).where(
            MarketplaceListing.is_published == True
        )
    )
    return {
        "listings": [
            {
                "id": l.id,
                "name": l.name,
                "slug": l.slug,
                "description": l.description,
                "category": l.category,
                "type": l.listing_type,
                "price_cents": l.price_cents,
                "downloads": l.downloads,
                "rating": l.rating,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in listings
        ],
        "total": count_result.scalar() or 0,
    }


@router.get("/listings/{listing_id}")
async def get_listing(listing_id: str, db: AsyncSession = Depends(get_db)):
    listing = await db.get(MarketplaceListing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {
        "id": listing.id,
        "name": listing.name,
        "slug": listing.slug,
        "description": listing.description,
        "category": listing.category,
        "type": listing.listing_type,
        "price_cents": listing.price_cents,
        "downloads": listing.downloads,
        "rating": listing.rating,
        "metadata": listing.metadata_,
        "is_published": listing.is_published,
        "created_at": listing.created_at.isoformat() if listing.created_at else None,
    }


@router.post("/listings")
async def create_listing(
    name: str,
    description: str = "",
    category: str = "tool",
    listing_type: str = "tool",
    price_cents: int = 0,
    db: AsyncSession = Depends(get_db),
):
    listing = MarketplaceListing(
        id=str(uuid.uuid4()),
        name=name,
        slug=name.lower().replace(" ", "-"),
        description=description,
        category=category,
        listing_type=listing_type,
        price_cents=price_cents,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    return {"id": listing.id, "name": listing.name, "slug": listing.slug}


@router.put("/listings/{listing_id}/publish")
async def publish_listing(listing_id: str, db: AsyncSession = Depends(get_db)):
    listing = await db.get(MarketplaceListing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing.is_published = True
    listing.updated_at = datetime.utcnow()
    await db.commit()
    return {"message": "Listing published", "id": listing.id}


@router.post("/listings/{listing_id}/install")
async def install_listing(listing_id: str, db: AsyncSession = Depends(get_db)):
    listing = await db.get(MarketplaceListing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing.downloads = (listing.downloads or 0) + 1
    await db.commit()
    return {"message": "Installed", "downloads": listing.downloads}


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MarketplaceListing.category, func.count(MarketplaceListing.id))
        .where(MarketplaceListing.is_published == True)
        .group_by(MarketplaceListing.category)
    )
    return [{"name": r[0], "count": r[1]} for r in result.all()]
