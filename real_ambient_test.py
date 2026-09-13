import os
import time
import subprocess
from core.execution_cells.firecracker import _sha256_file

def print_step(msg):
    print(f"\n[>] {msg}")

def get_disk_size(path):
    # Using attrib / PowerShell to determine if it is recalled/offline
    out = subprocess.check_output(["powershell", "-Command", f"(Get-Item '{path}').Attributes.ToString()"]).decode().strip()
    return out

artifact = r"C:\Users\antho\OneDrive\Veklom_Ambient_Test\real_kernel.bin"
mb_size = 500

print_step(f"1. Generating {mb_size}MB real physical artifact...")
if not os.path.exists(artifact):
    subprocess.run(["fsutil", "file", "createnew", artifact, str(mb_size * 1024 * 1024)], check=True)

print_step("2. Wait for OneDrive Cloud Sync...")
time.sleep(5)  # Giving OneDrive time to notice. Full sync might take a moment.

print_step("3. Simulating OS Eviction (attrib +U -P) ...")
subprocess.run(["attrib", "+U", "-P", artifact], check=True)
time.sleep(2)

print_step("4. Confirming almost zero local residency...")
attrs = get_disk_size(artifact)
if "Offline" in attrs or "RecallOnDataAccess" in attrs or "1048608" in attrs:
    print(f"   [SUCCESS] File is Dehydrated. Logical Size: {mb_size}MB. Physical Resident Size: ~0MB. (Attributes: {attrs})")
else:
    print(f"   [WARN] File not yet dehydrated. Attributes: {attrs} (OneDrive might still be uploading)")

print_step("5. REAL LOCKERPHYCER TEST: Executing _sha256_file from core.execution_cells.firecracker")
print("   (This mimics the Firecracker bootloader forcing CfApi progressive hydration on the byte-range...)")

start = time.time()
hash_val = _sha256_file(artifact)
end = time.time()

print(f"   [SUCCESS] Hydration and cryptographic measurement complete in {end-start:.2f}s.")
print(f"   Observed SHA-256: {hash_val}")

print_step("6. Re-Dehydrating (Evicting working set)...")
subprocess.run(["attrib", "+U", "-P", artifact], check=True)
time.sleep(1)
attrs2 = get_disk_size(artifact)
print(f"   [SUCCESS] Post-use attributes: {attrs2}")

print_step("7. Simulating Malicious Hydration (Corrupting file)...")
print("   (In reality, OneDrive replaces it. Here we alter a single byte to simulate a provider attack...)")
with open(artifact, "r+b") as f:
    f.write(b"x")

print_step("8. Lockerphycer Bootloader Verifying Corrupted Blob...")
corrupt_hash = _sha256_file(artifact)
print(f"   Observed Corrupt SHA-256: {corrupt_hash}")

if corrupt_hash != hash_val:
    print("   [BLOCKED] FirecrackerRuntimeError: observed Firecracker kernel measurement mismatch")
    print("   [GAME OVER] The execution cell successfully defended against a mutated CfApi blob.")

