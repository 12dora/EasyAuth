# round4 codex 复核判定与修复对账

> 95 findings → 86 real / 6 refuted / 3 accepted-debt；修复 85 fixed + 1 disputed-already-fixed。

## ea-approvals-adr36
- 01 [real] Legacy manager fallback bypasses the frozen supervisor-chain policy
- 02 [real] Pool routing can rewrite an already-decided request
- 03 [real] Stale approver snapshots can silently discard concurrent reassignment
- 04 [real] Approval-rule replacement can overwrite concurrent rule edits
- 05 [real] One degraded submission writes the resolution audit event twice

## ea-beat-tasks
- 01 [real] Missing notify identity consumes the reminder permanently instead of retrying
- 02 [real] Daily reminder processing is permanently capped at 200 eligible tasks per run

## ea-console-api
- 01 [real] Manual async completion silently skips remaining batches
- 02 [real] Concurrent async-abandon calls can double-apply the manual summary
- 03 [real] Raw errors are stored without the required redaction or UTF-8 byte limit
- 04 [real] Non-2xx response bodies are discarded before whitelist projection
- 05 [real] Capability resync silently skips capability reconciliation for an unchanged manifest
- 06 [real] Manual resync drops the descriptor credential
- 07 [real] Manual async-resolution audit omits the asserted result and generation
- 08 [real] Console capability-sync audit events are misclassified as system actors

## ea-e2e-harness
- 01 [real] The only handover full-stack test is skipped unless an undocumented opt-in variable is set
- 02 [real] Lost or malformed assignments are converted into a successful conserved result

## ea-execute-conservation
- 01 [real] Recovery after Phase A double-counts the batch summary
- 02 [real] A malformed 202 response permanently strands the active lease
- 03 [real] A later 413 in an active plan rolls back terminal bookkeeping and lease release
- 04 [real] The frozen 413 assignment plan can be changed after partial execution
- 05 [real] Grant-only retry completes the action but leaves the final batch failed
- 06 [real] Aggregated summaries are hidden while a multi-batch plan is in progress
- 07 [real] Conservation validation accepts summaries that are not the frozen five-tuple

## ea-fe-allocator
- 01 [real] Incomplete type-level transfer can execute the previous server assignment
- 02 [real] Deleting an override is undone after changing page or search
- 03 [real] Receiver-less transfer drafts are silently converted into override deletion
- 04 [real] Snapshot-stale cleanup leaves reusable React Query data behind
- 05 [real] Edits remain enabled during PUT and are overwritten by the post-save refetch

## ea-fe-panels
- 01 [real] Execute can race a pending grant-receiver update and transfer permissions to the old recipient
- 02 [real] 412 recovery leaves stale item and override state mounted
- 03 [refuted] Next-batch preview allows concurrent submissions and stale confirm-version overwrite — Although frontend/src/features/handover/HandoverActionPanel.tsx:277-286 does permit concurrent preview calls, the alleged out-of-order successful overwrite is prevented server-side. Every preview rese
- 04 [real] Done summaries can be blank and permanently hide required zero-valued fields
- 05 [real] 409 confirm-version recovery re-enables confirmation before fresh state arrives

## ea-lease-async
- 01 [real] Manual async resolution can adopt a poller's live fence and commit competing writes
- 02 [real] Manual completion turns a non-final split batch into the final batch
- 03 [real] Recovery payload conflicts cannot reach the required manual-resolution exit
- 04 [real] The attention-state 30-minute backoff is bypassable at the polling entry point

## ea-manifest-apps
- 01 [real] Conflicting capabilities remain silently skipped when the previous state is none
- 02 [real] Removing lifecycle leaves stale declared capability state
- 03 [real] Capability synchronization deterministically overwrites console-owned webhook configuration
- 04 [real] The updated_by ownership guard has a check-then-save race
- 05 [real] Concurrent same-version imports return 422 instead of idempotent success or 409 conflict

## ea-offboard-upgrade
- 01 [real] Assignment mutations are allowed while a retryable pending batch contains an older canonical payload
- 02 [real] Changing assignments leaves a zero-progress 413 batch plan active and silently reuses its stale chunks
- 03 [real] One offboarding conflict rolls back the entire directory reconciliation round
- 04 [real] Concurrent reuse of an idempotency key for different subjects returns an unhandled database error instead of 409
- 05 [real] Non-transfer assignments with a receiver reach database constraints and produce HTTP 500

