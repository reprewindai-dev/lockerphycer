# AGENTS.md — READ FIRST

Before any work, read [`00_VEKLOM_BIBLE.md`](./00_VEKLOM_BIBLE.md).

That file is the canonical Veklom cross-repo architecture/runtime contract. Repo-local source and tests govern Lockerphycer implementation details only when they do not conflict with current runtime evidence or the Bible.

Do not claim HSM/TEE/hardware-enclave guarantees, “secrets never enter software memory,” or compliance certification unless the exact deployed implementation and external evidence prove those claims.

Use Coolify UI/API/MCP for Coolify management; SSH is for direct host/container verification or operations. Host port `8000` is currently Coolify-owned even though internal Docker port `8000` can be used behind Traefik.
