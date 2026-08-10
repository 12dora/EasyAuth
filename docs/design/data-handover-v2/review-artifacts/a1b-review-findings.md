# A1b review findings (3 opus shards)

## Shard: v2:6d9c1640d70254647200c6dbbcafffa9670efe4d5bb49b593eecb1cbde8e6890 — verdict: issues_found

### [blocker/confirmed] src/easyauth/lifecycle/handover.py:383
**complete_data_phase 的「事务 A/B/C」实际跑在调用方的单个事务里, 授权转移一失败就整体回滚 —— action 卡在 executing、data_completed_at 丢失、租约永不释放, (subject, app) 永久锁死**

Evidence: complete_data_phase() 本身不开事务, 两个调用点都把它包在一个 atomic 里 (同步 200: handover.py:924-935; 异步终态: handover.py:319-336)。grant 步骤 (handover.py:383-394) 在 except 里写 action=failed / batch=failed / cas_release 后 `raise`, 异常穿出 atomic → 这些补救写入连同 action.data_completed_at (line 379) 一起被回滚。

实测 (docker uv pytest, monkeypatch transfer_selected_grants 抛 RuntimeError, 数据 webhook 已返回 200):
  ACTION STATUS: executing
  DATA COMPLETED AT: None
  LEASE released_at: None
  BATCH status: executing

后果: 下游数据已经搬走, EasyAuth 却什么都没记; action 停在 executing → retry_action 只接受 failed (line 222) 拒绝, skip_action 不接受 executing 且 action_execution_in_flight 为真 (line 421-431), cancel_task 因未释放租约拒绝 (line 528-539)。租约的条件唯一约束会让该 (subject, app) 此后任何 execute 都撞 409 handover_execution_in_flight。恢复任务抢占后重放 execute, 下游幂等返回 200 → 再次走到同一个回滚 → 无限循环。

触发条件真实存在: transfer_selected_grants 会抛 HandoverError(CATALOG_TARGET_DELETED_MESSAGE) (transfer.py:247), 任何 DB 异常同理。

违反 01 §5.5「action.data_completed_at 必须在授权事务之前提交…顺序写反了 retry 会重新发一次数据 webhook」与 §2.4.2 冻结表「授权转移(事务 B/C)失败 → 写 action.status='failed' 的那次 CAS 同时释放租约」。修法: A/B/C 必须各自 commit, 且调用方不得把 complete_data_phase 裹在自己的事务里。

### [major/confirmed] src/easyauth/lifecycle/handover.py:848
**generation 守卫把 superseded 落库和 cas_release 写在 atomic 内再 raise, 两者一起回滚, 租约同样永不释放**

Evidence: handover.py:848-857: `with transaction.atomic(): ... delivery.outcome = superseded; delivery.save(); cas_release(handle); raise HandoverConflictError('generation_superseded')` —— raise 在 with 内, 整块回滚。且 HandoverConflictError 不被下面的 `except HookCallError` 接住, 直接穿出。

实测 (monkeypatch _locked_action 让守卫事务看到不同 generation):
  RAISED: HandoverConflictError generation_superseded
  ACTION: executing / LEASE released: None / BATCH: executing / DELIVERY: sent

即 §5.5 要求的「标 superseded 并写审计, 不发网」一条都没落库, 而 §2.4.2「上表之外的任何结局不存在, 漏掉任何一行那条 (subject, app) 就被永久锁住」被违反。死锁形态与 blocker 相同(不能 retry / skip / cancel)。当前同步发送使窗口很窄, 但 §2.4.1 要求的 outbox 异步发送一旦接上, 窗口就是整个排队时间。

### [major/plausible] src/easyauth/lifecycle/handover.py:365
**complete_data_phase 的非最终批分支只在 status==executing 时把 action 退回 previewed, 异步(202)非最终批会把 action 永久留在 async_pending 且租约已释放**

Evidence: handover.py:365-376: 非最终批只有 `if action.status == ACTION_STATUS_EXECUTING` 才写回 previewed, 然后无条件 cas_release。异步路径进来时 action.status 是 async_pending / async_attention_required (poll_async_action 在 line 334-335 调用它), 于是 action 停在 async_pending 而租约已释放: 再 poll 会因为 line 249 `lease is None` 恒抛 409; retry 要求 failed; skip_action 不接受 async_pending; cancel_task 见 async_pending 直接拒绝 (line 531)。这条 (subject, app) 又是一个死锁。

目前 _execute_action 恒 is_final=True (line 806), HandoverBatchPlan 只有建表没有执行入口, 所以是潜伏缺陷; 一旦 A1c 接上 413 分批 + 202, 立刻可达。

### [minor/confirmed] src/easyauth/lifecycle/handover.py:290
**轮询超上限转 async_attention_required 时既不写审计也不写日志, §7 要求的「写告警」完全缺失**

Evidence: handover.py:288-294 只改 status 并把租约移回 sentinel 就 return; handover.py 全文没有任何 logger / AuditService 调用与该状态相关 (grep logger 无命中)。01 §7 冻结要求是「第 10 次仍非终态: 只写告警并把 action 置 async_attention_required」, 而 §7.4/§9.2 说明超管无法枚举、只能靠控制台告警条 —— 此处不留任何痕迹, A1c 的告警条和排障都没有数据源, 一条需要人工介入的 action 会静默停在那里。

