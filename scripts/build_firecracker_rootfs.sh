#!/usr/bin/env bash
set -euo pipefail

# Build the minimal read-only rootfs used by the P0 Firecracker governed cell.
# Requirements on the build host:
#   cargo + rustup, x86_64-unknown-linux-musl target, busybox-static,
#   e2fsprogs, mount, and root privileges for the loop mount.
# The Linux kernel is intentionally NOT downloaded here; production selects and
# measures a separately controlled kernel artifact.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-${ROOT_DIR}/dist/firecracker}"
ROOTFS_MB="${LOCKERPHYCER_ROOTFS_MB:-64}"
TARGET="x86_64-unknown-linux-musl"
AGENT="${ROOT_DIR}/microvm_guest/target/${TARGET}/release/lockerphycer-cell-agent"
ROOTFS="${OUT_DIR}/lockerphycer-rootfs.ext4"
MOUNT_DIR="$(mktemp -d)"

cleanup() {
  if mountpoint -q "${MOUNT_DIR}"; then
    umount "${MOUNT_DIR}" || true
  fi
  rmdir "${MOUNT_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

mkdir -p "${OUT_DIR}"

rustup target add "${TARGET}" >/dev/null
cargo build \
  --manifest-path "${ROOT_DIR}/microvm_guest/Cargo.toml" \
  --release \
  --target "${TARGET}"

if [[ ! -x "${AGENT}" ]]; then
  echo "guest agent was not produced at ${AGENT}" >&2
  exit 1
fi

BUSYBOX="$(command -v busybox || true)"
if [[ -z "${BUSYBOX}" ]]; then
  echo "busybox-static is required" >&2
  exit 1
fi
if ldd "${BUSYBOX}" 2>&1 | grep -q '=>'; then
  echo "busybox must be statically linked (install busybox-static)" >&2
  exit 1
fi

rm -f "${ROOTFS}"
dd if=/dev/zero of="${ROOTFS}" bs=1M count="${ROOTFS_MB}" status=none
mkfs.ext4 -F -q "${ROOTFS}"
mount -o loop "${ROOTFS}" "${MOUNT_DIR}"

install -d -m 0755 \
  "${MOUNT_DIR}/bin" \
  "${MOUNT_DIR}/dev" \
  "${MOUNT_DIR}/proc" \
  "${MOUNT_DIR}/sys" \
  "${MOUNT_DIR}/tmp" \
  "${MOUNT_DIR}/usr/local/bin"
install -m 0755 "${BUSYBOX}" "${MOUNT_DIR}/bin/busybox"
install -m 0755 "${AGENT}" "${MOUNT_DIR}/usr/local/bin/lockerphycer-cell-agent"

for applet in sh mount umount poweroff reboot cat; do
  ln -sf /bin/busybox "${MOUNT_DIR}/bin/${applet}"
done

cat >"${MOUNT_DIR}/init" <<'INIT'
#!/bin/busybox sh
set -eu
/bin/mount -t proc proc /proc
/bin/mount -t sysfs sysfs /sys
/bin/mount -t devtmpfs devtmpfs /dev
PORT=5000
for arg in $(/bin/cat /proc/cmdline); do
  case "$arg" in
    veklom.vsock_port=*) PORT="${arg#*=}" ;;
  esac
done
export VEKLOM_VSOCK_PORT="$PORT"
/usr/local/bin/lockerphycer-cell-agent
status=$?
/bin/umount /proc || true
/bin/umount /sys || true
/bin/poweroff -f || true
exit "$status"
INIT
chmod 0755 "${MOUNT_DIR}/init"
sync
umount "${MOUNT_DIR}"

ROOTFS_SHA="$(sha256sum "${ROOTFS}" | awk '{print $1}')"
AGENT_SHA="$(sha256sum "${AGENT}" | awk '{print $1}')"
cat >"${OUT_DIR}/measurements.env" <<EOF
LOCKERPHYCER_FIRECRACKER_ROOTFS=${ROOTFS}
LOCKERPHYCER_FIRECRACKER_ROOTFS_SHA256=sha256:${ROOTFS_SHA}
LOCKERPHYCER_FIRECRACKER_GUEST_AGENT_SHA256=sha256:${AGENT_SHA}
EOF

echo "Built ${ROOTFS}"
echo "rootfs sha256:${ROOTFS_SHA}"
echo "guest agent sha256:${AGENT_SHA}"
