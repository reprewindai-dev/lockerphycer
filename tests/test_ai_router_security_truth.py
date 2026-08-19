from pathlib import Path


AI_ROUTER = Path(__file__).resolve().parents[1] / "apps" / "api" / "routers" / "ai.py"


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
    assert '"file_path": file_path}' not in source
    assert 'detail="AI processing unavailable"' in source
    assert 'detail="Failed to persist model file"' in source


def test_ai_router_fails_closed_when_ollama_is_unconfigured() -> None:
    source = _source()
    assert "if not OLLAMA_BASE_URL:" in source
    assert 'raise RuntimeError("OLLAMA_NOT_CONFIGURED")' in source