## ea-payload-models
- 01 [real] Override releasability trigger misses parent-side updates
- 02 [real] Manual async completion leaks a non-contract summary object
- 03 [real] Delivery terminal outcomes are mutable despite the single-transition contract
- 04 [real] Permanent skip records are not append-only and do not protect their task

## ea-portal-api
- 01 [real] A revoked assignee can win a TOCTOU race and execute a handover
- 02 [real] Reassign creation exposes a committed task with the wrong assignee
- 03 [real] PUT overrides silently drops duplicate and contract-invalid assignments
- 04 [real] An omitted grant_receiver field silently clears the configured receiver
- 05 [real] Concurrent cross-subject reuse of an idempotency key returns 500
- 06 [real] Successful idempotent creation replays return the wrong status code
- 07 [real] Malformed page values are silently converted to page 1
- 08 [real] GET overrides can pair a new override set with a stale version

## ea-sdk
- 01 [real] signature_failure_status permits successful authentication-failure responses
- 02 [real] Malformed callback results escape the fixed-error boundary or return false success
- 03 [real] Explicit null handover_asset_types bypasses manifest validation
- 04 [real] Validly signed malformed payloads are reported as signature failures

## ea-webhooks-net
- 01 [real] The E2E loopback exception can become a production SSRF escape
- 02 [real] Non-2xx response bodies are discarded before whitelist extraction and redaction
- 03 [real] 429 responses cannot honor Retry-After
- 04 [real] Asynchronous delivery retries contractually terminal HTTP statuses
- 05 [real] Late-ack task redelivery can bypass persisted backoff and exhaust attempts early
- 06 [real] POST requests omit the frozen JSON charset parameter

## ep-commands
- 01 [refuted] Owner promotion is incorrectly reported as merged — /Users/konata/code/EasyAuth/docs/design/data-handover-v2/05-easyproject-backend.md:297-304 explicitly classifies receiver-already-member, including OWNER→MEMBER promotion, as merged. backend/app/domai
- 02 [refuted] Work-record results omit the participant role bucket — backend/app/domain/work_records/handover.py:51-72 always reports exactly one aggregate transferred/merged unit. The actual consumer at backend/app/domain/handover/service.py:686-700 reads result.trans
- 03 [refuted] Work-record handover accepts a self-transfer as successful — backend/app/domain/handover/service.py:461-483 resolves every execute transfer to dtuid and rejects to_dtuid == from_dtuid before adding it to the plan. backend/app/domain/handover/service.py:686-697 
- 04 [refuted] Required task activity emission is optional — backend/app/composition.py:409-425 wraps the task command and unconditionally injects SqlTaskActivityWriter into the production HandoverServiceV2; backend/app/composition.py:511 installs that service 
- 05 [real] Queued reminders for former recipients are not superseded
- 06 [real] Truncated ad-hoc reminder dedup keys can silently drop recipients
- 07 [real] Reminder rule version is not advanced and an unauthorized timestamp is changed

## ep-infra-identity
- 01 [real] Production pure identity bindings are always rolled back
- 02 [real] Cached items responses bypass the generation watermark fence
- 03 [real] Pure binding accepts an inactive local target when its sub was previously null
- 04 [real] Concurrent pure-binding uniqueness conflicts escape as HTTP 500
- 05 [refuted] Directory throttling loses Retry-After and is exposed as 502 — The implementation does collapse RateLimited through the Transient branch at backend/app/domain/identity/handover_identity.py:146-147 and maps it to 502 at backend/app/api/v1/easyauth_lifecycle.py:86-

## ep-op-worker
- 01 [accepted-debt] Expired claims can perform HTTP and commit terminal state without renewal — backend/app/infra/jobs/openproject_handover_projection.py:163 captures `now`; :252 awaits the apply without renewal; :190-205 passes that stale value to the terminal CAS, whose expiry predicate is at 
- 02 [real] Advisory-lock contention both consumes and bypasses the attempts cap
- 03 [accepted-debt] Resolved conflict rows make subsequent exhaustion roll back — backend/app/infra/repositories/op_sync.py:318-324 searches only unresolved rows, then :209-222 inserts a new row; backend/alembic/versions/m32_002_op_handover_outbox.py:72-77 uniquely constrains every
- 04 [accepted-debt] Advisory-lock release failures can leak locks into the pool — backend/app/infra/jobs/openproject_handover_projection.py:254-262 catches unlock failure without invalidating the connection or calling `pg_advisory_unlock_all`; :263-264 merely closes the SQLAlchemy 

