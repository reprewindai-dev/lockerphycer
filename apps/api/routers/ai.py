"""
AI Services Routes
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_
from typing import List, Optional, Dict, Any
from datetime import datetime

from core.database.database import get_db
from db.models import AIRequest, AIModel, User
from apps.api.routers.auth import get_current_user
from apps.api.schemas.ai import AIRequestResponse, AIModelResponse, AIAnalysisRequest, AIAnalysisResponse

router = APIRouter()


@router.get("/models", response_model=List[AIModelResponse])
async def list_ai_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List available AI models"""
    
    result = await db.execute(
        select(AIModel).where(AIModel.is_active == True)
    )
    models = result.scalars().all()
    
    return [AIModelResponse.from_orm(model) for model in models]


@router.get("/models/{model_id}", response_model=AIModelResponse)
async def get_ai_model(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get AI model details"""
    
    model = await db.get(AIModel, model_id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI model not found"
        )
    
    return AIModelResponse.from_orm(model)


@router.post("/analyze", response_model=AIAnalysisResponse)
async def analyze_with_ai(
    request: AIAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Analyze data using AI"""
    
    # Get model
    model = await db.get(AIModel, request.model_id)
    if not model or not model.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI model not found or inactive"
        )
    
    # Create AI request record
    ai_request = AIRequest(
        user_id=current_user.id,
        model_id=model.id,
        request_type=request.request_type,
        input_data=request.input_data
    )
    
    db.add(ai_request)
    await db.commit()
    await db.refresh(ai_request)
    
    try:
        # Process AI request (mock implementation)
        start_time = datetime.utcnow()
        
        # Mock AI processing
        analysis_result = await process_ai_analysis(request, model)
        
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Update request with results
        ai_request.output_data = analysis_result
        ai_request.processing_time = processing_time
        ai_request.confidence_score = analysis_result.get("confidence", 0.0)
        ai_request.status = "completed"
        ai_request.completed_at = datetime.utcnow()
        
        await db.commit()
        
        return AIAnalysisResponse(
            request_id=ai_request.id,
            model_id=model.id,
            model_name=model.name,
            analysis=analysis_result,
            confidence=analysis_result.get("confidence", 0.0),
            processing_time=processing_time,
            timestamp=datetime.utcnow()
        )
        
    except Exception as e:
        ai_request.status = "failed"
        ai_request.error_message = str(e)
        await db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI processing failed: {str(e)}"
        )


@router.get("/requests", response_model=List[AIRequestResponse])
async def list_ai_requests(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List AI requests for current user"""
    
    result = await db.execute(
        select(AIRequest)
        .where(AIRequest.user_id == current_user.id)
        .order_by(desc(AIRequest.created_at))
        .offset(skip)
        .limit(limit)
    )
    requests = result.scalars().all()
    
    return [AIRequestResponse.from_orm(req) for req in requests]


@router.get("/requests/{request_id}", response_model=AIRequestResponse)
async def get_ai_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get AI request details"""
    
    request = await db.get(AIRequest, request_id)
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI request not found"
        )
    
    # Check ownership
    if request.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    return AIRequestResponse.from_orm(request)


@router.post("/models/upload")
async def upload_ai_model(
    name: str,
    model_type: str,
    version: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload new AI model"""
    
    # Check user permissions
    if current_user.role.value not in ["admin", "ai_operator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to upload models"
        )
    
    # Save model file (mock implementation)
    file_path = f"/app/models/{file.filename}"
    
    # Create model record
    model = AIModel(
        name=name,
        model_type=model_type,
        version=version,
        config={"file_path": file_path},
        is_active=False  # Needs to be activated manually
    )
    
    db.add(model)
    await db.commit()
    await db.refresh(model)
    
    return {"message": "Model uploaded successfully", "model_id": model.id}


@router.post("/models/{model_id}/activate")
async def activate_ai_model(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Activate AI model"""
    
    # Check user permissions
    if current_user.role.value not in ["admin", "ai_operator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to activate models"
        )
    
    model = await db.get(AIModel, model_id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI model not found"
        )
    
    # Deactivate other models of the same type
    await db.execute(
        select(AIModel).where(AIModel.model_type == model.model_type)
    ).update({"is_active": False})
    
    # Activate this model
    model.is_active = True
    model.is_loaded = True
    model.updated_at = datetime.utcnow()
    
    await db.commit()
    
    return {"message": "Model activated successfully"}


@router.get("/stats")
async def get_ai_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get AI service statistics"""
    
    # Total requests today
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    
    total_requests_result = await db.execute(
        select(func.count(AIRequest.id)).select_from(AIRequest)
        .where(AIRequest.created_at >= today_start)
    )
    total_requests = total_requests_result.scalar()
    
    # Successful requests
    successful_requests_result = await db.execute(
        select(func.count(AIRequest.id)).select_from(AIRequest)
        .where(
            and_(
                AIRequest.created_at >= today_start,
                AIRequest.status == "completed"
            )
        )
    )
    successful_requests = successful_requests_result.scalar()
    
    # Active models
    active_models_result = await db.execute(
        select(func.count(AIModel.id)).select_from(AIModel)
        .where(AIModel.is_active == True)
    )
    active_models = active_models_result.scalar()
    
    return {
        "total_requests_today": total_requests,
        "successful_requests_today": successful_requests,
        "success_rate": (successful_requests / total_requests * 100) if total_requests > 0 else 0,
        "active_models": active_models,
        "avg_processing_time": await get_avg_processing_time(db, today_start)
    }


async def process_ai_analysis(request: AIAnalysisRequest, model: AIModel) -> Dict[str, Any]:
    """Process AI analysis (mock implementation)"""
    
    # Mock AI processing based on request type
    if request.request_type == "threat_analysis":
        return {
            "threat_level": "medium",
            "confidence": 0.85,
            "recommendations": [
                "Implement additional monitoring",
                "Review access logs",
                "Update security policies"
            ],
            "analysis": "Potential security risk detected in user behavior patterns"
        }
    elif request.request_type == "anomaly_detection":
        return {
            "is_anomaly": True,
            "confidence": 0.92,
            "anomaly_type": "unusual_access_pattern",
            "severity": "low",
            "details": "User accessed unusual endpoints at odd hours"
        }
    elif request.request_type == "sentiment_analysis":
        return {
            "sentiment": "neutral",
            "confidence": 0.78,
            "emotions": {
                "positive": 0.3,
                "negative": 0.2,
                "neutral": 0.5
            }
        }
    else:
        return {
            "result": "processed",
            "confidence": 0.75,
            "metadata": {
                "model": model.name,
                "version": model.version
            }
        }


async def get_avg_processing_time(db: AsyncSession, start_date: datetime) -> float:
    """Get average processing time for completed requests"""
    
    result = await db.execute(
        select(func.avg(AIRequest.processing_time))
        .select_from(AIRequest)
        .where(
            and_(
                AIRequest.created_at >= start_date,
                AIRequest.status == "completed"
            )
        )
    )
    avg_time = result.scalar()
    return avg_time or 0.0
