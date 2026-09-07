from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AI_ROUTER = ROOT / "apps" / "api" / "routers" / "ai.py"
AI_SCHEMA = ROOT / "apps" / "api" / "schemas" / "ai.py"
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

    upload_response = source.split("await db.refresh(model)", 1)[1].split(
        '@router.post("/models/{model_id}/activate")', 1
    )[0]
    assert '"file_path"' not in upload_response
    assert 'return {"message": "Model uploaded successfully", "model_id": model.id}' in upload_response
    assert 'detail="AI processing unavailable"' in source
    assert 'detail="Failed to persist model file"' in source


def test_public_model_schema_does_not_include_internal_config() -> None:
    schema = AI_SCHEMA.read_text(encoding="utf-8")
    response_block = schema.split("class AIModelResponse", 1)[1].split("class AIRequestBase", 1)[0]
    assert "config:" not in response_block
    assert "provider/runtime configuration is intentionally excluded" in response_block.lower()


def test_legacy_provider_errors_are_sanitized_at_response_boundary() -> None:
    source = _source()
    assert "def _public_request(" in source
    assert "response.error_message = _SAFE_ERROR" in source
    assert "return [_public_request(req)" in source
    assert "return _public_request(request)" in source


def test_ai_router_retains_sanitized_operator_failure_classes() -> None:
    source = _source()
    assert '"failure_code": exc.code' in source
    assert 'raise AIProviderError("OLLAMA_TIMEOUT")' in source
    assert 'raise AIProviderError("OLLAMA_TRANSPORT_ERROR")' in source
    assert 'raise AIProviderError("OLLAMA_INVALID_RESPONSE")' in source
    assert 'logger.exception(' not in source


def test_database_persistence_is_not_misclassified_as_provider_failure() -> None:
    source = _source()
    provider_try = source.split("try:\n        analysis_result = await process_ai_analysis", 1)[1].split(
        "except AIProviderError as exc:", 1
    )[0]
    assert "await db.commit()" not in provider_try
    assert "except AIProviderError as exc:" in source


def test_upload_directory_creation_is_inside_sanitized_io_boundary() -> None:
    source = _source()
    guarded = source.split("max_size = 5 * 1024 * 1024", 1)[1].split("model = AIModel(", 1)[0]
    assert "try:" in guarded
    assert "os.makedirs(base_dir, exist_ok=True)" in guarded
    assert "except OSError as exc:" in guarded


def test_ai_router_fails_closed_when_ollama_is_unconfigured() -> None:
    source = _source()
    assert "if not OLLAMA_BASE_URL:" in source
    assert 'raise AIProviderError("OLLAMA_NOT_CONFIGURED")' in source


def test_required_ollama_endpoint_is_documented_without_topology() -> None:
    env = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "OLLAMA_BASE_URL=" in env
    assert "167.233.202.195" not in env
