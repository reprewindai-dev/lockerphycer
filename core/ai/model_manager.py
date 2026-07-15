"""AI model health placeholder backed by explicit configured state."""


async def get_model_status() -> dict:
    return {"status": "configured", "models_loaded": 0}