### [minor/confirmed] src/easyauth/lifecycle/offboarding.py:111
**ensure_handover_task 无条件调用 resolve_assignee, 自助 pre_offboard 单会写出一条与事实不符的 handover_assignee_resolution_degraded 审计**

Evidence: offboarding.py:111 先算 resolution, 随后 line 112 的分支若命中「pre_offboard 且 created_by == subject」就完全弃用它 (assignee 直接置为本人)。而 resolve_assignee 在目录缺失/stale 时有副作用 —— assignee.py:41-51、58-68 会写 handover_assignee_resolution_degraded 审计。00 §12 定义该事件的语义是「主管链缺失或 stale, 落超管池」, 这里单子既没落池也不 degraded, 属于伪造的审计事实 (00 §15 步骤 9 要按事件逐条核对)。把 resolve_assignee 挪进 else 分支即可。

### [minor/confirmed] tests/unit/lifecycle/test_services.py:441
**被改的既有测试把删掉的断言替换成上一行的重复断言, 且 poll 上限用例被改成测「没有租约」, 导致本次重构最关键的两条行为(poll 终态转授权限、超上限转 async_attention_required)零覆盖**

Evidence: 三处断言降级为同义重复: test_services.py:305-306 (原 `action.result_payload == {...}` → 重复 `assert action.status == "done"`)、348-349 (原「陈旧 preview 不得覆盖 preview_payload」→ 重复 preview_generation 断言)、394-395 与 441+444。字段确实随 v2 删除, 但没有替换成 v2 等价断言。

后果具体在这一片: test_poll_async_action_completes_action_and_task (line 398-444) 只断言 status/async_status_url/task.status, 从不断言 receiver 的 AccessGrant 被建出、也不断言 data_completed_at 非空 —— 而 00 §10.5 / 01 §5.5 点名的既有缺陷正是「poll 拿到终态直接置 done, 根本不转授 grant_receiver 的权限, 单据显示完成而授权一动没动」。这条回归现在没有任何测试挡住。

test_poll_async_action_rejects_attempts_at_limit_without_calling_hook (line 447-483) 删掉了 `preview_action` 与 `assert action.status == "async_pending"`, 冲突来源已变成「无 active lease」(注释自承), 上限语义完全不再被测; 全仓 grep 也没有任何测试提到 async_attention_required。建议补: 上限→attention_required 且租约仍持有、attention 状态继续 poll、终态 200 后 receiver 拿到授权。

**Reviewer notes:** 审查范围: 96dbc9a vs 8b2a3e5, 只看 §3 assignee.py、§4 escalation.py、§7 中 A1b 负责的部分(poll_async_action / async_attention_required / §2.4.2 租约接管), 外加 test_services.py 的断言降级排查。测试用 docker+uv 跑过 tests/unit/lifecycle + tests/integration/test_execution_lease.py: 51 passed, 5 skipped(租约用例要 PG)。另写了三个探针测试放在 scratchpad(/private/tmp/claude-501/-Users-konata/25e64908-6fe5-439e-9b58-2ae0856ba202/scratchpad/probe/), 以只读方式挂进容器 /probe 运行, 未改动 worktree 任何文件或 git 状态。

符合规范、已逐条验证通过的部分:
- assignee 解析 (assignee.py:38-126) 完全对齐 01 §3 / 00 §8.2: 查询同时限定 (dingtalk_source_slug, dingtalk_corp_id, dingtalk_userid); manager_chain 元素按映射取 entry["user_id"], 畸形项写 handover_assignee_chain_entry_malformed 后跳过而非静默; 跳过 departed / local-admin(LOCAL_ADMIN_SUBJECT_PREFIX) / subject 本人; 无层数上限; stale/缺链不 fail-closed 而是落超管池并写 handover_assignee_resolution_degraded, 与权限查询相反的取舍写对了。
- apply_assignee 满足「与 assignee 写入同事务」的硬要求: 唯一两个调用点 offboarding.py:139 与 escalation.py:35 都在 select_for_update 之后的 atomic 内; 函数自身只写字段+审计, 不自开事务。
- escalation.py 起始层级分情况写对了 (line 25-29): assignee_state=subject 时 start=0, 否则 escalation_level+1 —— 01 §4 的陷阱(固定 +1 会跳过直属主管)被规避, 且 test_escalate_from_subject_starts_at_level_zero 有覆盖。落池时 escalation_deadline 置 None、escalation_deferred_at 重置(顺延额度按层级重置, 00 §7.4)都对。
- 代管路径确认彻底缺席: 全仓 grep custody / 代管 / HANDOVER_CUSTODY 均无命中, escalation 全程不碰 AccessGrant(测试也断言了 grant 数不变), 符合 00 §2.5/§7.5 的取消决定。
- poll_async_action 的终态 200 确实走 complete_data_phase (handover.py:334-335), 没有 async_pending → done 直跳; 探针实测: 10 次 202 后第 11 次转 async_attention_required 且租约仍未释放, 之后继续 poll 拿到 200 → done + data_completed_at 落库 + 租约释放, 与 01 §7 的冻结要求一致。
- §2.4.2 租约原语基本正确: allocate_fence 是单语句 upsert RETURNING(PG 分支), 未用 get_or_create+UPDATE; renew_lease 带 lease_expires_at > now(不复活过期 owner); preempt_expired_lease 是「先抢占后查证」的抢占半边, 且四样(owner/fence/renewed_at/lease_expires_at)都写; LEASE_TTL=5min、LEASE_RENEW_INTERVAL=TTL/3 有单测断言。sentinel 两次移交(delivery:{pk} → sender:{...} → async:{batch.pk})都在。

