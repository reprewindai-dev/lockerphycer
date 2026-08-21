from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AI_ROUTER = ROOT / "apps" / "api" / "routers" / "ai.py"
ENV_EXAMPLE = ROOT / ".env.example"


def _source() -> str:
    return AI_ROUTER.read_text(encoding="utf-8")


def test_ai_router_has_no_concrete_ollama_host() -> None:
    source = _source()
    assert "167.233.202.195" not in source
    assert 'os.environ.get("OLLAMA_BASE_URL", "")' in source


def test_ai_router_does_not_return_raw_internal_errors_or_upload_paths() -> None:
    source = _source()
    assert 'detail=f"AI processing failed: {str(e)}"' not in source
    assert 'detail=f"Failed to persist model file: {exc}"' not in source
    assert 'return {"message": "Model uploaded successfully", "model_id": model.id, "file_path": file_path}' not in source
    assert 'return {"message": "Model uploaded successfully", "model_id": model.id}' in source
    assert 'detail="AI processing unavailable"' in source
    assert 'detail="Failed to persist model file"' in source


def test_ai_router_retains_sanitized_operator_failure_classes() -> None:
    source = _source()
    assert 'logger.error(' in source
    assert '"failure_code": failure_code' in source
    assert 'raise AIProviderError("OLLAMA_TIMEOUT")' in source
    assert 'raise AIProviderError("OLLAMA_TRANSPORT_ERROR")' in source
    assert 'raise AIProviderError("OLLAMA_INVALID_RESPONSE")' in source
    assert 'logger.exception(' not in source
    assert 'str(exc)' not in source


def test_ai_router_fails_closed_when_ollama_is_unconfigured() -> None:
    source = _source()
    assert "if not OLLAMA_BASE_URL:" in source
    assert 'raise AIProviderError("OLLAMA_NOT_CONFIGURED")' in source


def test_required_ollama_endpoint_is_documented_without_topology() -> None:
    env = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "OLLAMA_BASE_URL=" in env
    assert "167.233.202.195" not in env