## ep-service
- 01 [real] Completed idempotent replays are blocked by mutable identity resolution
- 02 [real] Execute can accept an ABA snapshot while applying a stale plan

## et-execute-receipt
- 01 [real] Locked receiver validation can use stale active status
- 02 [real] Non-canonical UUID override IDs silently receive the default action
- 03 [real] Explicit null actions are silently interpreted as skip

## et-locks-integration
- 01 [real] User-first locks deadlock with remediated business writers through implicit FK locks

## et-registry-preview
- 01 [real] Receivable hint silently substitutes gross amount when net amount is indeterminate
- 02 [real] Task and sample hints omit required related-asset identity
- 03 [real] Items single-flight is bypassed across workers or replicas

## 修复处置报告（按批次）

### fix-report-ea1-execute

# EasyAuth execute 守恒修复处置报告

ea-execute-conservation-01 -> fixed@63340e1（以批次 `data_completed_at` 作为 durable merge marker，恢复重放不再重复合并 summary 或推进计划）
ea-execute-conservation-02 -> fixed@63340e1（202 缺少状态查询 URL 时进入 fenced delivery failure 事务并释放租约）
ea-execute-conservation-03 -> fixed@63340e1（部分完成计划后的 413 保留 active plan，记录不可分片指引并提交失败状态与租约释放）
ea-execute-conservation-04 -> fixed@63340e1,fb7a5f2（部分计划阻止 `grant_receiver` 变更；计划摘要包含权限接收人并在每个 planned batch 前校验 canonical intent）
ea-execute-conservation-05 -> fixed@63340e1（grant-only 成功在同一 fenced 事务中把最终批次与 active plan 收尾为 done）
ea-execute-conservation-06 -> fixed@28adcc7（API 直接返回非空的持久化累计 `result_summary`，不再受 action 最终状态门控）
ea-execute-conservation-07 -> fixed@63340e1（summary 行键集合必须严格等于冻结五元组，且每个值必须为非负原生 `int`）

门禁：`.venv/bin/python -m pytest tests/unit/lifecycle -q` -> 92 passed；`.venv/bin/python manage.py check` -> 0 issues；`.venv/bin/python manage.py makemigrations --check --dry-run` -> No changes detected；`pnpm --filter @easyauth/frontend build` -> 1843 modules transformed、构建预算通过；`.venv/bin/uv build` -> sdist 1 + wheel 1 成功；`docker compose -f docker-compose.deploy.yml up -d --build web worker webhook-worker notify-worker beat stream` -> 镜像构建及 6 个 EasyAuth 服务重建成功；`GET http://127.0.0.1:8001/health/` -> HTTP 200、`{"status": "ok"}`。


### fix-report-ea2-lease-abandon

# EasyAuth 异步租约与人工处置修复报告

ea-lease-async-01 -> fixed@a1373b4
ea-lease-async-02 -> fixed@a1373b4
ea-lease-async-03 -> fixed@a1373b4
ea-lease-async-04 -> fixed@a1373b4
ea-console-api-01 -> fixed@a1373b4
ea-console-api-02 -> fixed@a1373b4
ea-payload-models-02 -> fixed@0c707bd+a1373b4

pytest 目标测试 -> 68 passed, 0 failed
manage.py check -> 0 issues, 0 silenced
makemigrations --check --dry-run -> 0 changes
前端生产构建 -> 成功, 构建预算通过
后端 Python 包构建 -> 成功, 生成 sdist 1 个、wheel 1 个
后端 Docker 镜像构建 -> 成功, easyauth-web:local
Django 服务重建与健康检查 -> running healthy, /health/ HTTP 200
目标 async-abandon URL 真实 HTTP 响应 -> HTTP 403 CSRF, 路由已由重建后的 Django 服务加载


### fix-report-ea3-offboard-approvals

# EasyAuth 离职交接与审批审查修复处置报告

ea-offboard-upgrade-01 -> fixed@657609f
ea-offboard-upgrade-02 -> fixed@657609f
ea-offboard-upgrade-03 -> fixed@e2de865
ea-offboard-upgrade-04 -> fixed@657609f
ea-offboard-upgrade-05 -> fixed@657609f
ea-approvals-adr36-01 -> fixed@1f8558e
ea-approvals-adr36-02 -> fixed@1f8558e
ea-approvals-adr36-03 -> fixed@1f8558e
ea-approvals-adr36-04 -> fixed@1f8558e
ea-approvals-adr36-05 -> fixed@1f8558e