分片之外但顺手发现、建议转交对应 reviewer 或 A1c(未计入 findings):
1. §8.3 的 pre_offboard → offboard 升级链路缺失: reset_action_for_upgrade (handover.py:662) 全仓无调用者, ensure_handover_task 在遇到 kind 不同的 open 单时直接 raise TASK_KIND_CONFLICT (offboarding.py:96), 于是「已有 open pre_offboard 单的人被检出离职」时 start_offboarding 会抛异常而不是升级; handover_task_upgraded 审计也无落点。
2. §2.4.1 要求 execute 事务只写 outbox、提交后由 worker 发网; 现实现是在 HTTP 线程里同步发 (handover.py:846-864), 没有任何 outbox 记录。
3. 00 §10.5 的 summary 守恒校验与 failed>0 判 failed 未实现: complete_data_phase 的 response_payload 参数被 `_ = response_payload` 直接丢弃 (handover.py:354), 响应只以原样存进 delivery.response_payload。
4. require_cas (lease.py:259) 只做 exists() 不加行锁, 01 §2.4.2 要求「持有租约行锁到本阶段提交」; 目前因为收尾全在一个事务里、末尾 cas_release 会失败回滚而侥幸安全, 一旦按 finding #1 拆成三个事务, 这里必须补 select_for_update。
5. handover_task_escalated 审计只记了 from_assignee_user_id 与 to_assignee_state, 缺 00 §12 要求的 to_assignee 本身 (escalation.py:72-83)。
6. ASYNC_ATTENTION_POLL_INTERVAL_SECONDS (core.py) 已定义但无人使用, 且 action 上没有「上次轮询时间」字段, A1c 想实现 30 分钟退避只能拿 updated_at 凑合。


## Shard: v2:667ee53772b62fb569bd284df7ef3d68b11ec82bcf0c6b3cf05fc629a2be5766 — verdict: issues_found

### [blocker/confirmed] src/easyauth/lifecycle/models.py:363
**HandoverAppAction.status keeps max_length=16 while the newly added enum value `async_attention_required` is 24 characters — Django system check E009 fails and PostgreSQL cannot store the value.**

Evidence: Model field: `status = models.CharField(max_length=16, choices=ACTION_STATUS_CHOICES, ...)`; migration 0006 line 326 `AlterField(... max_length=16)`. Verified three ways: (1) `manage.py makemigrations --check` aborts with `SystemCheckError: lifecycle.HandoverAppAction.status: (fields.E009) 'max_length' is too small to fit the longest value in 'choices' (24 characters).` — this breaks every manage.py command on the deploy path, and the repo's own gate test `tests/test_project_scaffold.py::test_manage_check_succeeds_when_project_configuration_is_valid` fails on it. (2) After applying migrations to a real PostgreSQL 16, `information_schema.columns` shows `lifecycle_handoverappaction.status character varying(16)`. (3) Live probe on that DB: assigning ACTION_STATUS_ASYNC_ATTENTION_REQUIRED raises `DataError: value too long for type character varying(16)`. Failure scenario: poll_async_action (handover.py:290) writes `async_attention_required` after ASYNC_POLL_MAX_ATTEMPTS; on PostgreSQL the write raises DataError, the transaction that should also settle/release the lease rolls back, so the action stays `async_pending` with `released_at IS NULL` — exactly the permanent (subject, app) lock 01 §2.4.2 / 00 §6.2 exist to prevent, and the async-abandon human exit can never be reached. SQLite hides it (no varchar length enforcement), which is why the unit tests pass. Fix: widen to >=24 in both the model and the migration AlterField (the column is already created at 16).

### [blocker/confirmed] tests/integration/admin_console/test_lifecycle_handover_api.py:137
**The destructive schema change did not update all callers in the same commit: this pre-existing integration test still references removed `policy` / `preview_payload` / `to_user` attributes and the old `update_action_receiver` signature, leaving 7 failing tests.**

Evidence: `pytest tests/integration/admin_console/test_lifecycle_handover_api.py -q` → `7 failed, 7 passed`. Breakages: line 137 `real_update(action=action, to_user=to_user, policy=policy)` plus a monkeypatch stub declaring `policy` keyword-only, while the production caller now omits it → `TypeError: fail_second_update() missing 1 required keyword-only argument: 'policy'` and HTTP 500 instead of the asserted 409; lines 168/169, 237, 314-317 raise `AttributeError: 'HandoverAppAction' object has no attribute 'to_user'` / `.policy`; line 277 asserts on the removed `preview_payload`. Two further tests (line 263, line 507) break on intended new behaviour (action starts `blocked` without handover capability; `confirm_transfer_grant_diff` now 409s until all actions are done/skipped) but were left unadjusted. The commit message claims schema and callers ship together; the console API module was updated, this test module was not touched at all.

