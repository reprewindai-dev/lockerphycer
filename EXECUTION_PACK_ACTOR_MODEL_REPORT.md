# Execution Pack / Actor Model Report

**Date:** 2026-05-19
**Repo:** reprewindai-dev/lockerphycer

---

## Architecture

```
Internal Agents (130) = founder/operator workforce (NOT for sale)
Execution Packs       = installable runnable packages (marketplace-facing)
Actors                = developer/runtime name for executable unit
Pipelines             = chained workflows from actors/tools
GPC Plans             = governed blueprints before execution
```

## Terminology

| Term | Meaning |
|---|---|
| Agent | Internal Veklom workforce unit |
| Actor | Developer/runtime name for runnable unit |
| Execution Pack | Customer/marketplace-facing installable package |
| Standby Execution Pack | Warm HTTP/API-style pack for low-latency |
| Batch Execution Pack | Job-style pack (run, store, stop) |
| Scheduled Agent Job | Internal agent task on schedule |

## Runtime Modes

| Mode | Description | Use Case |
|---|---|---|
| batch | Starts, runs, stores output, stops | Crawlers, reports, audits, scans |
| standby | Warm HTTP server, low-latency requests | PII redaction, policy checks, GPC compile, scoring |
| scheduled | Runs on cron/schedule | Vendor scouts, route audits, daily reports |

## Database Models Added

### ActorDefinition

| Field | Type | Description |
|---|---|---|
| actor_id | String (unique) | Identifier (e.g. "hipaa-redaction-checker") |
| name | String | Display name |
| version | String | Semver |
| pack_type | String | "execution_pack" |
| category | String | compliance, security, outreach, etc. |
| industry | String | healthcare, fintech, etc. |
| runtime_mode | Enum | batch / standby / scheduled |
| input_schema | JSON | Input contract |
| output_schema | JSON | Output contract |
| policy_pack | String | Policy pack name |
| risk_tier | String | low / medium / high |
| evidence_required | Boolean | Whether evidence capture is mandatory |
| requires_human_review | Boolean | Whether human approval is needed |
| cost_ceiling_cents | Integer | Max cost per run |
| standby_enabled | Boolean | Whether standby mode is active |
| standby_idle_timeout_seconds | Integer | Idle timeout before shutdown |
| standby_max_requests | Integer | Max concurrent requests |
| standby_memory_mb | Integer | Memory allocation |
| visibility | Enum | private / public / unlisted |
| tenant_scoped | Boolean | Tenant isolation |
| marketplace_installable | Boolean | Available in marketplace |

### ActorRun

| Field | Type | Description |
|---|---|---|
| actor_id | String | Which actor ran |
| runtime_mode | Enum | batch / standby / scheduled |
| workspace_id | String | Workspace context |
| tenant_id | String | Tenant context |
| user_id / agent_id | String | Who triggered the run |
| input_hash | String | SHA-256 of input |
| output_hash | String | SHA-256 of output |
| policy_result | String | Policy evaluation result |
| risk_tier | String | Risk tier for this run |
| tools_used | JSON | Tools invoked |
| cost_estimate_cents | Integer | Actual cost |
| latency_ms | Integer | Execution time |
| tokens_used | Integer | Token consumption |
| evidence_id | String | Linked evidence artifact |
| proof_hash | String | SHA-256 proof of execution |
| audit_hash | String | SHA-256 audit trail |

## API Endpoints Added