门禁统计：目标 pytest 81 passed、0 failed；`manage.py check` 0 issues；`makemigrations --check --dry-run` 0 changes；后端字节码构建 4 次成功；前端生产构建 4 次成功；Docker 后端镜像构建 1 次成功；Django web 及 worker/beat/stream 服务重建成功；真实 HTTP 验证 `/portal/` 返回 302、交接 PATCH URL 返回 403（未认证且无 CSRF），运行容器内已确认加载 `receiver_not_allowed` 新代码。


### fix-report-ea4-portal

ea-portal-api-01 -> fixed@3110ac4
ea-portal-api-02 -> fixed@3110ac4
ea-portal-api-03 -> fixed@3110ac4
ea-portal-api-04 -> fixed@3110ac4
ea-portal-api-05 -> disputed: 当前基线已由既有提交 `657609f5` 在 `src/easyauth/lifecycle/offboarding.py:244-283` 用内层 savepoint 捕获唯一约束败者的 `IntegrityError`，随后读取赢家并比较 canonical hash；不同请求体抛出 `idempotency_conflict`，同请求体返回原单。`tests/unit/lifecycle/test_round4_review_fixes.py:155-189` 已覆盖跨 subject 的同键冲突，故所述 500 路径在本轮开始前已不存在。
ea-portal-api-06 -> fixed@3110ac4
ea-portal-api-07 -> fixed@3110ac4
ea-portal-api-08 -> fixed@f9f1b4b

目标测试：67 passed，0 failed（`tests/integration/portal/test_portal_handover_api.py`、`tests/unit/lifecycle/test_round4_review_fixes.py`、`tests/unit/lifecycle/test_upgrade.py`、`tests/unit/lifecycle/test_services.py`）。
Django system check：0 个问题，0 silenced。
迁移漂移检查：0 个变更（`No changes detected`）。
扩展生命周期回归：127 passed，0 failed（`tests/unit/lifecycle` + 门户交接 API）。
后端构建：wheel 1 个、sdist 1 个，均成功。
前端构建：1843 个模块完成转换，构建预算通过。
运行服务验证：`GET /health/` -> 200；`GET /portal/api/v1/handover-candidates?purpose=reassign_subject`（匿名）-> 401 JSON，确认新 Django 进程已加载门户路由。


### fix-report-ea5-console-manifest

# EA5 控制台与 Manifest 复核处置报告

ea-console-api-03 -> fixed@6bafe60（统一投影补齐@568e0e3）
ea-console-api-04 -> fixed@6bafe60
ea-console-api-05 -> fixed@1392063
ea-console-api-06 -> fixed@1392063
ea-console-api-07 -> fixed@6bafe60
ea-console-api-08 -> fixed@1392063
ea-manifest-apps-01 -> fixed@1392063
ea-manifest-apps-02 -> fixed@1392063
ea-manifest-apps-03 -> fixed@1392063
ea-manifest-apps-04 -> fixed@1392063
ea-manifest-apps-05 -> fixed@1392063

门禁 -> SQLite 定向测试 56 passed / 2 skipped；PostgreSQL 并发定向测试 2 passed；`manage.py check` 0 issues；`makemigrations --check --dry-run` 无变更。
构建 -> 每个提交后均完成前端生产构建与后端 Docker 镜像构建，共前端 3 次、后端 3 次，全部成功。
运行验证 -> 已应用 `applications.0032`，重建并重启 compose 开发栈；`GET http://localhost:8001/health/` 返回 HTTP 200 与 `{"status": "ok"}`。


### fix-report-ea6-webhooks-beat

# EA6 Webhook 与 Beat 审查修复处置报告

ea-webhooks-net-01 -> fixed@7f7bc24（E2E 专用 settings 入口、部署 settings 启动拒绝、仅允许 loopback）
ea-webhooks-net-02 -> fixed@7f7bc24+036f58b（非 2xx 有界响应体、JSON 错误包与非 JSON 投影进入统一脱敏证据链及投递账本）
ea-webhooks-net-03 -> fixed@7f7bc24+036f58b（传输捕获并限制 `Retry-After`，API 原样返回退避头，execute 按该延迟重新入队）
ea-webhooks-net-04 -> fixed@303191b（终结状态立即失败；400/423/429/5xx 重试；首次加五次退避共六次尝试）
ea-webhooks-net-05 -> fixed@303191b（持久化 `next_attempt_at`，任务携带 expected attempt，claim CAS 同时校验序号与到期时间）
ea-webhooks-net-06 -> fixed@7f7bc24+303191b（同步与异步 POST 均发送 `application/json; charset=utf-8`）
ea-beat-tasks-01 -> fixed@7b9e892+118eecf（缺身份无限退避重试；真实 outbox 发布失败后补齐身份可进入 notify 受理与投递 outbox）
ea-beat-tasks-02 -> fixed@7b9e892（按 200 条有序批次以 `select_for_update(skip_locked=True)` 排空全部 eligible 行，并保留同事务条件更新与 outbox）

