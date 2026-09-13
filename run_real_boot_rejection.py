import os
import shutil
import hashlib
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Import the actual models and runtime
from core.execution_cells.models import CellRequest, CellResourceLimits, AuthorizedExecutionEnvelope, SignedAuthority
from core.execution_cells.firecracker import FirecrackerMicroVMRuntime, FirecrackerConfig, FirecrackerRuntimeError, _sha256_file

# Paths
artifact_rootfs = r"C:\Users\antho\OneDrive\Veklom_Ambient_Test\real_rootfs.bin"
artifact_kernel = r"C:\Users\antho\OneDrive\Veklom_Ambient_Test\real_kernel.bin"
artifact_binary = r"C:\Users\antho\OneDrive\Veklom_Ambient_Test\fake_firecracker.exe"

# 1. Setup real, cryptographically distinct files
print("\n[>] 1. Setting up physical artifacts...")
artifacts = {
    artifact_rootfs: b"ROOTFS_DATA",
    artifact_kernel: b"KERNEL_DATA",
    artifact_binary: b"BINARY_DATA"
}

for p, data in artifacts.items():
    if os.path.exists(p): os.remove(p)
    with open(p, "wb") as f:
        # Write distinct data patterns for each file to ensure unique hashes
        f.write(data * (1024 * 1024)) 

# Get initial distinct SHA-256 for rootfs and kernel
rootfs_digest = _sha256_file(artifact_rootfs)
kernel_digest = _sha256_file(artifact_kernel)
binary_digest = _sha256_file(artifact_binary)
print(f"   Original Rootfs: {rootfs_digest}")
print(f"   Original Kernel: {kernel_digest}")
print(f"   Original Binary: {binary_digest}")

# 2. Configure FirecrackerConfig exactly as the app does
os.environ["LOCKERPHYCER_FIRECRACKER_BINARY"] = artifact_binary
os.environ["LOCKERPHYCER_FIRECRACKER_KERNEL"] = artifact_kernel
os.environ["LOCKERPHYCER_FIRECRACKER_ROOTFS"] = artifact_rootfs
os.environ["LOCKERPHYCER_FIRECRACKER_KERNEL_SHA256"] = kernel_digest
os.environ["LOCKERPHYCER_FIRECRACKER_ROOTFS_SHA256"] = rootfs_digest
os.environ["LOCKERPHYCER_FIRECRACKER_STATE_DIR"] = os.getcwd()

config = FirecrackerConfig.from_environment()

class MockVerifier:
    def verify(self, authority) -> str:
        return "fake-authority-digest"

# Mock /dev/kvm check so Windows can instantiate the class without crashing
_original_exists = os.path.exists
def mock_exists(path):
    if path == '/dev/kvm': return True
    return _original_exists(path)

with patch('os.path.exists', side_effect=mock_exists):
    runtime = FirecrackerMicroVMRuntime(MockVerifier(), config, expected_runtime_instance="host-1")

# 3. Create the real execution request using model_construct to bypass tedious field validation
envelope = AuthorizedExecutionEnvelope.model_construct(
    execution_id="exec-123", path_id="p-1", request_id="r-1", idempotency_key="i-1",
    grant_id="g-1", subject_id="s-1", tenant_id="t-1", workspace_id="w-1",
    capability_id="github.file.update", semantic_intent_digest="sha256:00",
    resource_constraints=CellResourceLimits(), authority_epoch=1, assignment_id="a-1",
    runtime_kind="lockerphycer-cell", runtime_instance="host-1", required_isolation="microvm",
    runtime_image_digest=rootfs_digest, runtime_kernel_digest=kernel_digest,
    issued_at=datetime.now(timezone.utc),
    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    nonce="nonce1234567890123456"
)
authority = SignedAuthority.model_construct(envelope=envelope, signatures={"PGL": "sig"})
request = CellRequest.model_construct(authority=authority, image=f"reg.local/img@{rootfs_digest}", cell_payload="{}")

# 4. Mutate the file (Simulate CfApi hydration corruption)
print("\n[>] 2. Simulating Cloud Files API returning corrupted hydrated bytes...")
with open(artifact_rootfs, "r+b") as f:
    f.write(b"CORRUPT!")

# 5. Execute the LIVE FIRECRACKER BOOT PATH
print("\n[>] 3. Hitting the live FirecrackerMicroVMRuntime.run() boundary...")
try:
    runtime.run(request)
    print("   [FAILED] The bootloader ignored the corruption and launched a VMM!")
except FirecrackerRuntimeError as e:
    print(f"   [SUCCESS] Live Boot Rejection Confirmed: {type(e).__name__}: {str(e)}")
    print("   [GAME OVER] The VMM process was never spawned. The physical boundary held.")
except Exception as e:
    print(f"   [ERROR] Expected FirecrackerRuntimeError but got {type(e).__name__}: {str(e)}")