### [major/confirmed] src/easyauth/lifecycle/handover.py:170
**The `update_action_receiver` compat shim silently swallows `policy`, so the still-live console PATCH endpoint accepts `release_to_pool` and mutually-exclusive receiver combinations and returns 200 while doing nothing.**

Evidence: `def update_action_receiver(*, action, to_user, policy=None): _ = policy; return update_grant_receiver(...)` discards `policy`, and the XOR guard `validate_receiver_strategy()` (core.py:89) is no longer reached from this path. `admin_console/lifecycle_api.py:733` still parses `entry.release_to_pool` but passes nothing derived from it. Failure scenario: a superuser PATCHes `{app_key, to_user_id: X, release_to_pool: true}` (or neither) — previously 400, now 200 with the release intent silently dropped; demonstrated by `test_receiver_requires_exactly_one_transfer_strategy[strategy0/strategy1]` failing with `assert 200 == HTTPStatus.BAD_REQUEST`. This is the silent-fallback pattern AGENTS.md and 00 §1.1 forbid; the field must be rejected until A1c replaces the endpoint, or the shim must raise rather than ignore `policy`.

### [minor/confirmed] src/easyauth/lifecycle/migrations/0006_handover_v2_schema.py:370
**`lifecycle_grant_item_unique_per_generation` is added with no data migration asserting existing rows are duplicate-free, which 01 §2.5.1 requires explicitly.**

Evidence: 01 §2.5.1: "迁移前先断言存量数据在该键上无重复（有重复说明现有快照逻辑已经出过问题，需要人工核对，不得自动去重）". The migration goes straight from `AddField(generation, default=1)` to `AddConstraint(UniqueConstraint(task, generation, source_grant_id, target_kind_snapshot, target_key_snapshot, scope_key))` with no `RunPython` pre-check. On a database that does contain a duplicated snapshot row the deploy fails with a raw `duplicate key value violates unique constraint`, giving the operator no signal that manual reconciliation — not de-duplication — is the required response.

### [minor/confirmed] tests/integration/test_execution_lease.py:36
**The two PostgreSQL constraint triggers created by the migration have no PostgreSQL-lane test although 01 §2.2 makes one mandatory; the HandoverActionSkipRecord retention-exemption assertion (§2.2.1) is also missing.**

Evidence: 01 §2.2: "触发器只在 PostgreSQL lane 验证；对应用例必须显式标记为需要真库". The only PG-marked test file is tests/integration/test_execution_lease.py (leases/fences only); grepping tests for `lifecycle_grant_receiver_offboard_trg` / `lifecycle_override_releasable_trg` returns nothing. I confirmed manually on a real PostgreSQL that both triggers do fire (grant_receiver on a `reassign` task and a `release` override under `releasable=false` are rejected), so the DDL is correct, but a future migration dropping them would go unnoticed. Similarly 01 §2.2.1 requires a unit test asserting the skip-record table is excluded from retention cleanup; the table is correctly absent from `run_retention_cleanup` (config/data_retention.py:62) but nothing asserts it.

### [minor/plausible] src/easyauth/lifecycle/handover.py:1093
**Downstream preview values are written into bounded columns without validation, turning a non-conforming APP response into an uncontrolled 500 instead of a controlled `failed` action.**

Evidence: `token = str(payload.get("snapshot_token", "") or ""); action.snapshot_token = token` goes straight into `CharField(max_length=128)`, and `count = int(raw.get("count", 0) or 0)` (line 1157) into `PositiveIntegerField`. On PostgreSQL I confirmed the column is `character varying(128)` and that `lifecycle_handoverassettype_count_check CHECK (count >= 0)` exists. Failure scenario: an APP returns a 200-byte snapshot_token (contract §10.5.1 caps it at 128) or `count: -1` → DataError/IntegrityError escapes `_complete_preview_request`, producing a 500 and leaving the action in its prior state, instead of recording the contract violation on the action (`last_error` + status `failed`) the way `undeclared_asset_type` does two lines above. `label` is correctly truncated with `[:120]`, so the omission looks like an oversight.

**Reviewer notes:** Scope: 01 §2.2/§2.3/§2.4/§2.4.1/§2.4.2/§2.5/§2.5.1/§2.7/§2.8 only. HTTP layer (§6) and beat tasks treated as out of scope per instructions.