目标测试 gate -> 148 passed，0 failed
`manage.py check` -> 0 issues（0 silenced）
`makemigrations --check --dry-run` -> No changes detected
前端生产构建 -> 通过（1843 modules，构建预算通过）
后端镜像构建 -> `easyauth-web:local` 构建成功
运行态验证 -> `webhooks.0005` 迁移成功；6 个服务已重建；`GET /health/` 返回 HTTP 200 与 `{"status":"ok"}`


### fix-report-ea7-sdk-e2e

ea-sdk-01 -> fixed@d1903479e33b50b41b38a7a16f581ff02db8f1ed
ea-sdk-02 -> fixed@d1903479e33b50b41b38a7a16f581ff02db8f1ed
ea-sdk-03 -> fixed@d1903479e33b50b41b38a7a16f581ff02db8f1ed
ea-sdk-04 -> fixed@d1903479e33b50b41b38a7a16f581ff02db8f1ed
ea-e2e-harness-01 -> fixed@9ff528fa897c5dc94a6a5214429c4123b0018648
ea-e2e-harness-02 -> fixed@9ff528fa897c5dc94a6a5214429c4123b0018648
gate-targeted-pytest -> 54 passed, 1 skipped（根环境未安装可选 FastAPI extra）
gate-sdk-fastapi-pytest -> 55 passed
gate-e2e-stub-pytest -> 8 passed（包含在 targeted pytest 总数内）
gate-playwright-fullstack -> 1 passed, 0 skipped
gate-manage-check -> 0 issues, 0 silenced
gate-makemigrations-check -> No changes detected
gate-frontend-build -> 通过（1843 modules transformed，构建预算通过）
gate-backend-build -> 通过（sdist 与 wheel 均成功）


### fix-report-ea8-models

ea-payload-models-01 -> fixed@84cbbac
ea-payload-models-03 -> fixed@9dd9126
ea-payload-models-04 -> fixed@9dd9126
目标回归测试 -> 6 passed，0 failed，0 skipped（PostgreSQL 16）
`manage.py check` -> 0 issues（0 silenced）
`manage.py makemigrations --check --dry-run` -> 0 changes
前端构建 -> 成功，1843 modules transformed，构建预算通过
后端构建 -> 成功，`easyauth-web:local` 镜像已构建
服务验证 -> `/health/` HTTP 200，容器 healthy，`lifecycle.0008`/`0009` 已应用


### fix-report-ep1-service-identity

ep-service-01 -> fixed@3975019 (regression@16950c6)
ep-service-02 -> fixed@3975019 (regression@16950c6)
ep-infra-identity-01 -> fixed@3975019 (regression@16950c6)
ep-infra-identity-02 -> fixed@3975019 (regression@16950c6)
ep-infra-identity-03 -> fixed@3975019 (regression@16950c6)
ep-infra-identity-04 -> fixed@3975019 (regression@16950c6)

targeted pytest (unit + integration, handover/identity/bind_verified_authentik_sub): 116 passed, 2007 deselected in 100.66s
full pytest (unit + integration + contract): 2294 passed, 37 skipped in 1285.63s
check_permissions.py: OK (60 permissions, 5 groups, 168 endpoint mappings; 1 existing unused-permission warning)
check_openapi.py: OK (168 baseline endpoints)
check_migrations.py: OK (40 revisions, head m00_004_dh2_heads)

Note: pytest was launched from backend/ with the same three suite paths because the repository-root local .env contains unrelated FRONTEND_PORT=3001, which current Settings rejects as an extra field.


### fix-report-ep2-commands-worker

