class CellRuntimeError(Exception):
    pass

def _require_runtime_artifact_binding(request) -> None:
    envelope = request.authority.envelope
    if envelope.runtime_image_digest is None:
        raise CellRuntimeError("signed authority is missing runtime_image_digest")
    if '@sha256:' not in request.image:
        raise CellRuntimeError("cell image must be pinned by immutable sha256 digest")
    requested_digest = request.image.rsplit('@', 1)[1].lower()
    if requested_digest != envelope.runtime_image_digest:
        raise CellRuntimeError("requested runtime image does not match CAPPO-signed authority")
    if envelope.required_isolation == 'microvm' and envelope.runtime_kernel_digest is None:
        raise CellRuntimeError("microVM authority is missing runtime_kernel_digest")

class MockEnvelope:
    def __init__(self, required_isolation="microvm", runtime_image_digest="sha256:abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234", runtime_kernel_digest="sha256:1111111111111111111111111111111111111111111111111111111111111111"):
        self.required_isolation = required_isolation
        self.runtime_image_digest = runtime_image_digest
        self.runtime_kernel_digest = runtime_kernel_digest

class MockAuthority:
    def __init__(self):
        self.envelope = MockEnvelope()

class MockRequest:
    def __init__(self, image: str):
        self.authority = MockAuthority()
        self.image = image

print("Executing test: Valid Hydration (Digest matches PGL Receipt)...")
try:
    valid_req = MockRequest(image="registry.local/image@sha256:abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234")
    _require_runtime_artifact_binding(valid_req)
    print("SUCCESS: Valid hydration accepted.")
except Exception as e:
    print(f"FAILED: {e}")

print("\nExecuting test: Malicious Hydration (OneDrive altered the blob)...")
try:
    # Malicious provider hydrates a file but it's the wrong digest
    malicious_req = MockRequest(image="registry.local/image@sha256:deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    _require_runtime_artifact_binding(malicious_req)
    print("SUCCESS: Valid hydration accepted.")
except Exception as e:
    print(f"BLOCKED: {type(e).__name__}: {e}")
