from apps.api.routers.health_dependencies import _external_http_state, _result


def test_external_http_success_is_reachability_only() -> None:
    assert _external_http_state(200) == "reachable_not_verified"
    assert _external_http_state(204) == "reachable_not_verified"
    assert _external_http_state(404) == "degraded"
    assert _external_http_state(500) == "degraded"


def test_public_dependency_result_does_not_expose_topology_or_latency() -> None:
    result = _result("capi", "reachable_not_verified", "HTTP_REACHABILITY_ONLY")

    assert result == {
        "name": "capi",
        "state": "reachable_not_verified",
        "verification_scope": "HTTP_REACHABILITY_ONLY",
    }
    assert "host" not in result
    assert "url" not in result
    assert "latency_ms" not in result
    assert "healthy" not in result.values()
