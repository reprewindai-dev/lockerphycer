"""
AI Services Routes

All AI analysis is delegated to a deployment-configured Ollama endpoint. There is
no mock fallback — if Ollama is unconfigured, unreachable, or returns an error,
the request fails closed with HTTP 503 without exposing provider topology.
"""

import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_, func, update
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import aiofiles

from core.database.database import get_db
from db.models import AIRequest, AIModel, User
from core.security.auth import get_current_user
from apps.api.schemas.ai import AIRequestResponse, AIModelResponse, AIAnalysisRequest, AIAnalysisResponse

router = APIRouter()
logger = logging.getLogger("lockerphycer.ai")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "").rstrip("/")
MODEL_UPLOAD_DIR = os.environ.get("MODEL_UPLOAD_DIR", "/app/models")


class AIProviderError(RuntimeError):
    """Sanitized provider failure that is safe to classify in internal logs."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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
    """Analyze data using AI via the configured Ollama inference node"""

    model = await db.get(AIModel, request.model_id)
    if not model or not model.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI model not found or inactive"
        )

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
        start_time = datetime.utcnow()
        analysis_result = await process_ai_analysis(request, model)
        processing_time = (datetime.utcnow() - start_time).total_seconds()

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

    except Exception as exc:
        failure_code = exc.code if isinstance(exc, AIProviderError) else exc.__class__.__name__
        # Keep caller/persisted errors topology-free while retaining an operator-useful
        # failure class. Deliberately do not log str(exc) or exc_info because provider
        # exceptions may contain deployment URLs or response bodies.
        logger.error(
            "AI provider analysis failed",
            extra={
                "provider": "ollama",
                "failure_code": failure_code,
                "model_id": str(model.id),
                "request_type": request.request_type,
            },
        )
        ai_request.status = "failed"
        ai_request.error_message = "AI_PROVIDER_UNAVAILABLE"
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI processing unavailable"
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
    """Upload new AI model — binary is persisted to MODEL_UPLOAD_DIR with strict boundary checks"""

    if current_user.role.value not in ["admin", "ai_operator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to upload models"
        )

    allowed_extensions = {".bin", ".gguf", ".pt", ".pth", ".safetensors", ".onnx"}
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ""
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid model extension {ext}. Allowed: {', '.join(allowed_extensions)}"
        )

    import uuid
    server_filename = f"{uuid.uuid4().hex}{ext}"

    os.makedirs(MODEL_UPLOAD_DIR, exist_ok=True)

    base_dir = os.path.abspath(MODEL_UPLOAD_DIR)
    file_path = os.path.abspath(os.path.join(base_dir, server_filename))

    if os.path.commonpath([base_dir, file_path]) != base_dir:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path resolution failed security boundaries"
        )

    MAX_SIZE = 5 * 1024 * 1024
    total_size = 0

    try:
        async with aiofiles.open(file_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > MAX_SIZE:
                    os.remove(file_path)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Model file exceeds 5MB limit"
                    )
                await f.write(chunk)
        os.chmod(file_path, 0o600)
    except OSError:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist model file"
        )

    model = AIModel(
        name=name,
        model_type=model_type,
        version=version,
        config={"file_path": file_path},
        is_active=False
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

    await db.execute(
        update(AIModel)
        .where(AIModel.model_type == model.model_type)
        .values(is_active=False)
    )

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

    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())

    total_requests_result = await db.execute(
        select(func.count(AIRequest.id)).select_from(AIRequest)
        .where(AIRequest.created_at >= today_start)
    )
    total_requests = total_requests_result.scalar()

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
    """Delegate AI analysis to the deployment-configured Ollama inference node."""
    if not OLLAMA_BASE_URL:
        raise AIProviderError("OLLAMA_NOT_CONFIGURED")

    ollama_model = model.config.get("ollama_model", "llama3")

    system_prompt_map = {
        "threat_analysis": (
            "You are a security analyst. Analyze the following data for threats and risks. "
            "Respond in JSON with keys: threat_level (low/medium/high/critical), confidence (0.0-1.0), "
            "recommendations (list of strings), analysis (string)."
        ),
        "anomaly_detection": (
            "You are an anomaly detection system. Analyze the following data for anomalies. "
            "Respond in JSON with keys: is_anomaly (bool), confidence (0.0-1.0), "
            "anomaly_type (string or null), severity (low/medium/high/critical or null), details (string)."
        ),
        "sentiment_analysis": (
            "You are a sentiment analysis engine. Analyze the sentiment of the following text. "
            "Respond in JSON with keys: sentiment (positive/negative/neutral), confidence (0.0-1.0), "
            "emotions (object with positive, negative, neutral float values summing to 1.0)."
        ),
    }

    system_prompt = system_prompt_map.get(
        request.request_type,
        "You are an AI analysis assistant. Analyze the following data and respond in JSON."
    )

    payload = {
        "model": ollama_model,
        "prompt": f"{system_prompt}\n\nData:\n{request.input_data}",
        "stream": False,
        "format": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
    except httpx.TimeoutException as exc:
        raise AIProviderError("OLLAMA_TIMEOUT") from exc
    except httpx.HTTPError as exc:
        raise AIProviderError("OLLAMA_TRANSPORT_ERROR") from exc

    if resp.status_code != 200:
        raise AIProviderError(f"OLLAMA_HTTP_{resp.status_code}")

    try:
        ollama_response = resp.json()
    except ValueError as exc:
        raise AIProviderError("OLLAMA_INVALID_RESPONSE") from exc
    raw_text = ollama_response.get("response", "")

    import json as _json
    try:
        result = _json.loads(raw_text)
    except _json.JSONDecodeError:
        result = {"result": raw_text, "confidence": 0.0, "model": ollama_model, "parse_error": True}

    return result


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