What checks out (verified field-by-field against the doc tables and, where relevant, against a live PostgreSQL 16 after `manage.py migrate`):
- §2.2 destructive change: `RenameField to_user -> grant_receiver` (not Remove+Add); `execution_to_user` / `policy` / `execution_policy` / `preview_payload` / `result_payload` all removed; `preview_generation` and `attempts` retained as existing columns with no spurious AddField. New columns match the doc exactly (snapshot_token 128, confirm_version/overrides_version PositiveInteger default 0, blocked_reason 64, skipped_by 128, approval_instance_warning JSON null=True, last_error_raw TextField, batch_seq, data_completed_at, skipped_at).
- §2.2.1 HandoverActionSkipRecord present with SET_NULL FK + snapshot columns + index; delete_task refuses tasks with skip history (handover.py:554).
- §2.3/§2.4 HandoverAssetType / HandoverAssetOverride are byte-exact vs the doc (action_shape checks, unique keys, orderings). The extra `release_requires_releasable` and `*_action_supported` checks are strictly stronger additions, not deviations.
- §2.4.1 exactly two execution-record tables with the doc's split (HandoverExecutionBatch request-side immutable, HandoverDeliveryAttempt controlled single transition), plus HandoverBatchPlan per §2.4.1.1. No save()-override immutability trap. The `outcome IN ('sent','superseded') OR http_status IS NOT NULL OR error_text <> ''` CHECK is present verbatim, including the `superseded` and `error_text` legs the doc warns about.
- §2.4.2 lease + fence tables and LEASE_TTL / LEASE_RENEW_INTERVAL constants match; take/renew/preempt/CAS semantics pass on a real PostgreSQL lane (tests/integration/test_execution_lease.py: 5 passed).
- §2.5 no CustodyGrant tables, no HANDOVER_CUSTODY scope; `HANDOVER_ESCALATION_DAYS: Final = 14` hardcoded with no env override anywhere.
- §2.1 both constraint rebuilds present as RemoveConstraint+AddConstraint; open-task unique constraint includes pre_offboard; assignee shape/state checks correct and satisfiable by existing rows.
- §2.7 App capability: five fields + both check constraints in their own applications/0031 migration, which lifecycle/0006 depends on.
- §2.8 single hand-written lifecycle migration, correct dependency ordering, RunPython triggers with reverse_sql, no schema drift — `makemigrations --check --dry-run --skip-checks` reports "No changes detected".

Full-suite context (45 failed / 1388 passed): the 30 failures in tests/integration/frontend/test_react_shell.py plus test_app_detail_ops1 / test_operations_api_ops3 / test_portal_api_ops2 / test_oidc_session_s12 are environmental — the container has no built frontend assets (staticfiles.W004: src/easyauth/static does not exist), so the shell renders 500. Only the 7 in test_lifecycle_handover_api.py and the 1 in test_project_scaffold.py are attributable to this commit; both are reported above.

Environment: started and stopped my own throwaway PostgreSQL container (ea-a1b-shard2-pg); the worktree is unchanged (`git status --porcelain` empty) and no files were written into it.


## Shard: v2:88ae113498973d42dab77c5dfd4e8a4da6a38e835149ab379677e695e9841e68 — verdict: issues_found

### [blocker/confirmed] src/easyauth/lifecycle/models.py:363
**HandoverAppAction.status is CharField(max_length=16) but the new enum value async_attention_required is 24 chars — Django system check fails (every manage.py command aborts) and writing that status raises DataError on PostgreSQL, so §7's poll-limit path dies with the lease still held.**

Evidence: Ran on real PostgreSQL 16 in the review container: `manage.py check` → `SystemCheckError: lifecycle.HandoverAppAction.status: (fields.E009) 'max_length' is too small to fit the longest value in 'choices' (24 characters)`; a probe doing `action.status = ACTION_STATUS_ASYNC_ATTENTION_REQUIRED; action.save()` → `django.db.utils.DataError` (varchar(16)). Migration 0006_handover_v2_schema.py:342 also writes max_length=16. pytest does not run system checks, which is why the suite hides this. poll_async_action (handover.py:290) sets exactly this value when async_poll_attempts >= ASYNC_POLL_MAX_ATTEMPTS, so the one path 00 §6.2 requires ("async_attention_required 必须有人工出口") crashes and, per §2.4.2, that (subject, app) stays locked. Deployment is also blocked: migrate/runserver refuse to start on a system-check error.

### [blocker/confirmed] src/easyauth/lifecycle/handover.py:1224
**_build_execute_payload emits assignment keys that violate the frozen webhook contract: `type` instead of `asset_type`, and override `asset_id` instead of `id` — every execute call will be rejected by both downstreams.**

Evidence: 00 §10.5 freezes the request body as `assignments: [{"asset_type": "customer", "default_action": ..., "default_to_user_id": ..., "overrides": [{"id": "9b2c…", "action": ..., "to_user_id": ...}]}]`, and 03 §3.x spells the trap out verbatim in EasyTrade's DTO: `id: str  # 契约字段名就叫 id, 不是 asset_id`; EasyProject's AssignmentSpec also uses `asset_type`. handover.py:1215 emits `"asset_id": ov.asset_id` and handover.py:1224 emits `"type": asset_type.type_key`. 01 §5.5 requires "形状严格照契约 §10.5". Consequence: downstream parses zero assignments (or 422s), and because this canonical body is frozen into HandoverExecutionBatch.request_payload/request_hash and replayed on retry and on lease takeover, the wrong shape is what every idempotent replay sends.

### [blocker/confirmed] src/easyauth/lifecycle/handover.py:383
**complete_data_phase runs transactions A/B/C as one transaction and re-raises the grant-transfer failure from inside it, so a failure after the data webhook returned 200 rolls back action.data_completed_at, the batch/action failure marking AND the lease release — exactly the state §5.5 says must never exist.**

