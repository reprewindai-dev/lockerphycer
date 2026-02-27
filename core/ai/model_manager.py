"""
AI Model Manager
"""

from typing import Dict, Any, Optional, List
import torch
from transformers import AutoTokenizer, AutoModel
import logging
from datetime import datetime

from core.config.settings import settings
from core.utils.redis_client import redis_client

logger = logging.getLogger(__name__)


class ModelManager:
    """AI Model Manager"""
    
    def __init__(self):
        self.models: Dict[str, Any] = {}
        self.tokenizers: Dict[str, Any] = {}
        self.model_configs: Dict[str, Dict[str, Any]] = {}
    
    async def load_model(self, model_name: str, model_path: Optional[str] = None) -> bool:
        """Load AI model"""
        try:
            if model_name in self.models:
                logger.info(f"Model {model_name} already loaded")
                return True
            
            # Load tokenizer
            tokenizer = AutoTokenizer.from_pretrained(
                model_path or model_name,
                cache_dir=settings.MODEL_CACHE_DIR
            )
            
            # Load model
            model = AutoModel.from_pretrained(
                model_path or model_name,
                cache_dir=settings.MODEL_CACHE_DIR
            )
            
            # Move to GPU if available
            if torch.cuda.is_available():
                model = model.cuda()
            
            self.models[model_name] = model
            self.tokenizers[model_name] = tokenizer
            
            # Cache model info
            model_info = {
                "name": model_name,
                "loaded_at": datetime.utcnow().isoformat(),
                "device": "cuda" if torch.cuda.is_available() else "cpu",
                "parameters": sum(p.numel() for p in model.parameters())
            }
            
            await redis_client.set_json(f"model:{model_name}", model_info)
            
            logger.info(f"Model {model_name} loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load model {model_name}: {e}")
            return False
    
    async def unload_model(self, model_name: str) -> bool:
        """Unload AI model"""
        try:
            if model_name in self.models:
                del self.models[model_name]
                del self.tokenizers[model_name]
                
                # Remove from cache
                await redis_client.delete(f"model:{model_name}")
                
                logger.info(f"Model {model_name} unloaded successfully")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to unload model {model_name}: {e}")
            return False
    
    async def predict(self, model_name: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Make prediction with model"""
        try:
            if model_name not in self.models:
                raise ValueError(f"Model {model_name} not loaded")
            
            model = self.models[model_name]
            tokenizer = self.tokenizers[model_name]
            
            # Tokenize input
            if "text" in inputs:
                tokens = tokenizer(
                    inputs["text"],
                    return_tensors="pt",
                    truncation=True,
                    padding=True
                )
                
                # Move to GPU if available
                if torch.cuda.is_available():
                    tokens = {k: v.cuda() for k, v in tokens.items()}
                
                # Get model output
                with torch.no_grad():
                    outputs = model(**tokens)
                
                # Process output
                predictions = outputs.last_hidden_state.mean(dim=1).cpu().numpy()
                
                return {
                    "predictions": predictions.tolist(),
                    "confidence": 0.85,  # Mock confidence
                    "model": model_name
                }
            
            return {"error": "Invalid input format"}
            
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return {"error": str(e)}
    
    async def get_model_status(self) -> Dict[str, Any]:
        """Get model status"""
        loaded_models = list(self.models.keys())
        
        return {
            "loaded_models": loaded_models,
            "total_models": len(loaded_models),
            "gpu_available": torch.cuda.is_available(),
            "gpu_memory_used": torch.cuda.memory_allocated() if torch.cuda.is_available() else 0,
            "timestamp": datetime.utcnow().isoformat()
        }


# Global model manager instance
model_manager = ModelManager()


async def get_model_status() -> Dict[str, Any]:
    """Get model manager status"""
    return await model_manager.get_model_status()


async def initialize_default_models():
    """Initialize default AI models"""
    default_models = [
        "bert-base-uncased",
        "distilbert-base-uncased"
    ]
    
    for model_name in default_models:
        await model_manager.load_model(model_name)