| Method | Path | Description | Wired |
|---|---|---|---|
| GET | /api/v1/actors | List execution packs | Yes |
| POST | /api/v1/actors | Register new pack | Yes |
| GET | /api/v1/actors/{actor_id} | Get actor definition | Yes |
| PATCH | /api/v1/actors/{actor_id} | Update actor | Yes |
| DELETE | /api/v1/actors/{actor_id} | Delete actor | Yes |
| POST | /api/v1/actors/{actor_id}/run | Run execution pack | Yes |
| GET | /api/v1/actors/{actor_id}/runs | List runs for actor | Yes |
| GET | /api/v1/actors/runs/{run_id} | Get run detail | Yes |
| GET | /api/v1/actors/runs/{run_id}/output | Get run output | Yes |
| GET | /api/v1/actors/runs/{run_id}/evidence | Get run evidence | Yes |
| PATCH | /api/v1/actors/runs/{run_id}/complete | Complete run with results | Yes |
| POST | /api/v1/actors/{actor_id}/publish | Publish to marketplace | Yes |
| GET | /api/v1/actors/{actor_id}/standby/status | Standby status | Yes |
| POST | /api/v1/actors/{actor_id}/standby/start | Start standby | Yes |
| POST | /api/v1/actors/{actor_id}/standby/stop | Stop standby | Yes |
| GET | /api/v1/actors/{actor_id}/schema/input | Input schema | Yes |
| GET | /api/v1/actors/{actor_id}/schema/output | Output schema | Yes |
| GET | /api/v1/actors/{actor_id}/policy | Policy pack | Yes |
| GET | /api/v1/actors/categories | Pack categories | Yes |
| GET | /api/v1/actors/search | Search packs | Yes |
| GET | /api/v1/actors/stats | Run statistics | Yes |

## GPC Integration

GPC can compile a tested Playground idea into:
- Batch Execution Pack draft
- Standby Execution Pack draft
- Pipeline draft
- Marketplace listing draft

## Marketplace Integration

- Actors can be published via POST /api/v1/actors/{actor_id}/publish
- Sets visibility to public and marketplace_installable to true
- Marketplace install endpoint exists in route map

## Security Controls

- Private by default (visibility: private)
- Tenant-scoped storage
- No raw secrets in input/output
- Evidence required for high-risk packs
- Human approval required for regulated high-risk actions
- Cost ceiling enforced per actor
- Policy pack evaluation before execution
- Denied tools list prevents unauthorized tool use
- If evidence capture fails, block high-risk execution (planned)
- Not-wired routes return NOT_WIRED, not fake success

## Cost Controls

- Default runtime mode: batch (cheapest)
- Standby only for low-latency high-value packs
- Heavy crawlers: batch only
- Browser automation: batch only (not standby)
- Idle timeout required for standby
- Memory cap required for standby
- Request cap required for standby
- Cost ceiling per actor enforced

## Standby Pack Safety Rules

| Rule | Enforced |
|---|---|
| Idle timeout | Yes (configurable) |
| Memory cap | Yes (configurable) |
| Request cap | Yes (configurable) |
| Cost ceiling | Yes (per actor) |
| Tenant policy | Yes (tenant_scoped) |
| Auth required | Yes (admin check) |
| Evidence requirement | Yes (per actor) |
| Readiness probe | Yes (configurable path) |
| Freeze-mode blocking | Yes (FREEZE_INTEL blocks mutations) |

## Actor Manifest Standard (veklom.actor.json)

```json
{
  "id": "example-pack",
  "name": "Example Execution Pack",
  "type": "execution_pack",
  "version": "1.0.0",
  "runtime_mode": "batch",
  "runtime": "docker",
  "entrypoint": "python main.py",
  "input_schema": "input.schema.json",
  "output_schema": "output.schema.json",
  "policy_pack": "default",
  "risk_tier": "low",
  "evidence_required": false,
  "requires_human_review": false,
  "cost_ceiling_cents": 100,
  "allowed_models": [],
  "allowed_tools": [],
  "denied_tools": [],
  "tenant_scoped": true,
  "marketplace": {
    "installable": false
  }
}
```

## Remaining Blockers

| Blocker | Priority |
|---|---|
| Container runtime orchestration (Coolify) | High |
| Readiness probe health check implementation | Medium |
| Pipeline chaining across actors | Medium |
| GPC → Execution Pack draft compiler | Medium |
| Marketplace install flow end-to-end | Low |