Evidence: Probe on real PostgreSQL (patched transfer_selected_grants to raise, called complete_data_phase inside the caller's atomic exactly as _handle_execute_response:924-934 and poll_async_action:319-335 do) printed: ACTION STATUS: previewed / ACTION data_completed_at: None / BATCH STATUS: executing / LEASE released_at: None. The except block at handover.py:387-394 writes status=failed + cas_release then `raise`, and that raise propagates out of the caller's `with transaction.atomic()` → full rollback. 01 §5.5 requires "action.data_completed_at 必须在授权事务之前提交" (otherwise retry re-sends the data webhook and the data is moved twice) and §2.4.2's table requires the grant-failure path to write failed and release the lease in the same CAS. Here neither happens: the action is stuck in `executing`, the lease stays unreleased, and §5.5.1 then forbids skip/cancel until the (still unimplemented) recovery beat expires it.

### [major/confirmed] src/easyauth/lifecycle/handover.py:1086
**_complete_preview_request marks the action `failed` and then re-raises inside the same atomic block, so the §5.3 failure state (undeclared/missing asset type) is rolled back and never persisted.**

Evidence: Probe on PostgreSQL: after `_complete_preview_request(req, payload={"assets": [{"type": "nope", "count": 1}]})` raised, the action re-read from the DB was `status='pending', last_error=''` (expected `failed` + `undeclared_asset_type: nope`). handover.py:1084-1092 sets status/last_error and calls refresh_task_status_locked, then `raise` exits the `with transaction.atomic()` opened at line 1079 → rollback. 01 §5.3 requires the action to go `failed` with last_error naming the offending/missing types; instead it silently stays previewable. Same anti-pattern at handover.py:742-747 in the grant-only retry branch.

### [major/confirmed] src/easyauth/lifecycle/lease.py:261
**require_cas is a plain .exists() read (no row lock) and several call sites discard the cas_release return value, so a preempted worker can still commit action/batch/delivery writes — violating §2.4.2's "影响行数不为 1 必须丢弃写回".**

Evidence: lease.py:259-268 uses `HandoverExecutionLease.objects.filter(...).exists()`; §2.4.2 requires "A / B / C 三个事务各自都要重新 CAS 并持有租约行锁到本阶段提交" — without select_for_update a recovery worker's preempt UPDATE can commit between the exists() check and the writes. The writes are then kept because the release result is ignored: handover.py:1001 and 1008 (`_ = cas_release(handle)` in _finish_delivery_failure, after already saving delivery.outcome/batch.status/action.status), handover.py:393 (grant-failure path) and handover.py:856 (generation-superseded path). Failure mode: recoverer preempts an expired lease, replays the canonical body, gets 200, while the old worker's late 5xx still writes action=failed — the stale-writer scenario fencing exists to prevent.

### [major/confirmed] src/easyauth/applications/handover_capability.py:36
**The capability declaration path is dead: sync_handover_capability_from_manifest has no caller, and the third whitelist (§5.2) was not added, so no App can ever reach handover_capability='declared' and every action is created `blocked`.**

Evidence: `grep -rn sync_handover_capability_from_manifest src/` returns only the definition — it is not called from the manifest push path (api/manifest_sync_views.py is untouched by this commit). 01 §5.2 also requires `_LifecyclePayload` (applications/permission_template_parsing.py:116-124, still `ConfigDict(extra="forbid")` with only handover_url/onboard_url/capabilities) and `AppManifestLifecycleInput` (permission_template_types.py:88-93) to gain a handover_asset_types DTO; neither was changed, so a downstream pushing lifecycle.handover_asset_types is rejected by validation before reaching the sync function. Effect on the execution chain: initial_action_status_for_app (handover.py:1305) always falls through to blocked/capability_undeclared, preview_action raises action_blocked, and no handover can run end-to-end.

### [major/confirmed] tests/integration/admin_console/test_lifecycle_handover_api.py:237
**The atomic commit left the test suite red: 7 console lifecycle tests fail because the to_user→grant_receiver rename and the new confirm_transfer_grant_diff data gate were not propagated to the integration tests.**

Evidence: Full run on PostgreSQL: tests/integration/admin_console/test_lifecycle_handover_api.py → 7 failed / 7 passed. Two causes: (a) `AttributeError: 'HandoverAppAction' object has no attribute 'to_user'` at lines 168/169/208/237 (field renamed in this commit); (b) `assert 409 == HTTPStatus.OK` on POST .../grant-diff/confirm — the new §5.5 gate (all actions done/skipped, no in-flight lease) now rejects the fixture, so the test needs rewriting. 01 §11 step 2 requires schema changes and all callers in one commit, and AGENTS.md requires a green build per commit; merging as-is hands A1c a red baseline. (The 38 other failures in the wider run are frontend-shell/asset tests unrelated to this commit.)

### [major/confirmed] src/easyauth/lifecycle/handover.py:112
**§5.6's items rate limit is not implemented — ITEMS_RATE_LIMIT_WINDOW_SECONDS/ITEMS_RATE_LIMIT_MAX are declared and never referenced, and no unit test asserts them.**

Evidence: `grep -rn ITEMS_RATE_LIMIT src/ tests/` matches only the two constant definitions at handover.py:112-113. fetch_action_items (handover.py:595-659) enforces the page/page_size/q bounds but performs no (actor, task_id, app_id) counting, and takes no actor argument at all, so a caller cannot enforce it either without changing the signature. 01 §5.6 freezes 「窗口 60 秒、上限 120 次(写成模块级常量并进单测断言)，超限返回 429 rate_limited」 and says that without it the read amplification of 00 §10.4 is wide open on the EasyAuth side.

### [major/confirmed] src/easyauth/lifecycle/handover.py:806
**413 batching is schema-only: no HandoverBatchPlan is ever created, assignments are never chunked, is_final is hard-coded True, and a 413 marks the batch `failed` so the only available action (retry) replays the identical oversized payload — a permanent 413 loop with no exit.**

Evidence: `grep -rn HandoverBatchPlan src/` matches only models.py; handover.py:806 always passes `is_final=True`; PAYLOAD_SOFT_LIMIT_BYTES (handover.py:114, the 200 KiB cut-off from §2.4.1.1) is never referenced. _finish_delivery_failure (handover.py:990-992) handles 413 by setting action back to `previewed` with the comment 「建 plan 由上层处理」 while setting batch.status=failed — and retry_action (handover.py:759-770) selects exactly the latest FAILED batch and re-sends batch.request_payload verbatim. Missing versus §2.4.1.1: plan creation with total/chunks/assignment_hash at the moment of the 413, forced default_action=skip on non-final batches plus all skip overrides on the final batch, completed_batches/batch_progress accounting, and the per-batch assignment_hash check. The complete_data_phase non-final branch (handover.py:365-376) is therefore unreachable and untested.

### [minor/confirmed] src/easyauth/lifecycle/models.py:178
**BATCH_IN_FLIGHT_STATUSES includes `pending`, so after a 429 (batch→pending, lease released, action→previewed) skip_action and update_grant_receiver are refused forever — nothing in this commit ever re-queues a pending batch.**

Evidence: action_execution_in_flight (lease.py:252-256) tests BATCH_IN_FLIGHT_STATUSES = (pending, executing, async_pending). 01 §5.5.1 defines the replacement predicate as 「存在 status ∈ {executing, async_pending} 的 HandoverExecutionBatch, 或存在未释放的 HandoverExecutionLease」 (§2.4.1.1 uses the wider set only for the three assignment-mutating endpoints). Probe on PostgreSQL: with a single batch left at status=pending, skip_action raises HandoverConflictError. retry_action only picks up FAILED batches, so the 429 requeue described in §2.4.2 has no implementation here — until A1c ships it, the superuser escape hatch §5.5.1 exists to guarantee is closed.

### [minor/confirmed] src/easyauth/lifecycle/handover.py:541
**Lock order is inverted between cancel_task (task → actions) and the execution paths (action → task), against §2.2's prescribed uniform order task → 子项; concurrent cancel and skip/complete can deadlock.**

Evidence: cancel_task locks the task (handover.py:526) then row-locks all actions via `HandoverAppAction.objects.filter(task=task).update(snapshot_token="")` (line 541). skip_action (420 → 461), complete_data_phase (363 → 405), _finish_delivery_failure (971 → 1009), _complete_preview_request (1080 → 1114) and reconcile_blocked_actions (handover_capability.py:131 → 162) all lock the action first and the task second. 01 §2.2 freezes 「要按统一锁序 task → 子项 加锁」. On PostgreSQL the loser gets a deadlock abort, which in the execute path means a lost response with an unreleased lease.

### [minor/confirmed] src/easyauth/lifecycle/handover.py:978
**Delivery rows persist the raw downstream response body and raw error text, and last_error_raw is never written — 00 §10.6 requires a redacted, length-capped projection in the ledger.**

Evidence: handover.py:977-981 stores `delivery.response_payload = response_payload` verbatim, and lines 903/929 do the same for the 202/200 bodies; error_text is `str(error)[:2000]` with no redaction. 00 §10.6 freezes: 「投递账本(HandoverDeliveryAttempt.response_payload / error_text)同样：只存 HTTP 状态、响应体的 SHA-256、以及白名单脱敏摘要，并冻结长度上限；不存未限长、未脱敏的副本」. Downstream 5xx bodies may carry SQL, connection strings, tokens and person identifiers, and these tables go into backups/exports. Also HandoverAppAction.last_error_raw (added by this commit) has no writer, and last_error is filled with str(error) rather than the whitelisted code/message projection.

### [minor/confirmed] src/easyauth/lifecycle/lease.py:131
**Renew and preempt compare lease_expires_at against the application clock (timezone.now()) instead of db_now(), which the §2.4.2 predicate table specifies; with skewed worker clocks a lagging owner can renew an already-expired lease or a fast recoverer can preempt a live one.**

Evidence: renew_lease (lease.py:126-132) filters `lease_expires_at__gt=now` with `now = timezone.now()`, and preempt_expired_lease (lease.py:205-215) filters `lease_expires_at__lte=now` the same way; both also write `lease_expires_at = now + LEASE_TTL` from the local clock. 01 §2.4.2 writes both predicates explicitly against `db_now()` (「续约: ... AND lease_expires_at > db_now()」, 「抢占: ... AND lease_expires_at <= db_now()」) precisely so all workers agree on expiry. Fix is a one-liner: use django.db.models.functions.Now in the filter and the update expression.

### [minor/confirmed] src/easyauth/lifecycle/lease.py:199
**The takeover protocol is half-built: preempt_expired_lease exists, but the "后查证" step (replay the original canonical body and branch on 200/202/409/unreachable) has no implementation anywhere, so the A1c recovery beat has nothing to call.**

Evidence: 01 §2.4.2 fixes the protocol as 先抢占 → 用原 (task_id, generation, batch_seq) 与原 payload 重放 execute → 200 走 complete_data_phase 并释放 / 202 转轮询 / 409 payload conflict 转人工告警且保持租约 / 不可达则续约重试, and §11.1 assigns 「租约接管协议」 to A1b (A1c only gets 「beat 注册与调度壳」). `grep -rn preempt_expired_lease src/` returns only the definition; there is no verify/replay helper in handover.py and no consumer of a preempted handle. Without it the recovery beat can only preempt-and-drop, the one behaviour §2.4.2 forbids.

### [minor/confirmed] src/easyauth/lifecycle/handover.py:662
**reset_action_for_upgrade resets every field on the §5.1.2 list correctly, but the mandatory "upgrade must be refused while a lease is unreleased" 409 guard is implemented nowhere and the function has no caller.**

Evidence: Field-by-field against the §5.1.2 table: generation ✓, data_completed_at→None ✓, snapshot_token→"" ✓, batch_seq→0 ✓, last_error/last_error_raw→"" ✓, async_status_url→""/async_poll_attempts→0 ✓, skipped_at/skipped_by/skip_reason cleared ✓, attempts→0 ✓, preview_generation deliberately untouched ✓, confirm_version/overrides_version each +1 ✓, status re-judged from capability with the superuser skip NOT inherited ✓ (handover.py:680-693). Missing: §5.1.2's 「升级前必须确认没有在途执行：存在未释放的 HandoverExecutionLease 时返回 409 handover_execution_in_flight」 — no upgrade service exists (`grep -rn reset_action_for_upgrade src/ tests/` finds only the definition), so nothing checks has_active_lease before bumping task.generation, and there is no test covering the reset list.

### [minor/confirmed] src/easyauth/lifecycle/handover.py:397
**snapshot_token is not cleared when the action completes, only when the task is cancelled — §5.6 requires clearing it in the same transaction on cancel or completion.**

Evidence: cancel_task clears it (handover.py:541) but complete_data_phase's final-batch branch (handover.py:396-408) writes status/async_status_url/last_error and leaves snapshot_token populated. 01 §5.6: 「取消或完成时同事务清空 snapshot_token」. The items gate currently blocks reuse via data_completed_at, so this is defence-in-depth rather than an open hole, but the stale token stays in the row and in any detail projection built later.

**Reviewer notes:** Scope: 01 §5 execution chain + §2.4.2 lease protocol, reviewed against 96dbc9a diffed on its parent. Verified on a throwaway PostgreSQL 16 container (created and removed afterwards; worktree untouched, `git status` clean). tests/integration/test_execution_lease.py: 5 passed on real PG. tests/unit/lifecycle: 51 passed. Adversarial probes ran from a scratchpad-mounted file, never written into the worktree.

Correct and closely checked (no finding): fence allocation is a single INSERT ... ON CONFLICT DO UPDATE RETURNING with no get_or_create/read-modify-write, and the conditional unique index really does serialise two tasks on the same (subject, app) — proven on PG, the second execute gets 409 handover_execution_in_flight. renew/preempt predicates carry the full owner+fence+released_at+expiry conjunctions, preempt writes all four columns including lease_expires_at, and preemption is ordered before verification. Both sentinel handoffs exist: delivery:{pk} then sender:{...} inside the entry transaction (handover.py:826-837), and async:{batch.pk} on 202 (line 916), with the poller claiming from the sentinel under select_for_update and handing back on a further 202. §5.5.1's attempts bans are gone from both skip_action and cancel_task; failed is skippable and the task is cancellable. ACTION_GRANT_TRANSFER_KINDS = (offboard,) is used on the action path rather than GRANT_MUTATING_KINDS. confirm_transfer_grant_diff has the §5.5 gate (all actions finished + no in-flight lease) and transfer_selected_grants mutates grants and item rows in one caller-owned transaction with an early return that does not bump grant version. §5.3's three-way (pk, generation, preview_generation) conditional reload is right and preserves default_action/default_to_user; §5.4 drops the "all skip" rejection and keeps the rest; compute_task_status is a full pure function with ACTION_FINISHED_STATUSES=(done, skipped) and ACTION_INITIAL_STATUSES=(pending, blocked, skipped), so D6 holds — covered by tests/unit/lifecycle/test_blocked_never_completes.py. complete_data_phase clearing snapshot_token on a non-final batch is correct per §2.4.1.1 (each batch must re-preview), not a bug. 412/423→pending, 413/429→previewed, all else→failed matches 00 §10.6. The cross-table constraint triggers (grant_receiver only on offboard; override release requires parent releasable) are real DEFERRABLE constraint triggers in migration 0006.

On the worker's self-reported gaps: "413 only partially wired" understates it — nothing beyond the two model tables exists (finding 9) and the 413 outcome as coded is a closed loop. "items rate-limit not enforced end-to-end" is accurate and cannot be finished by A1c alone because fetch_action_items takes no actor parameter (finding 8). Nothing else claimed in the commit message is a stub, but the capability-declaration half of §5.2 is inert (finding 6), which is why the chain cannot be exercised end-to-end today.

Fix order: findings 1-3 are hard blockers (1 breaks deployment and every management command; 2 breaks every downstream call and every replay; 3 loses the data-phase marker and the lease on grant failure). Findings 4 and 5 are the same class of transaction/CAS discipline bug and are cheap to fix alongside 3.