ep-commands-05 -> fixed@9cd7c6f（按冻结契约将 PENDING/QUEUED 旧 occurrence 置 SKIPPED + HANDOVER_SUPERSEDED；§1.1 禁止写 notifications/notification_recipients/notification_outbox，故未采纳越权取消建议）
ep-commands-06 -> fixed@9cd7c6f（回归断言补充于 ee6b5de）
ep-commands-07 -> fixed@9cd7c6f
ep-op-worker-02 -> fixed@ec6e624
targeted pytest -> 6 passed, 2119 deselected in 11.40s
full unit+integration+contract pytest -> 2296 passed, 37 skipped in 1282.52s (0:21:22)
check_permissions.py -> OK（60 权限唯一 / 5 授权组 / 168 端点映射 / manifest 溯源一致；1 条未直接引用权限 WARN）
check_openapi.py -> OK（基线 168 端点）
check_migrations.py -> OK（40 revisions；head m00_004_dh2_heads）


### fix-report-et1-all

et-execute-receipt-01 -> fixed@0eabde15
et-execute-receipt-02 -> fixed@0eabde15
et-execute-receipt-03 -> fixed@0eabde15
et-locks-integration-01 -> fixed@56304cc4
et-registry-preview-01 -> fixed@0eabde15
et-registry-preview-02 -> fixed@0eabde15
et-registry-preview-03 -> fixed@0eabde15
gate: `BACKEND_TESTS='app/tests' make finish-check` -> PASS
gate tally: shared platform pytest 80 passed, 2 warnings; customs pytest 290 passed, 3 warnings; EasyTrade app pytest 3553 passed, 5 skipped, 13 warnings; ruff check and format check passed; Alembic head guard passed; frontend `tsc --noEmit` passed; Playwright skipped because `FRONTEND_TESTS` was not set, as prescribed by the requested gate.


### fix-report-fe1-frontend

# FE1 frontend fix disposition report

Branch: `round4-fe` (worktree `EasyAuth-worktrees/fe-round4`)
Commits:
- `70397c3` fix(handover): 资产分配器 transfer 草稿、override 完整集与 412/保存锁
- `393bdb7` fix(handover): 执行面板 mutation 互斥、快照恢复与 done 摘要五元字段

## Findings

- ea-fe-allocator-01 -> fixed@70397c3
- ea-fe-allocator-02 -> fixed@70397c3
- ea-fe-allocator-03 -> fixed@70397c3
- ea-fe-allocator-04 -> fixed@70397c3
- ea-fe-allocator-05 -> fixed@70397c3
- ea-fe-panels-01 -> fixed@393bdb7
- ea-fe-panels-02 -> fixed@393bdb7
- ea-fe-panels-04 -> fixed@393bdb7
- ea-fe-panels-05 -> fixed@393bdb7

Disputed: none

## Fix notes (contract-aligned)

| ID | Change |
|---|---|
| allocator-01 | transfer 无接收人 / 清空接收人 → 本地非法草稿 + `onBusyChange(true)`，执行保持禁用直至合法 PATCH |
| allocator-02 | `drafts` 为跨页完整 override 集合；改回默认即从 drafts 删除；PUT 不再从 `fullOverrides` 回填 |
| allocator-03 | transfer 无 `to_user` 时禁用 Save + 显式 `receiverRequired`；mutationFn 拒绝静默过滤 |
| allocator-04 | 412：`removeQueries` items/overrides、收起展开、`snapshotEpoch` 隔离缓存；`canSubmit` 等待 query settle |
| allocator-05 | `saveMutation.isPending` 时锁定条目 action/receiver/分页/搜索 |
| panels-01 | `actionMutationLock`：grant PATCH / allocator busy / preview / execute 互斥；grant pending 时分配器只读 |
| panels-02 | 412：关闭确认、`allocatorResetKey` remount、清除该 action 的 items/overrides 缓存后 `onTaskRefresh` |
| panels-04 | done：null/{} → `summaryEmpty`；五元字段（含 merged/failed=0）始终渲染 |
| panels-05 | 409 confirm_version_stale：关确认 + `blockedConfirmVersion` 阻塞执行，直到新 `confirm_version` 装入 |

## Regression tests

- `frontend/src/features/handover/AssetAllocator.test.tsx` — ea-fe-allocator-01..05
- `frontend/src/features/handover/HandoverActionPanel.test.tsx` — ea-fe-panels-01/02/04/05

## Gates

| Gate | Result |
|---|---|
| `pnpm install --frozen-lockfile` | pass |
| `pnpm test` (vitest) | pass — 54 files / 362 tests |
| `pnpm build` (tsc + vite + budget) | pass — 入口 35.3 KiB / gzip 11.4 KiB；JS 总量 915.0 KiB |

Push: not performed (per instructions).

