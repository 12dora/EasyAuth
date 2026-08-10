# EasyProject handover review findings (5 opus shards)


## Shard: v2:df99ee7d187ba811ea0ae91624d00215569223be88773ebb0d76c2a840604934 — verdict: issues_found

### [blocker/confirmed] backend/app/domain/reminders/handover.py:174
**M18 rebuilds payload_snapshot with a hand-written 4-key dict instead of the materializer's variables, which makes reminder-enqueue silently kill every DUE_BEFORE occurrence of the handed-over task — the exact "整组提醒静默全灭" failure 05 §4.3.1 exists to prevent.**

Evidence: `_compute_new_natural_keys` (handover.py:174-179) writes `{"recipientRole", "taskTitle", "assignee", "assigner"}`. The authoritative materialize path (infra/jobs/reminder_materialize.py:87-90) writes `dict(intent.variables)` + `recipientRole` + `taskId`, i.e. for DUE_BEFORE it includes `offsetSeconds`, `dueRevision`, `taskNo`, `title`, `dueAt`. reminder_enqueue.py:253-259 reads exactly those: `offset_seconds = int(snap.get("offsetSeconds", 0))` → 0, `rev_mismatch = str(snap.get("dueRevision")) != str(task.due_revision)` → "None" != "1" → True → `mark_occurrences(rows, status=SKIPPED, error="DUE_REVISION_SUPERSEDED")` and `return 0` for the whole group. Worse, the same reduced dict is written over rows in the *kept* branch (handover.py:93-97), so DUE_BEFORE occurrences whose recipient did not even change (ASSIGNER rows) are destroyed too. Additionally enqueue.py:331 feeds `payload_snapshot` minus recipientRole straight into the notification event `variables`, so surviving reminders (OVERDUE/CADENCE) lose `taskNo`/`title`/`dueAt`/`overdueDays` template variables. Net effect after a task handover: receiver gets no due reminders and no error is raised anywhere.

### [major/confirmed] backend/app/domain/reminders/handover.py:159
**`_compute_new_natural_keys` swallows every exception and returns an empty new set, which makes the caller mark all PENDING occurrences SKIPPED — a silent total wipe on any config/algorithm error.**

Evidence: handover.py:151-160: `try: calc = calculate(...) except Exception: return {}`. With `new_keys == {}` the loop at handover.py:90-104 takes the else branch for every existing row and sets `status=SKIPPED, last_error=HANDOVER_SUPERSEDED`, then inserts nothing. A single unparsable `config_json` (or any future `calculate` bug) therefore deletes the entire reminder set for that rule with HTTP 200 returned to EasyAuth. 08 §1.3 M18 requires 「任一失败使整个 execute 数据库事务回滚 … 意外故障按契约 §10.6 返回 5xx」, i.e. the exception must propagate, not be converted into an empty set.

### [major/confirmed] backend/app/domain/reminders/handover.py:166
**The new-set computation ignores `OccurrenceIntent.status`, so intents the algorithm explicitly marks SKIPPED (PROGRESS_CADENCE / ALREADY_UPDATED) are inserted as PENDING or resurrected from SKIPPED to PENDING, sending reminders the domain said must not be sent.**

Evidence: domain/reminders/algorithm.py:229-241 emits `OccurrenceIntent(..., status=STATUS_SKIPPED, skip_reason="ALREADY_UPDATED")` for cadence slots where the assignee already reported progress; reminder_materialize.py:94-96 honours it (`status=intent.status`, `processed_at`, `last_error`). handover.py:166-179 keeps only `scheduled_for/kind/roles` and drops `occ.status`, so (a) such a key present in the new set makes the existing SKIPPED row be restored to `STATUS_PENDING` with `last_error=None` (handover.py:93-98), and (b) if absent it is INSERTed with `status=STATUS_PENDING` (handover.py:121). A handover on a task whose cadence reminder was legitimately skipped now fires a spurious 「请汇报进度」 reminder at a scheduled_for already in the past.

### [major/plausible] backend/app/domain/reminders/handover.py:111
**New occurrences are inserted with a raw `session.add` while the pre-existing-row lookup only considers PENDING/SKIPPED rows, so a natural key already held by a QUEUED/SENT/FAILED row raises IntegrityError and rolls the whole execute transaction back to a 5xx.**

Evidence: `uq_reminder_occurrences_natural (rule_id, scheduled_for, occurrence_kind, recipient_dingtalk_user_id)` and `uq_reminder_occurrences_dedup_key` are permanent, status-independent (alembic/versions/m18_001_reminder_tables.py:244-251; 08 §1.3 M18 spells this out). handover.py:66-78 loads `existing` with `status.in_([PENDING, SKIPPED])` only, and handover.py:111-127 does a plain ORM insert with no ON CONFLICT (contrast repositories/reminders.py:355-372 which uses `pg_insert(...).on_conflict_do_nothing()`). Trigger: an assignee-only handover on a rule whose OVERDUE_ESCALATED / PROGRESS_CADENCE recipient is the *unchanged* assigner or the `$MANAGER` placeholder — algorithm.py:_calc_overdue/_calc_cadence recompute the same `current` slot that was already materialized and QUEUED/SENT earlier that day, so the same natural key is regenerated and re-inserted.

### [major/confirmed] backend/app/domain/tasks/handover.py:59
**M10 transfers the assignee to a user who may already be a collaborator of the same task, leaving a task whose collaborator set contains the final assignee — the invariant 08 §1.3 M10 froze as 「合并后的 collaborator 集合不得包含最终 assignee」.**

Evidence: handover.py:59-80 sets `task.assignee_dingtalk_user_id = assignee_to_...` with no check on `task_collaborators`; the only guard implemented is the reverse direction (collaborator transfer targeting the final assignee, handover.py:115-117). Scenario, which is the most common offboarding shape: task assignee = A (leaver), B already a collaborator, `default_to_user_id = B`. After execute the row set is assignee=B **and** `task_collaborators(task, B)` — a state the human API forbids (`terr.assignee_cannot_be_collaborator()` at domain/tasks/commands.py:1235 and :1757-1758). It also feeds OP projection (`cf:collaborators_dtuid` containing the assignee) and double-notifies B. The fix per the ruling is to delete the target's collaborator row and count it as `merged`.

### [minor/confirmed] backend/app/domain/reminders/handover.py:130
**The rule cursor is never advanced: `calc.next_trigger_at` is discarded and only `version`/`updated_at` are touched, contrary to 08 §1.3 M18 「推进规则游标」 and §1.1's allowed-column list (`next_trigger_at`, `version`, `updated_at`).**

Evidence: handover.py:130-131 does `rule.version += 1; rule.updated_at = clock_now` and never calls the equivalent of `repo.update_rule_cursor(rule, next_trigger_at=calc.next_trigger_at, now=now)` (reminder_materialize.py:110). `calc` is computed inside `_compute_new_natural_keys` and its `next_trigger_at` is dropped on the floor at handover.py:162.

### [minor/confirmed] backend/app/domain/projects/handover.py:39
**M13 re-derives the terminal-project predicate inline instead of consuming the frozen selector in domain/handover/predicates.py, giving a third independent copy of the {COMPLETED, CANCELLED} set that 05 §3.1.2 requires to be frozen in one place.**

Evidence: projects/handover.py:39 uses a literal `{ProjectStatus.COMPLETED, ProjectStatus.CANCELLED}`; the sibling command domain/tasks/handover.py:13 imports `TERMINAL_PROJECT_STATUSES`/`TERMINAL_TASK_STATUSES` from predicates.py and infra/repositories/handover.py:25-36 builds its SQL filters from the same constants. domain/projects/handover.py imports nothing from `app.domain.handover.predicates`. Preview/items (predicates.py) and execute (this literal) can drift, which §3.1.2 flags as the source of the 412/423 loop.

### [minor/confirmed] backend/app/domain/projects/handover.py:92
**No command rejects a transfer whose target equals the source, and for `project_owned` the delete+insert path would then rewrite an existing membership's historical metadata (`added_by`, `created_at`), violating 08 §2.1's 「已存在的目标关系行，其 added_by / created_at 一个字节不动」.**

Evidence: 08 §2.5 lists 「接收人 … 不是来源本人」 under 绝不豁免, but neither domain/handover/service.py (no comparison of `to_dtuid` against `from_dtuid` anywhere; see `_apply_plan` at service.py:422-505) nor projects/handover.py / tasks/handover.py checks it. With `to == from`, `_transfer_owner` (projects/handover.py:101-108) deletes the OWNER row, then finds `target is None` and re-inserts it with `added_by=None, created_at=now`, destroying the original signature; `_transfer_member` (projects/handover.py:155-193) does the same for MEMBER rows and reports `transferred=1`.

### [minor/confirmed] backend/tests/integration/handover/test_execute_composite_keys.py:29
**None of the three commands in this shard has a unit test, and the §6-mandated composite-key integration file covers only one of the four merge scenarios — which is why the M18 payload/insert defects above are not caught by the suite.**

Evidence: `tests/integration/handover/test_execute_composite_keys.py` contains a single test (`test_owner_transfer_upgrades_existing_member`); 05 §6 requires 「§4.3 四类合并场景；OWNER 升级；每项目一个 OWNER 的部分唯一索引不被违反；merged 如实上报」. There is no test file anywhere referencing `domain/tasks/handover.py` or `domain/reminders/handover.py` (`grep -rn refresh_after_system_handover backend/tests` returns nothing), so `refresh_after_system_handover` ships with zero coverage. `.venv/bin/python -m pytest tests/integration/handover tests/unit/handover -q` → 20 passed, all green despite the defects above.

**Reviewer notes:** Scope: 87e73cf (M13), 30f680a (M10), 3e0ff04 (M18). Ran `backend/.venv/bin/python -m pytest tests/integration/handover tests/unit/handover -q` → 20 passed (integration ones do hit real PG via `alembic upgrade heads`, so both migrations apply cleanly).

Things I checked and found CORRECT, so nobody re-litigates them:
- m13_003 / m10_002: correct `down_revision = m46_001_record_task_order`, both are parents of m00_004_dh2_heads, ORM synced to `Mapped[str | None]` (projects.py:131, tasks.py:203/226). `alter_column(nullable=True)` without `existing_type` is fine on PostgreSQL and is exercised by the integration fixture. Downgrades restore NOT NULL without back-filling, which matches the frozen precondition in 08 §1.4 (「确认三列都没有 NULL」) rather than being a defect.
- AG-00 §2.1 actor semantics: `task_assignment_history.changed_by = NULL` (tasks/handover.py:72), `task_collaborators.added_by = NULL` (:125), `project_members.added_by = NULL` (projects/handover.py:127,188), activity `actor=None` + `payload.action="SYSTEM_HANDOVER"` (:144-149). No sentinel dtuid anywhere.
- D11: no command touches `created_by_*`, comments, history rows, or `work_records.created_by_dingtalk_user_id`; existing target relations keep their `added_by`/`created_at` (projects/handover.py:137-140 only flips `role`; tasks/handover.py:118-119 only deletes the source row).
- M10 status invariants: `status` / `state_version` / `accepted_at` / review untouched; `assignment_version` +1 only on assignee change; `version` +1 at most once per command; `task_state_transitions` not written; no `TASK_REASSIGNED` notification.
- M13 OWNER ordering: delete old OWNER → flush → upgrade/insert target → sync `projects.owner_dingtalk_user_id` (projects/handover.py:101-143); old OWNER is deleted, never demoted; `project_member` selector excludes OWNER (:160); a target that is already OWNER is only merged, never role-mutated (:179-181).
- Lock ordering is honoured upstream: `HandoverServiceV2._lock_plan` (service.py:378-412) locks `project_ids | task_parent_project_ids` first, then tasks → templates → work_records → reminder rules, so M10's unlocked parent-project read is safe in the real path.
- Approval-lock semantics: both M13 and M10 split `PROJECT_LOCKED` into 409 (terminal) vs `HandoverTemporarilyLockedError`/423 (approval lock) per 08 §2.4.
- M18 correctly does not touch recurrence templates and correctly leaves MANAGER recipients as `$MANAGER` placeholders, so the manager-role natural keys survive the diff.

Out of shard but relevant to the reviewer of 37a5224: `_apply_plan` mis-attributes the per-asset-type summary because each `SystemHandoverResult` aggregates all roles of one aggregate — e.g. service.py:494 counts `transferred=max(0, result.transferred)` into `task_collaborator` even when that number came from the assignee/assigner transfer, and service.py:458-461 always reports `merged=0` for `project_member`. Contract §10.5 conservation checks on the EasyAuth side will see inflated `transferred` and lost `merged`.


## Shard: v2:c88be9f20ea7053b93c3e1cddec7884f150436b0f7194f9a2df8bc552eb5e071 — verdict: issues_found

### [major/confirmed] backend/tests/unit/handover/test_assets_registry.py:1
**114072c 用 67 行浅测替换了 250 行的 §3.1/§3.1.2 逐类覆盖，实测能力净损失，且 is_live_for_asset_type 变成零覆盖**

Evidence: `git show 114072c~1:backend/tests/unit/handover/test_assets_registry.py` 含：@parametrize 逐 asset_type 的 project/task/recurring/work_record 谓词断言、project_member 排除 OWNER 的交叉断言、`test_unknown_asset_type_raises`、以及 `test_count_criteria_matrix_summary` 的 13 条「活/死各一例」§3.1 全表口径矩阵。HEAD 版本只剩 4 个函数、67 行，全部改成对 `project_is_live/task_is_live/...` 的单点调用。被删测试的被测对象**并未消失**：`app/domain/handover/predicates.py:112` 的 `is_live_for_asset_type` 与 `PROJECT_SCOPED_TYPES/TASK_SCOPED_TYPES/RECURRING_SCOPED_TYPES/WORK_RECORD_SCOPED_TYPES` 仍在。`grep -rn --include='*.py' is_live_for_asset_type app tests` 除 predicates.py 自身外**零命中** —— 这个按 asset_type 分派的统一入口（含 `raise ValueError(f"unknown handover asset_type")` 分支）现在完全没有测试。05 §6 对该文件的要求是「9 类 count 口径（§3.1 全表逐类）；§3.1.2 终态谓词逐类断言」。

### [major/confirmed] backend/tests/contract/test_handover_v2_golden.py:28
**golden 契约测试从不与 EasyProject 的实际输出比对，只自检 SDK 样本文件本身，§6 要求的「逐字段比对」未实现**

Evidence: 全文件 5 个测试都只调用 `_load()` 读 SDK 包内 JSON，然后断言它自己是 dict / 含某几个 key。没有任何一处 import `app.domain.handover.service` 或构造 preview/items/execute 响应去比对。样本内容是 EasyTrade 口径（`customer` / `order_in_transit` / `inquiry_open`），与本仓库 9 类无关。后果：若 `HandoverServiceV2.preview` 把 `{"snapshot_token","assets"}`（service.py:105）改名，或 `items` 丢掉 `unfiltered_total`（service.py:158-166），本测试仍全绿。05 §6 原文是「从 easyauth_app_sdk.contract_samples 包内资源读取样本**逐字段比对**」。附带两处弱化断言：:53 的「兼容两种 golden」回退让 契约 §10.5 冻结的 `summary = {asset_type: 五元}` 形状没有被钉死；:38 `assert body.get("mode") == "preview" or "mode" in body` 对 `mode:"execute"` 同样通过，是一条恒真断言。（正面结论：「缺失必须 fail 不得 skip」这一条**满足** —— 实测缺文件 → `path.is_file()` False → AssertionError；缺子包 → ModuleNotFoundError；且在 scratchpad 里 `pip wheel` 打包该 SDK，`contract_samples/handover_v2/*.json` 6 个文件都进了 wheel，非 editable 安装路径也不会退化。）

### [major/confirmed] backend/tests/integration/handover/test_execute_transaction.py:8
**文件名与 §6 声称覆盖「事务内无网络调用；失败整体回滚」，实际两个测试都不涉及事务，且断言恒真**

Evidence: 整个文件 23 行、2 个测试：`test_system_handover_context_has_no_actor` 断言 `not hasattr(ctx, "actor")`（对一个 frozen dataclass 恒真，且和「actor 写 NULL」这条裁定毫无关系）；`test_result_shape` 断言 `SystemHandoverResult(transferred=1,...).transferred == 1`（构造即断言）。没有 session、没有 DB、没有回滚、没有网络桩。05 §6 表格该行要求「§4.5：事务内无网络调用；失败整体回滚」，AGENTS.md 不变量 4 是本仓库最硬约束之一，现零覆盖。

### [major/confirmed] backend/tests/integration/handover/test_idempotency.py:9
**§4.4 三条幂等行为规定与 05 §4.4 明文「必须有测试」的 generation=2→1 场景全部缺测**

Evidence: 文件只有 2 个纯函数单测：`handover_idempotency_key` 带 batch_id 后两个 key 不同、`canonical_payload_sha256` 与 key 顺序无关。05 §4.4 冻结的三条行为「同三元组同 hash → 返回首次 summary 200 不重复执行 / 同三元组不同 hash → 409 WEBHOOK_PAYLOAD_CONFLICT / generation 低于水位 → 409 HANDOVER_CONFLICT」一条都没测；05 §4.4 还有一句明确的「**必须有测试**：按 generation=2 → generation=1 的顺序投递，第二个请求返回 409 且零写入」，也没有。08 §2.3 的「execute 不在入口做水位拒绝、claim_or_replay 命中重放直接返回」与「ProcessingInProgressError→429 / IdempotencyConflictError→409 必须按异常类而非 code 分流」（实现在 app/api/v1/easyauth_lifecycle.py:83-90）同样零覆盖。

### [major/confirmed] backend/tests/unit/handover/test_items_pagination.py:1
**名为 items_pagination 的文件里没有任何分页测试；§6 明列的 total 两种口径与翻页不漏不重全缺**

Evidence: 文件 23 行，两个测试都只测 `compute_snapshot_token`（顺序无关、状态变化则 token 变）。05 §6 对该文件的要求是「排序稳定、连续翻页不漏不重；**total 的两种口径**：q="" 时等于 preview 的 count，q!="" 时等于过滤后的数量。不要写成『始终等于 preview count』」。实现里 `service.py:158-166` 恰好有一个 `"unfiltered_total": unfiltered if q.strip() else None` 的三元分支，以及 `HandoverReadRepository.list_items` 的 total/rows 分页，全部无测试。§4.3.3 的参数上界（page ≤ 100000、q 去空白后 ≤128 字节）也只在 test_lifecycle_handover.py:24 测了 page=0 与 page_size=201 两例，page 上界、q 超长、以及 `known_types` 不匹配触发 ASSET_TYPE_UNDECLARED 都没测（该参数在测试中从未传入非法值）。

### [major/confirmed] backend/tests/integration/authz/test_auth_me_and_endpoints.py:180
**本次提交删掉了唯一一个走通端点成功路径的端到端测试，未替代；现在没有任何测试对 handover 端点发出会返回 200 的请求**

Evidence: 114072c 把 `test_lifecycle_preview_and_execute_idempotent`（原来断言 preview 200 + execute 两次 200 且响应完全相同）改写成了 `test_lifecycle_bad_signature`，把原 bad_signature 改成 `test_lifecycle_event_type_mismatch`。`grep -rn 'lifecycle/handover' tests` 现在只命中这一个文件的两处，全是错误路径（401 / 422）。`app/domain/authz/app_factory.py:54` 的注释「测试默认服务无 DB；完整预览/执行测试自行注入 HandoverServiceV2」所指的那类测试并不存在 —— `grep -rn HandoverServiceV2 tests` 零命中。后果：端点→service→repo 的装配、`_map_domain_error` 的 12 条映射分支、成功体 JSON 形状、`read_bounded_body` 正常路径全部只靠两条错误分支间接触达。05 §5.2 新增的 10 个错误码里，只有 EVENT_MODE_MISMATCH 有测试；REQUEST_BODY_TOO_LARGE(413，且 §4.2 明文要求「测试同时覆盖伪造 Content-Length 与 chunked 超限」)、EVENT_UNSUPPORTED、ASSET_TYPE_UNDECLARED、SNAPSHOT_STALE(HTTP 层 412)、HANDOVER_TEMPORARILY_LOCKED(423)、RATE_LIMITED(429)、IDENTITY_UNMAPPED(HTTP 层 409)、WEBHOOK_TIMESTAMP_INVALID、WEBHOOK_PAYLOAD_CONFLICT 均无端点级测试（`grep` 全仓命中的都是 approvals/其它模块的同名码）。

### [major/confirmed] backend/tests/integration/handover/test_execute_composite_keys.py:29
**08 §2.1 的 actor NULL 与 D11「历史署名一律不改写 / 新建行 added_by=NULL」在全仓无任何断言，且最常见的「接收人原先不是成员」INSERT 路径未被 PostgreSQL 实跑**

Evidence: `grep -rn --include='*.py' -e actor_dingtalk_user_id -e changed_by_dingtalk_user_id -e added_by_dingtalk_user_id -e 'SYSTEM:EASYAUTH_HANDOVER' tests` 在全部 handover 测试里零命中。08 §2.1 冻结的四行取值（audit actor NULL + metadata_json.executor、task_activities actor NULL + payload_json.action=SYSTEM_HANDOVER、task_assignment_history.changed_by NULL、合并场景目标行 added_by「一个字节不动」/ 新建行 added_by NULL）没有一条被断言。唯一的集成测试只造了「接收人已是 MEMBER」这一种场景（:61-69 预置 to_uid 的 MEMBER 行），因此 `app/domain/projects/handover.py:121-128` 与 `:181-190` 那两条 `added_by_dingtalk_user_id=None` 的 INSERT 分支从未在真库上执行过 —— 而 05 §4.7 明文警告这正是「最常见」的交接场景，漏了迁移会当场 NotNullViolation 5xx。同理 `app/domain/tasks/handover.py:125` 的协作人 NULL INSERT 也未被执行。

### [major/confirmed] backend/tests/integration/handover/test_execute_composite_keys.py:83
**merged 的断言写成 `>= 0`，恒真；§4.3.2「merged 必须如实上报、不得并进 transferred」实际未被钉住**

Evidence: 测试场景（离职者 OWNER、接收人已是 MEMBER）在 `app/domain/projects/handover.py:129-138` 走的是 `merged = 1; transferred = 0` 分支，正确值是确定的 1。但断言是 `assert result.merged >= 0`，对任何 int 都成立。若实现把 merged 折进 transferred（正是 05 §4.3.2 点名禁止的「不得并进 transferred 掩盖」），本测试仍绿。另外 §6 要求该文件覆盖「§4.3 **四类**合并场景」，实际只有 ProjectMemberRow 一类；TaskCollaboratorRow / RecurringTemplateCollaboratorRow / WorkRecordParticipantRow 三类合并（含「直接删除离职者行、计入 merged」）零测试。

### [major/confirmed] backend/app/domain/handover/service.py:378
**08 §2.2/§2.3 的固定锁序（含「projects 集合必须并入待写 task 的父项目」与「幂等 claim 排在业务锁之前」）实现了但零测试**

Evidence: `_lock_plan`（service.py:378-411）按 projects→tasks→templates→work_records→reminder rules 顺序加锁，`execute` 在 :207-210 先锁 generation 水位再 claim_or_replay 再 `_lock_plan`。08 §2.2 的警告是：只锁 task 不锁其父项目会「让审批期间的写保护被穿透，而且不会返回 423」；08 §2.3 的警告是 claim 与业务锁顺序反了会产生「可复现的死锁」。这两条都有可观测效果（锁集合内容、加锁调用顺序），可用 spy/记录顺序的方式断言，但全仓无任何测试触及。同样地，六个领域 `system_handover` 命令中只有 projects 有测试：`grep -rln system_handover tests` 只命中 handover 目录下的 3 个文件；M10 tasks（status/state_version/accepted_at 不变、version+1、assignment_version+1、状态流转表不写）、M18 `refresh_after_system_handover` 的自然键三分支（05 §4.3.1 点名「不做这一步的后果是整组提醒静默全灭」）、M19 周期模板、M40 work_records participant、M32 outbox 全部零测试。

### [major/confirmed] backend/app/domain/authz/lifecycle.py:61
**v1 partial-success 的 HandoverService/InMemoryHandoverReceiptStore 仍留在树里，本次提交只删了它的测试，使被禁语义变成无人覆盖的死代码**

Evidence: `grep -rn --include='*.py' -e 'HandoverService\b' -e NullContributor -e InMemoryHandoverReceiptStore -e ContributorCount app tests | grep -v app/domain/authz/lifecycle.py` **零命中** —— 114072c 删掉 test_lifecycle_handover.py 里的 v1 测试、并从 test_auth_me_and_endpoints.py:23 移除 import 之后，该模块在 app/ 与 tests/ 中都不再被引用。模块里仍完整保留 `ContributorCount(..., failures=[...])`、`_aggregate` 的部分成功聚合（:138）、`InMemoryHandoverReceiptStore`（:50）与 v1 camelCase `parse_request`（:76）。05 §1 要求「删掉 v1 payload 解析、换掉内存幂等、去掉 partial-success…按 AGENTS.md『不保留历史错误形态』一次性替换，不留兼容分支」；契约 §10.5 要求整事务成败一致。现状是「测试删了、错误形态留着」。

### [minor/confirmed] backend/tests/integration/handover/conftest.py:28
**conftest.py 里的 `pytestmark = pytest.mark.integration` 是空操作，整个 handover 集成套件实际未打 integration 标记**

Evidence: pytest 只从测试模块/类上采集 `pytestmark`，conftest.py 上的赋值不会传播（需 `pytest_collection_modifyitems`）。实测：`pytest tests/integration/handover -m integration` → `no tests collected (5 deselected)`；`-m "not integration"` → 5 个全部收集，包括依赖真库的 `test_owner_transfer_upgrades_existing_member`。当前 CI（.github/workflows/ci.yml:70）与 quality-gate.sh:28 都跑无过滤的 `pytest -q`，所以今天不红；但任何按标记分层的执行都会静默漏掉整套交接集成测试，或把需要 PostgreSQL 的用例塞进 unit 通道。同理 tests/contract/test_handover_v2_golden.py 未打 `contract` 标记（同目录 tests/contract/easyauth/* 都显式写了 pytestmark）。

### [minor/confirmed] docs/design/09-分期计划与风险清单.md:230
**§3.4 的 WorkRecordRow 缺口已按要求登记（本项达标）；但同一份设计要求登记的 P1 MANAGED_USERS 偏差未登记**

Evidence: 新增的「## 数据交接 v2 已知缺口（2026-08-10）」小节（:230-247）完整写明 WorkRecordRow.created_by_dingtalk_user_id 不转移、接收人看不到也改不了、主管只能看到 work_record_participant 明细、后续需 owner 列+迁移+鉴权切换 —— 满足 05 §3.4/§7 的登记要求。缺的是 05 §1.1 与 §2.2 同样点名的另一项：「MANAGED_USERS 不消费 EasyAuth 快照…本期降级为已知偏差，不修…该偏差记入 docs/design/09-分期计划与风险清单.md」。`grep -n 'MANAGED_USERS|代管|managed_users'` 在该文件里只命中 :19 的 M1 里程碑表格，与本期偏差无关。

**Reviewer notes:** 范围：commit 114072c（测试 + 已知缺口文档）与整个 60d60d6..a22abad 区间的测试充分性。只读，未改动任何文件（唯一写入在 scratchpad：为验证 wheel 打包把 SDK 源码副本拷出去 build 了一次）。

已验证为**达标**的三项：
1. golden 样本确实走 `importlib.resources.files(\"easyauth_app_sdk.contract_samples.handover_v2\")`，不碰 `../EasyAuth/` 兄弟目录；缺失时是 fail 不是 skip（缺文件 → `assert path.is_file()` AssertionError；缺子包 → ModuleNotFoundError → ERROR）。尝试证伪的两条路径也都堵住了：backend/.venv 是 `__editable__.easyauth_app_sdk*.pth` 指向 vendor/src，样本可见；非 editable 路径我在 scratchpad 里 `pip wheel` 实际打了一次包，`[tool.setuptools.package-data] \"easyauth_app_sdk\" = [\"contract_samples/**/*.json\"]` 配合 `packages.find where=[\"src\"]` 把 6 个 JSON 全部装进了 wheel（`contract_samples/` 与 `handover_v2/` 都有 `__init__.py` 且已被 git 跟踪）。
2. §3.4 的 WorkRecordRow 缺口已写进 docs/design/09-分期计划与风险清单.md:230+（另附 OpenProject 异步投影债务）。
3. v1 partial-success 的**断言**确实被删干净了（不存在「为了让它绿而保留 partial success」的改错方向），且新增的 EVENT_MODE_MISMATCH 端点测试正确覆盖了 05 §5.2 那条安全补偿校验。

测试实跑：`backend/.venv/bin/python -m pytest tests/contract/test_handover_v2_golden.py tests/unit/handover tests/unit/authz/test_lifecycle_handover.py tests/unit/identity/test_handover_identity.py tests/integration/handover -q` → 46 passed；`tests/integration/authz/test_auth_me_and_endpoints.py` → 13 passed。真库在位，集成用例确有实跑（未被静默 skip）。加起来约 49，与「49-test 套件」的说法吻合。

对「49 个测试是否真的钉住了裁定语义」的总体判断：**没有**。真正被钉住的只有三块——身份解析（tests/unit/identity/test_handover_identity.py，13 个用例，含 §2.1 第 3 步「纯绑定不得写 first_login_at/last_login_at」的两条专测，质量好）、hint 逐类要素（tests/unit/handover/test_hints.py，含 ≤120 字符截断与未知类型 raise，质量好）、以及 task_id 的 `\"137:1\\n\"` / `\" 137:1\"` 拒绝（test_lifecycle_handover.py:16，正是 §4.4 的陷阱段）。剩下的裁定语义——actor NULL / D11 历史署名、锁序可观测效果、幂等三行为与 generation 倒序 409、412 与 409 的分工、423 按锁因分流、四类复合主键合并、六个 system_handover 命令的逐条保证——基本都停留在「构造即断言」或干脆没有。

05 §6 要求但当前缺失的具体用例清单（按文件）：
- test_assets_registry.py：9 类 count 口径全表逐类（被本次提交删除）；§3.1.2 谓词逐类 parametrize（被删）；未知 asset_type raise（被删）。
- test_items_pagination.py：排序稳定；连续翻页不漏不重；total 两种口径（q=\"\" == preview count / q!=\"\" == 过滤后）；page 上界 100000；q 去空白后 >128 字节 → 422；asset_type 不在注册表 → ASSET_TYPE_UNDECLARED 422。
- test_execute_composite_keys.py：TaskCollaboratorRow / RecurringTemplateCollaboratorRow / WorkRecordParticipantRow 三类合并；接收人原先**不是**成员/协作人的新建路径（added_by=NULL）；merged 精确值断言。
- test_execute_transaction.py：事务内无网络调用；中途失败整体回滚零残留。
- test_idempotency.py：同三元组同 hash 重放返回首次 summary 且不调领域命令；同三元组不同 hash → 409 WEBHOOK_PAYLOAD_CONFLICT；generation=2→generation=1 → 409 且零写入；同 generation 不同 batch 独立执行不互相重放；ProcessingInProgressError → 429 与 IdempotencyConflictError → 409 的按异常类分流。
- test_handover_v2_golden.py：preview/items/execute 响应与样本的逐字段比对。
- 端点层（无对应文件）：preview/items/execute 成功 200；256 KiB 上限的伪造 Content-Length 与 chunked 两种超限 → 413；EVENT_UNSUPPORTED；SNAPSHOT_STALE 412；HANDOVER_TEMPORARILY_LOCKED 423（审批锁）与项目终态 → 409 的分流；RATE_LIMITED 429。
- 领域层（无对应文件）：M10/M18/M19/M40/M32 五条 system_handover 命令的逐条保证，其中 M18 `refresh_after_system_handover` 的自然键三分支（原位保 PENDING / 旧行 SKIPPED+HANDOVER_SUPERSEDED / 新自然键 INSERT）优先级最高——05 §4.3.1 明写漏了是「整组提醒静默全灭，而且没有任何报错」。

优先级建议（若只能补三项）：① 端点成功路径 + generation 倒序 409 零写入（覆盖面最大、且是设计里唯一用「必须有测试」措辞点名的场景）；② M18 三分支；③ actor NULL / added_by NULL 的真库断言（顺带真正执行到那两条 NotNullViolation 风险路径）。另外建议把 test_assets_registry.py 恢复成 114072c~1 的版本——那一版本身就是达标的，删它没有任何被测对象消失作为理由。


## Shard: v2:f4f02f13a281714191e778d976ed639263a07305314b5f0aed188c241c66862e — verdict: issues_found

### [blocker/confirmed] backend/app/domain/recurrence/handover.py:48
**M19 transfers the template assignee onto a user who is already a template collaborator, leaving assignee ∈ collaborators — the invariant 08 §1.3 M19 explicitly names (domain/recurrence/service.py:215,381). Every subsequent generation of that template then fails permanently and silently.**

Evidence: Only the collaborator branch guards the overlap (`if collaborator_to == final_assignee: merged += 1`, lines 95-99). The assignee branch (44-50) writes `tpl.assignee_dingtalk_user_id = assignee_to` with no check against recurring_template_collaborators. Reachable and common: template assignee = A (departing), collaborators = {B}, handover A→B. A's only recurrence asset is recurring_assignee, so M06 (domain/handover/service.py:521-532) calls with assignee_to=B, collaborator_to=None → template ends assignee=B, collaborators={B}. Generation path: infra/jobs/recurrence_generate.py:197-221 loads collaborators verbatim and calls M10 create_from_command (domain/tasks/commands.py:1136 → _create), which raises assignee_cannot_be_collaborator() at commands.py:1236; recurrence_generate.py:170-178 marks the occurrence FAILED after max_attempts, and every later period produces a new occurrence that fails the same way — the template stops producing tasks forever with no user-visible error. 08 §1.3 states the set-level rule "合并后的 collaborator 集合不得包含最终 assignee". Fix: after the assignee branch, delete any collaborator row for the new assignee and count it merged. The identical hole exists in backend/app/domain/tasks/handover.py:64-66 (commit 30f680a, adjacent shard).

### [blocker/confirmed] backend/app/infra/jobs/openproject_handover_projection.py:76
**In the only production wiring (gateway always non-None) the worker moves every outbox row to CLAIMED and never touches it again: no reclaim of expired claims, no APPLY_FAILED, no op_sync_conflicts row, no alert. The OP person projection dies silently instead of being merely deferred.**

Evidence: run_once selects `WHERE status == 'PENDING'` only (lines 55-61); no branch re-claims expired CLAIMED rows and nothing else in the repo touches op_handover_projection_outbox. With a gateway the loop sets status='CLAIMED', claim_owner='handover-projection-worker' and leaves claim_expires_at NULL (76-77), so the row is unreachable by any future poll — including by a later correct PATCH implementation. composition.py:740-752 constructs the worker only inside _wire_openproject after the `ready` early-return, so `gateway` is never None there and the gateway-is-None branch (69-73) advertised by the docstring/commit message ("失败重试至 APPLY_FAILED") is dead code in every deployed configuration. Net effect: no operator surface at all, exactly the "看起来成功、实际什么都没发生" failure 08 §1.3 forbids ("不允许只写进台账就当没事"). Safer interim: leave rows PENDING, or CAS back to PENDING with backoff.

### [major/confirmed] backend/app/infra/repositories/op_sync.py:78
**m32_002 added op_sync_conflicts.handover_outbox_id plus its partial unique index, but the writer mandated by 08 §1.3 (record_handover_apply_failed(..., outbox_id)) does not exist, so retry exhaustion can never be recorded — while the risk list already claims it is.**

Evidence: Only the ORM column was added (op_sync.py:78); the repo's methods are get_stream/upsert_stream/record/list_unresolved/count_unresolved/list_streams/get_conflict/resolve/_find_unresolved — no handover writer, and the worker never references OpSyncConflict. 08 §1.3 bullet 6 requires "重试耗尽 → 写 M32 的 op_sync_conflicts（APPLY_FAILED）… m32_002 给该表加 handover_outbox_id … 新增 record_handover_apply_failed(..., outbox_id)", and §1.1 adds op_sync_conflicts to the writable-table list for exactly this. docs/design/09-分期计划与风险清单.md:245 asserts "重试耗尽写入 op_sync_conflicts" as if implemented — the ledger entry overstates the landed state.

### [major/confirmed] backend/app/domain/handover/service.py:541
**Summary double-counts a merged recurrence collaborator as transferred=1 AND merged=1, and folds a task's whole per-command transferred count into the task_collaborator bucket — breaking the five-tuple conservation EasyAuth checks (05 §4.3.2).**

Evidence: Lines 538-544 add SummaryCounts(transferred=1, merged=result.merged) unconditionally for every role present, so a template whose collaborator target already exists (or equals the final assignee) reports transferred=1 + merged=1 for a single asset; 05 §4.3.2 requires merged to be reported truthfully and never folded into transferred, and EasyAuth compares summary totals against item counts. Same class at line 494: summary['task_collaborator'].add(SummaryCounts(transferred=max(0, result.transferred), ...)) uses the command-wide result.transferred, which already includes that task's assignee and assigner transfers (domain/tasks/handover.py increments one shared counter per role), so a task transferring assignee+collaborator reports task_assigned=1 and task_collaborator=2. Landed in commit 37a5224 (adjacent shard) but it is the consumer of the SystemHandoverResult contract this shard produces.

### [minor/confirmed] backend/app/infra/jobs/openproject_handover_projection.py:58
**The claim query ignores next_attempt_at <= now and no code path ever advances next_attempt_at or sets claim_expires_at, so the frozen retry/lease columns are inert and there is no exponential backoff.**

Evidence: Lines 55-61 order by next_attempt_at but do not filter on it; the loop (67-77) never writes next_attempt_at or claim_expires_at. 08 §1.3 freezes attempts / next_attempt_at as "指数退避" and claim_owner / claim_expires_at as the worker lease, and requires owner-CAS on claim/renew/terminal updates plus "拿不到 task advisory lock 时，只由当前 owner CAS 回 PENDING 并设 next_attempt_at". As written, the dead gateway-None branch would burn its 8 attempts in 8 consecutive 30s ticks.

### [minor/confirmed] backend/app/composition.py:415
**execute enqueues an outbox row for every assignee/collaborator change even when the task has no OpenProject anchor or OP is disabled entirely — and when OP is disabled no consumer is registered at all, so rows accumulate unboundedly and the documented downgrade precondition can never be met.**

Evidence: _wire_handover_service (composition.py:385-430) always injects op_projection_enqueue=_op_enqueue, while the consumer JobSpec is registered only inside _wire_openproject after the `ready` early-return (composition.py:676-696, 743-752). enqueue (domain/openproject/handover_projection.py:53-54) writes the row regardless of op_work_package_id being NULL. 05 §4.7 and 08 §1.4 make "没有未消费的 OP outbox 行" a downgrade precondition for m32_002; 08 §1.3 allows SUPERSEDED for rows with no OP anchor, but nothing implements that either.

### [minor/confirmed] backend/app/domain/recurrence/handover.py:17
**No unit or integration test covers M19, M40, or the M32/M33 outbox+worker paths, so none of the frozen guarantees (merge counting, OPEN-only, created_by untouched, enqueue snapshot) is pinned.**

Evidence: grep over backend/tests for recurrence.handover / work_records.handover / handover_projection / OpHandoverProjection matches only tests/integration/handover/conftest.py, and only as metadata-registration imports (lines 18-24). tests/unit/handover holds assets_registry / hints / items_pagination; tests/integration/handover holds composite_keys / transaction / idempotency. 08 §1.5 requires each owner to deliver 实现/自测 with sign-off before A5 accepts the handoff; 05 §6 lists the required integration coverage.

### [minor/confirmed] backend/app/domain/openproject/handover_projection.py:25
**enqueue_system_handover_projection deviates from the signature frozen in 08 §1.3 — it drops the assignee_dingtalk_user_id / collaborator_dingtalk_user_ids parameters and re-reads them from the DB instead.**

Evidence: Frozen: (self, session, *, task_id, assignee_dingtalk_user_id, collaborator_dingtalk_user_ids, context) -> UUID. Landed: (session, *, task_id, context, now=None) re-selecting TaskRow and TaskCollaboratorRow (lines 33-45). Behaviourally equivalent today only because M10 flushes before returning (domain/tasks/handover.py:130) and SessionLocal is autoflush=False (core/database.py:48) so the collaborator read would otherwise be stale — correctness now rests on an implicit flush contract in the caller rather than on explicit arguments.

**Reviewer notes:** SCOPE: commits 1b30333 (M19), 88a109c (M40), e2bb06b (M32 outbox + m32_002), a22abad (M33 JobSpec). Checked against 05 §1.3/§3.1/§3.1.2/§4.5/§4.7/§5.7, 08 §1.1–§1.5 and §2.1–§2.6, 00 §11.1. Read-only; no files changed. Ran backend/.venv/bin/python -m pytest tests/unit/handover -q (15 passed) and an alembic smoke on a throwaway DB ep_review_smoke created on :55432 and dropped afterwards (easyproject_test / easyproject_smoke untouched): upgrade head and downgrade m46_001_record_task_order both clean; alembic heads = single head m00_004_dh2_heads.

WHAT IS CORRECT
- M40 (88a109c) follows the D11 explicit exception exactly: only work_record_participants rows are touched, created_by_dingtalk_user_id is never written (08 §1.1 "work_records: 不写 created_by"), predicate is status='OPEN' via the shared LIVE_WORK_RECORD_STATUS constant (05 §3.1.2), the record is locked FOR UPDATE, and target-is-creator is treated as merged (transferred=0, merged=1) rather than 409 — matching the 08 §1.3 M40 trap note that EasyAuth cannot know at preview time that the receiver created some of the records. Signature matches the frozen one. The gap is documented at docs/design/09-分期计划与风险清单.md:232-241 and was not silently "fixed". No finding.
- M19 (1b30333) moves exactly the three roles 05 §3.1 requires (recurring_assignee / recurring_assigner / recurring_collaborator), writes only the columns 08 §1.1 permits (assignee, assigner, version, updated_at + collaborator row delete/insert), locks the template FOR UPDATE, requires is_enabled, re-validates source role and target active inside the lock, bumps version exactly once, and touches neither historical occurrences nor notifications. Its one defect is the assignee↔existing-collaborator overlap (finding 1).
- m32_002 matches the frozen column list and the unique key (handover_task_id, generation, batch_id, task_id); it correctly avoids the trap column name handover_task_key_sha256 called out in 08 §1.4; the op_sync_conflicts FK plus partial unique index on non-null handover_outbox_id are present. Revision ids are shortened vs the docs (m32_002_op_handover_outbox vs m32_002_handover_projection_outbox, m06_003_handover_gen_wm, m00_004_dh2_heads) but are internally consistent, the merge carries all four parents and the head is single — cosmetic drift from 08 §1.4 / 05 §4.7, not a defect.
- JobSpec registration (a22abad) closes the 05 §5.7 gap ("不注册就没有消费者") using the same composition pattern as OPENPROJECT_SYNC_JOB; enqueue is in-transaction with zero network I/O (05 §4.5, AGENTS.md invariant 4); M06 enqueues only when assignee or collaborators changed, matching the two projected CFs.

EXACT OP-PROJECTION DEBT → DOC CLAUSES (all 08 §1.3 "M32 / M33 · OpenProject 投影" unless noted)
1. CF PATCH of cf:assignee_dtuid + cf:collaborators_dtuid and the post-success short-transaction anchor update of tasks.op_lock_version / op_synced_at — bullet 5, 08 §1.1 tasks.op_lock_version/op_synced_at row, 05 §4.5 ③. NOT IMPLEMENTED.
2. task_lock_key(task_id) advisory lock shared with the ordinary write-through — bullet 2. NOT IMPLEMENTED.
3. Version guard on assignment_version + collaborators_hash, including the trap that task.version is diagnostic only and must never alone trigger SUPERSEDED — bullet 3 and the "没有版本护栏会发生什么" callout. Columns are populated at enqueue; nothing reads them. NOT IMPLEMENTED.
4. SUPERSEDED / CANCELLED transitions (only when the task is deleted, has no OP anchor, or a newer outbox row takes over) and "人员已前进时取锁内当前本地权威值" — bullet 3. NOT IMPLEMENTED.
5. Owner-CAS on claim and on every renew/retry/APPLIED/SUPERSEDED/APPLY_FAILED update (WHERE id=? AND status='CLAIMED' AND claim_owner=?), lease renewal across a long HTTP call, "CAS 影响 0 行的旧 worker 不得写任何终态或冲突账", and CAS-back-to-PENDING when the advisory lock is unavailable — bullet 4. NOT IMPLEMENTED, and the landed claim is worse than absent (finding 2).
6. Exponential backoff via attempts / next_attempt_at and the lease via claim_expires_at — frozen column table. NOT IMPLEMENTED (finding 5).
7. Retry exhaustion → op_sync_conflicts APPLY_FAILED row deduped by outbox_id via new record_handover_apply_failed(..., outbox_id) — bullet 6 + 08 §1.1 op_sync_conflicts row. Schema landed, writer NOT IMPLEMENTED (finding 3).
8. Redrive endpoint POST /api/v1/admin/openproject/handover-projections/{outbox_id}/redrive (APPLY_FAILED→PENDING, clear claim_owner, reset next_attempt_at, write audit) — 08 §1.3 delivery table row 1. NOT IMPLEMENTED. Note it is a new operation, so it also needs a contracts/openapi-baseline.json entry via AG-00; CCR 09 covers only the handover endpoint's x-error-codes, so this is an unscheduled gate, not just unwritten code.
9. Batch query GET .../handover-projections?status=APPLY_FAILED with triple + task info — table row 2. NOT IMPLEMENTED (same baseline caveat).
10. Immediate alert on retry exhaustion ("不是等人去翻台账") — table row 3. NOT IMPLEMENTED.
11. Runbook in docs/runbooks/ (how to detect / how to redrive / what if redrive still fails) — table row 4. NOT IMPLEMENTED (docs/runbooks/ has openproject-{backup-restore,bootstrap,cutover,token-rotation,upgrade}.md, nothing for handover projections).
12. Risk-list registration — 05 §7 / 08 §1.3 ("必须写进 EasyProject 的风险清单"). PRESENT at docs/design/09-分期计划与风险清单.md:243-247 but inaccurate: it says retry exhaustion writes op_sync_conflicts, which item 7 shows it does not.

IS THE LANDED SKELETON SAFE TO DEPLOY?
Local data: yes — no corruption path. execute writes only the outbox inside the business transaction, makes no network call under lock, rolls the whole transaction back on failure, and the outbox row carries only a snapshot (nothing is back-written to business columns). M40/M19 writes stay inside their frozen column allowlists; no partial success is possible.
OP projection: NOT merely "deferred". Two states, neither self-healing: (a) OP enabled — the job is registered and parks every row in CLAIMED with a NULL lease where no current or future poll can find it; there is no APPLY_FAILED row, no op_sync_conflicts entry, no alert and no redrive API, so recovery needs hand-written SQL and someone first noticing OpenProject still shows the departed employee (M34 reconcile explicitly never repairs person fields, reconcile.py:4). (b) OP disabled — no consumer is registered, rows pile up as PENDING and permanently block the m32_002 downgrade precondition.
Verdict: the handover itself can ship, but the OP projection worker is a blocker for any OP-enabled deployment. Minimum pre-push fix set: (i) fix the M19 (and sibling M10) assignee/collaborator overlap; (ii) make the worker leave rows PENDING or CAS them back with backoff instead of parking them in CLAIMED, so no row is silently consumed before the real apply path lands; (iii) correct the risk-list wording to describe the actual landed state and register items 1-11 as tracked debt with an owner rather than prose.


## Shard: v2:b6c6f86ec1fd2f5a55e63928caad22dbd25bf1f05c62e34a091261dbe8810e35 — verdict: issues_found

### [blocker/confirmed] backend/app/domain/handover/service.py:460
**project_member 合并场景在 summary 中完全消失：merged 被硬编码为 0，transferred 也是 0，该条资产不进五元中的任何一格，直接违反契约 §10.5 的守恒公式。**

Evidence: _apply_plan 对 project_member 写的是 SummaryCounts(transferred=..., merged=0)。M13 的 _transfer_member（domain/projects/handover.py:179-181）在「接收人已是该项目成员/OWNER」时返回 (transferred=0, merged=1) —— 这正是 05 §4.3 表格里列为正常路径的合并场景。用真实返回值驱动 _apply_plan 实测：project_member (merge case): {'transferred': 0, 'released': 0, 'skipped': 0, 'merged': 0, 'failed': 0}，而 preview 对该类型的 count 是 1。契约 §10.5 守恒公式要求 transferred+released+skipped+merged+failed == 该类型在本批 snapshot_token 对应 preview 的 count，「EasyAuth 会校验，不满足则把 action 判为 failed 并展示差额」。更糟的是数据已经写成功并 commit、三元组幂等记录已落库，§10.5.1 明说「同一幂等键重试只会重复返回那份错误 summary」，该 action 永久 failed，按 D13 整张交接单再也到不了 completed。05 §4.3.2 另有一句「merged 是复合主键合并的正常结果，必须如实上报」——这里连报都没报。

### [blocker/confirmed] backend/app/domain/handover/service.py:496
**task_collaborator 用的是任务级聚合 result.transferred（含 assignee/assigner 的计数），同一任务上离职者既是 assigner 又是协作人时该类型会多报。**

Evidence: M10 的 system_handover（domain/tasks/handover.py）对 assignee、assigner、collaborator 三段各自 transferred += 1 后返回一个聚合值；_apply_plan 却把该聚合值整个记到 task_collaborator 名下：SummaryCounts(transferred=max(0, result.transferred), merged=result.merged)。实测：assigner+collaborator 同任务、领域命令返回 transferred=2 时输出 task_assigner {'transferred': 1,...}、task_collaborator {'transferred': 2,...}，协作人这一类 preview count 为 1 却报 2；三个角色齐全时报 3。该状态完全可达——domain/tasks/commands.py:1236 只禁止 assignee ∈ collaborators，assigner（创建人）兼协作人是允许且常见的。后果同上：契约 §10.5 守恒校验失败 → action 判 failed，幂等重放永远返回同一份错误 summary。

### [blocker/confirmed] backend/app/domain/handover/service.py:538
**recurring_* 三类无条件计 transferred=1，协作人合并时又叠加 merged，一条资产被记成两条。**

Evidence: 循环体是 SummaryCounts(transferred=1, merged=result.merged if role_field == 'collaborator' else 0)，transferred 与 merged 没有互斥。实测：M19 命令返回 (transferred=0, merged=1) 的合并场景下输出 recurring_collaborator: {'transferred': 1, 'released': 0, 'skipped': 0, 'merged': 1, 'failed': 0}，合计 2 而 preview count 为 1；正确值是 transferred=0, merged=1。同样触发契约 §10.5 守恒失败 → action failed 且不可通过重试自愈。

### [major/confirmed] backend/app/domain/handover/service.py:354
**overrides 的「快照外 asset_id」409 判定发生在锁内全量摘要重算之前，preview 之后的普通归属竞态会先命中 409 而不是契约冻结的 412。**

Evidence: execute 顺序为 line 230 _build_execute_plan（内含 line 354-355：oid not in live_ids → HandoverConflictError → API 映射 409）→ line 251 _lock_plan → line 254-256 才重算 snapshot_token 抛 SnapshotStaleError(412)。live_ids 是本次锁前的实时读，preview 之后被别人改派掉的对象已不在其中。00 §10.5.1 第 4 条把顺序连同处置一起冻结：「校验顺序是规范的一部分：必须先比摘要、后逐条」「归属在 preview 之后发生变化的一律走 412，不得用 409 表达」；08 §2.2 复述为「M06 必须在调用任何领域命令之前、在锁内完成全量摘要重算并以 412 短路」。按 §10.6，409 在 EasyAuth 侧是不可重试的 failed（界面只剩「应用拒绝了本次交接」），412 才退回 pending 重新预演——正是文档反复警告的陷阱。同一顺序问题还有第二处实例：_lock_plan（line 388-389）在 token 重算之前对「preview 后变终态的项目」抛 409。

### [major/confirmed] backend/app/domain/handover/service.py:263
**审计把 08 §2.1 冻结的固定字段写进 after_json，metadata_json 留空，system actor 的唯一标识位 metadata_json.executor 实际不存在。**

Evidence: audit_writer.record(...) 只传 before=None / after={executor, trigger_system, handover_task_id, generation, batch_id, delivery_id, kind, from_user_id, to_user_ids, summary}，没有传 metadata=。AuditWriter.record（infra/repositories/reliability.py:165-200）的 metadata 是独立可选参数，未传即 metadata_json=NULL。08 §2.1 的表格与「审计 metadata_json 的固定字段」JSON 块都把这批字段定在 metadata_json 上，05 §4.5 ① 同样写「执行者身份放进 metadata_json.executor」。这不是位置偏好：该裁定明确否决哨兵 dtuid，代价就是 actor_dingtalk_user_id=NULL 加 metadata_json.executor 作为识别系统执行者的唯一手段，写错位置后按 executor 过滤交接审计的查询一条都查不到。

### [major/confirmed] backend/app/domain/projects/handover.py:167
**接收人 == 来源人时 project_member 交接会删除成员行且报成 merged —— 人被静默移出项目；M06 编排层也没有 08 §2.5 要求的「接收人不是来源本人」校验。**

Evidence: _transfer_member 先在 line 167-174 查 target（to_dtuid==from_dtuid 时命中的就是 source 那一行），line 176 才 session.delete(source)，line 179 判断 target is not None → 返回 (0,1)。结果：成员行被删、没有新行插入，接口 200 且报 merged=1，此后该用户看不到这个项目（可见性只看成员行是否存在，infra/repositories/project_queries.py:115）。08 §2.5「绝不豁免」清单写明「接收人能精确映射为 dtuid、仍 active、且不是来源本人」，而 service.py 的 _build_execute_plan / _apply_plan 全程没有 to_dtuid != from_dtuid 判断，各领域命令的 _require_active 也只查在职。上游 EasyAuth 会先拦（§10.5 前置条件），但这条被裁定列为下游不得豁免，且失手后果是数据丢失而非报错。

### [major/plausible] backend/app/domain/handover/service.py:431
**未出现在 assignments 里的 asset_type 一律输出全 0，而契约把「缺席 ≡ default_action=skip」并要求 skipped 等于该类型的 preview count。**

Evidence: summary 初始化为全部 9 类（line 431-434），但 skipped 只在 _build_execute_plan 的 assignments 循环里累加（line 362-364）；assignments 中不存在的类型永远是 {0,0,0,0,0}。00 §10.5 语义第 4 条「未出现在 assignments 中的 asset_type 等价于 default_action=skip」，守恒公式紧接着规定「口径固定为全量：右边是该 asset_type 在本批所用的那个 snapshot_token 对应的 preview 里返回的 count，与 default_action 取什么值无关。被 skip 的条目计入 skipped」。只要 EasyAuth 省略了一个 count>0 的类型，EasyProject 报 0 而 preview count 为 N，差额 N → action failed。判 plausible 是因为它取决于 EasyAuth 是否真会省略非零类型（EasyAuth 侧 rollup 尚未实现，无法在本仓库外验证）。

### [major/confirmed] backend/app/infra/repositories/handover_generations.py:41
**generation 水位行的建行竞态与 REPEATABLE READ 下的加锁写，都会把重复投递变成 500（EasyAuth 侧记 failed）。**

Evidence: lock_or_create 在 row is None 时直接 session.add + flush，没有 ON CONFLICT / savepoint：同一 task_id 的首两次并发投递（preview 重投，或 preview 与 execute 并行）第二个会在主键上拿到未捕获的 IntegrityError → 整个请求 500。第二个机制：preview（service.py:90）与 items（:138）把事务设为 REPEATABLE READ 后仍调用 lock_or_create（SELECT ... FOR UPDATE + INSERT/UPDATE 水位）；PostgreSQL 在 RR 下对「快照之后被其他已提交事务改过的行」做 FOR UPDATE 会抛 40001 could not serialize access due to concurrent update，同样 500 收场。05 §4.3.3 要求 preview/items 跑在 REPEATABLE READ READ ONLY 事务里，在只读事务中做加锁写本身即与该规定相悖（真加上 READ ONLY 会当场报错）。按 §10.6，5xx 让 action 判 failed。

### [minor/confirmed] backend/app/domain/handover/service.py:365
**action="release" 返回 409 HANDOVER_CONFLICT，契约规定的是 422。**

Evidence: _build_execute_plan line 365-366：if action == 'release': raise HandoverConflictError('本应用不支持 release') → API 映射 409。00 §10.5 语义第 5 条：「下游仍应做防御性校验：action="release" 落在 releasable=false 的类型上时返回 HTTP 422，不得静默改成保持原状」。两者在 §10.6 里都判 failed 且不可重试，影响有限，但界面文案不同（422「应用声明与实现不一致」vs 409「应用拒绝了本次交接」），且这是逐字冻结的状态码。

### [minor/confirmed] backend/app/domain/handover/service.py:74
**items 的 300 秒缓存是进程内 dict 且永不清理，既漏内存又在多实例部署下失效。**

Evidence: _items_cache: dict[str, tuple[float, dict]] 只在 line 166 写入、line 126-128 读取，没有任何过期项淘汰——每个不同的 body 指纹都会永久留一份响应体在内存里。它与 _items_inflight 都是 per-process，05 §4.3.3「验签后按签名覆盖的 body 指纹做 300 秒响应缓存或 single-flight，超限返回 429 RATE_LIMITED」在多副本部署下等于按副本数放大了读放大防护的阈值。

### [minor/confirmed] backend/app/domain/handover/errors.py:47
**各领域命令的「来源已非 assignee / 已非项目成员」兜底错误继承 HandoverConflictError（409），M06 没有按裁定转译成 412。**

Evidence: ProjectHandoverConflict / TaskHandoverConflict / RecurrenceHandoverConflict / WorkRecordHandoverConflict 全部继承 HandoverConflictError（status_code=409），service.py 的 _apply_plan 直接让它们冒泡到 API 层映射 409。08 §2.2 结尾：「§1.3 各条签名里领域命令内部的『来源不再匹配 / 不再满足谓词』只是兜底，M06 收到后仍按 412 上报，不要原样透传成 409。」实际触发概率低（锁内摘要重算通常先命中 412），但同一批 exception 里也混着本该是 409 的「接收人未在职」，一旦兜底真的生效，处置方向是相反的。

### [minor/confirmed] backend/tests/integration/handover/test_idempotency.py:1
**05 §4.4 点名「必须有测试」的 generation=2 → generation=1 顺序投递（第二个 409 且零写入）用例缺失，整个 execute 端到端路径无集成覆盖。**

Evidence: test_idempotency.py 只有两个纯函数单测（幂等键含 batch_id、canonical hash 与 key 顺序无关），没有任何走 HandoverServiceV2.execute 的用例；test_execute_transaction.py 也只断言 dataclass 形状。05 §4.4：「必须有测试：按 generation=2 → generation=1 的顺序投递，第二个请求返回 409 且零写入。这不是理论场景」。summary 守恒、412/409 顺序、幂等重放同 summary 三条主路径同样零覆盖——上面三条 blocker 能一路走到 pre-push 正是因为这个缺口。

### [minor/confirmed] backend/alembic/versions/m00_004_dh2_heads.py:11
**merge revision 的 id 与 05 §4.7 / 08 §1.4 冻结的 m00_004_data_handover_v2_heads 不一致（m06_003 / m32_002 同样被改名）。**

Evidence: revision = 'm00_004_dh2_heads'，四个 down_revision 也是 m06_003_handover_gen_wm / m32_002_op_handover_outbox 等短名，而裁定表写的是 m00_004_data_handover_v2_heads / m06_003_handover_generation_watermarks / m32_002_handover_projection_outbox。机制上健全：ScriptDirectory.get_heads() 实测只剩 ['m00_004_dh2_heads']，四个 parent 齐全，upgrade/downgrade 均为空（merge 的正确形态），集成 fixture 的 alembic upgrade heads 在空库上通过。但裁定给的 m06_003_handover_generation_watermarks 长 38 字符、m32_002_handover_projection_outbox 长 34 字符，都超过 alembic 默认 alembic_version.version_num 的 VARCHAR(32)，原名根本用不了——应由 AG-00 修订裁定表，而不是让实现与冻结文档默默分叉。另：08 §1.6 把 merge revision 的创建权保留给 AG-00，本提交作者是 AG-05。

**Reviewer notes:** 分片结论（37a5224 及其承接的 M06 execute 编排——编排主体在 0aa1678 引入的 domain/handover/service.py，按分片要求一并审）。

判对的部分：① 身份解析确实全在事务外（execute 先 _resolve_identity 再进 session_factory，service.py:188-192 vs :205），resolve_handover_identity 走自己的短 session；② 锁序与 08 §2.2 逐条一致：generation 水位行 → IdempotencyGuard.claim_or_replay → projects（含所有待写 task 的非空 project_id，service.py:240-248 专门补了这一集合）→ tasks → templates → work_records → task_reminder_rules，全部 UUID 升序；③ snapshot 不匹配 → SnapshotStaleError → 412（items 同样 412），且在调任何领域命令之前短路；④ system actor 一律 NULL（audit actor、task_assignment_history.changed_by、新建关系行 added_by），无哨兵 dtuid；⑤ 幂等重放安全：同三元组 COMPLETED 走 replay 返回原 summary，PROCESSING 因 wait_for_completion=False 抛 ProcessingInProgressError→429（不会返回空 summary），hash 不同 → IdempotencyConflictError→409 WEBHOOK_PAYLOAD_CONFLICT；claim 与业务写在同一事务，异常即整体回滚，迟到 generation 的 409 也是零写入；⑥ 部分失败语义正确：failed 恒为 0，无逐条兜底跳过，任何领域错误都整事务回滚；⑦ OP 投影 outbox 用同一个 session 在业务事务内入队（composition.py 的 _op_enqueue → enqueue_system_handover_projection(session, ...)），事务内不发任何网络请求；⑧ composition.py 注入的六个 owner 命令 + audit_writer 的关键字签名与各领域实现逐个对得上，app.state.handover_service 与 API 层读取的 key 一致；⑨ 四 head merge 机制健全（见 findings 末条）。

关于「per-type 计数是近似值」这个自述：
1) 有条款要求精确。00 §10.5 的守恒公式是硬约束——transferred+released+skipped+merged+failed 必须逐类型等于该批 snapshot_token 对应 preview 的 count，「EasyAuth 会校验，不满足则把 action 判为 failed 并展示差额」；merged 还被单列「必须与 transferred 分开报」，05 §4.3.2 复述为「必须如实上报，不得并进 transferred 掩盖」。近似不是可接受的实现自由度。
2) 但作者自陈的那个场景（同一项目同时转 owner 与 member）实际不可达：project_member 谓词排除 OWNER 行（predicates.py:33、repositories/handover.py:110），project_owned 取 ProjectRow.owner，加上 policies.validate_member_shape（domain/projects/policies.py:201-207）强制「恰好一个 OWNER 且必须是 projects.owner」，同一个人不可能在一个项目里既是 ProjectRow.owner 又持非 OWNER 成员行。真正在跑的是三个可达得多的错法——project_member 合并全丢、task_collaborator 吃掉任务级聚合（assigner 兼协作人完全合法）、recurring 协作人合并被双计。自述把风险定位错了对象，实际缺陷比自述严重。
3) 对 EasyAuth 侧 rollup 的影响不是 D6/blocked。D6/blocked 只判「APP 有没有声明 handover.v2」，与 summary 无关；错误 summary 的路径是守恒校验失败 → 该 action 判 failed，再按 D13「存在任何 blocked/pending/failed 即未完成」把整单卡住。最要命的是不可自愈：数据已 commit、三元组幂等记录已落库，§10.5.1 明说「同一幂等键重试只会重复返回那份错误 summary」，只能由 EasyAuth 起新 generation 重来，而新一轮 preview 里这些资产已不在离职者名下，差额再也对不平。建议把三条 blocker 当作上线阻断项。

未改动任何文件；仅在 scratchpad 写了只读探针 /private/tmp/claude-501/-Users-konata/25e64908-6fe5-439e-9b58-2ae0856ba202/scratchpad/check_summary.py，用真实领域返回值驱动 _apply_plan 复现三条计数缺陷。已跑 backend/.venv/bin/python -m pytest tests/integration/handover tests/unit/handover -q → 20 passed（含 alembic upgrade heads 空库冒烟，:55432 测试库数据未破坏）。


## Shard: v2:9ff222921b282187f5ec60b40070e984256caeab0718b0bf96c2a58e3ce0be4c — verdict: issues_found

### [blocker/confirmed] contracts/permissions.json:3
**613eaee edited docs/design/easyproject-manifest.draft.json + easyproject_manifest.json (adding lifecycle.handover_asset_types) without refreshing contracts/permissions.json.sourceSha256 — the backend test suite and the contract gate are both red on main right now.**

Evidence: `backend/.venv/bin/python -m pytest tests/unit/authz -q` → 1 failed: tests/unit/authz/test_manifest_consistency.py:37 `assert baseline["sourceSha256"] == manifest_file_sha256()` → expected b0a219d4cbab…, file has 4dc5bc7891eb…. Independently: `python3 scripts/check_permissions.py` → `FAIL: manifest 哈希漂移: easyproject-manifest.draft.json sha256=b0a219d4cbab... != permissions.json sourceSha256=4dc5bc7891eb...`, exit=1. `git show 60d60d6:docs/design/easyproject-manifest.draft.json | shasum -a 256` = 4dc5bc7891eb… (was in sync before the commit). scripts/quality-gate.sh runs pytest (step 3) and check_permissions.py (step 6) under `set -e`, so both stages fail. permissions.json is an AG-00 shared-hot file (05 §5.7 / contracts/ownership.md 共享热点), so the fix is a patch to AG-00, not a silent edit — but it must land before push.

### [major/confirmed] backend/app/domain/handover/assets.py:117
**The served descriptor does NOT share a constant with the asset registry: handover_asset_types is hand-copied into easyproject_manifest.json, and descriptor_handover_asset_types()/lifecycle_manifest_section() are never called by production code — so registry↔descriptor drift is silent, exactly what 05 §4.6 forbids.**

Evidence: `grep -rn 'lifecycle_manifest_section|descriptor_handover_asset_types' backend/app` returns only assets.py itself and the re-export in domain/handover/__init__.py; the only caller is tests/unit/handover/test_assets_registry.py:27-31, which asserts the helper against itself. The real descriptor path is api/v1/easyauth_descriptor.py:60 → domain/authz/manifest.load_manifest() → the literal JSON at backend/app/domain/authz/easyproject_manifest.json:2239. No test compares that JSON to HANDOVER_ASSET_TYPES (`grep -rln handover_asset_types backend/tests` → only test_assets_registry.py). Failure: add/rename/remove a type in HANDOVER_ASSET_TYPES (or flip detail_supported) and preview emits a `type` the descriptor never declared → EasyAuth returns `422 undeclared_asset_type` and marks the action `failed` (00 §10.3), with nothing in CI catching it. 05 §4.6 requires the rows be 由 §4.1 注册表生成（与 preview/items/execute 共用同一常量，杜绝漂移）.

### [major/confirmed] backend/app/domain/handover/service.py:90
**preview/items run in a REPEATABLE READ transaction that takes SELECT … FOR UPDATE on (and writes) the shared easyauth_handover_generations row; a concurrent watermark advance makes PostgreSQL abort with SQLSTATE 40001, which nothing catches → HTTP 500.**

Evidence: service.py:90/138 set `isolation_level=REPEATABLE READ`, then HandoverGenerationRepository.lock_or_create() (infra/repositories/handover_generations.py:32-58) issues `.with_for_update()` and advance_if_needed() UPDATEs the same row. Reproduced against easyproject-test-db (scratch DB, dropped afterwards): tx A `BEGIN ISOLATION LEVEL REPEATABLE READ; SELECT g FROM wm WHERE k='t';` … tx B `UPDATE wm SET g=5; COMMIT;` … tx A `SELECT g FROM wm WHERE k='t' FOR UPDATE;` → `ERROR: could not serialize access due to concurrent update`. Concrete trigger: EasyAuth fires items for several of the 9 detail_supported types (or preview and execute) for the same task_id concurrently; the first advances the watermark, the others 500 → EasyAuth records failed/non-retryable. Second failure mode in the same function: the first-ever concurrent pair both miss the row and both INSERT — lock_or_create has no ON CONFLICT and no savepoint, so IntegrityError poisons the transaction. Per spec this write does not belong here at all: 05 §4.4 puts the generation watermark in execute, and 05 §4.3.3 requires preview/items to be REPEATABLE READ READ ONLY (the code omits READ ONLY precisely because it writes).

### [major/confirmed] backend/app/domain/handover/service.py:303
**_resolve_identity silently treats the raw Authentik sub as a local dtuid whenever the directory port is unwired, so preview answers with nine zero counts and execute is a no-op 200 — the exact silent-empty-stats outcome 05 §2.1 forbids.**

Evidence: service.py:302-307: `if self.directory is None or self.user_repo_factory is None: … return sub` (comment 测试/本地). composition.py:435-436 sets `directory_port = create_directory_adapter(ea_config) if ea_config else None`, and _easyauth_config() (composition.py:115-118) returns None whenever EASYAUTH base_url or app_token is missing; composition.py:420 then passes `user_repo_factory=… if directory_port is not None else None`. Result: with the webhook secret set but EasyAuth base_url/token unset, a signed preview resolves from_user_id=<uuid sub> as a dtuid, every count query matches nothing, and EasyProject reports “no data for this employee” with HTTP 200. 05 §2.1: 禁止静默跳过或返回空统计 — unresolvable subs must raise IdentityUnmappedError → 409 IDENTITY_UNMAPPED. The test shortcut belongs in the test factory (app_factory.py), not in the production service.

### [major/confirmed] backend/tests/unit/handover/test_items_pagination.py:1
**The §6-mandated preview/items coverage does not exist: the pagination test file contains only two snapshot-token ordering asserts, there is no 256 KiB body-bound test, and no preview/items endpoint test at all.**

Evidence: test_items_pagination.py is 23 lines and only calls compute_snapshot_token(); 05 §6 requires this file to cover 排序稳定、连续翻页不漏不重；total 的两种口径（q="" 时等于 preview 的 count，q!="" 时等于过滤后的数量）. Nothing exercises HandoverReadRepository.list_items (infra/repositories/handover.py:66-81), whose Python-side slicing and per-type count/items query pairs are exactly where a q="" total ≠ preview count divergence would appear (EasyAuth's conservation check then judges the action failed). Likewise `grep -rn 'REQUEST_BODY_TOO_LARGE|read_bounded_body' backend/tests` → no hits, although 05 §4.2 requires 测试同时覆盖伪造 Content-Length 与 chunked 超限. The only endpoint tests are tests/integration/authz/test_auth_me_and_endpoints.py:199-249 (bad signature → 401, event_type mismatch → 422); no preview/items/execute request ever reaches the endpoint in a test.

### [minor/confirmed] backend/app/api/v1/easyauth_lifecycle.py:147
**delivery_id is read from a non-existent header name, so SystemHandoverContext.delivery_id and the audit record's delivery_id are always the empty string.**

Evidence: `delivery_id = headers.get("x-easyauth-delivery-id") or ""`, but the wire header is `X-EasyAuth-Delivery` (SDK webhook.py:25 DELIVERY_HEADER, tests/helpers/hmac_signing.py:39, app/api/v1/easyauth_webhooks.py:128 all use it). The already-parsed `event.delivery_id` was available two lines above. Effect: every SYSTEM_HANDOVER audit row written at service.py:279 records `"delivery_id": ""`, destroying the only link back to EasyAuth's delivery ledger during incident triage.

### [minor/confirmed] backend/app/api/v1/easyauth_lifecycle.py:84
**429 RATE_LIMITED responses carry no Retry-After header, although both the contract and this repo's frozen error vectors say that code returns one.**

Evidence: _map_domain_error builds `AppError(code="RATE_LIMITED", status_code=429)` and app/core/errors.py:48-63 has no header channel; the AppError handler emits only the ErrorBody JSON. contracts/test-vectors/error-bodies.json httpMap: `"429": ["RATE_LIMITED（返回 Retry-After）"]`, and 00 §10.6 / 09 §5.2 say EasyAuth 按 Retry-After 重试. Without the header EasyAuth falls back to its own backoff, and the items 300s single-flight window (service.py:129-132) is not communicated at all.

### [minor/confirmed] backend/app/domain/handover/service.py:74
**_items_cache grows without bound — entries are keyed by the SHA-256 of the whole request body and are never evicted, only TTL-checked on read.**

Evidence: `_items_cache: dict[str, tuple[float, dict]]` (service.py:74) is written at service.py:166 and only ever read at :126-128; no eviction, no size cap, and the service is a process-wide singleton (composition.py:431). Every distinct signed items body (page, page_size, q, snapshot_token all vary) adds a permanent entry holding a full page of rendered items. On a webhook endpoint whose bodies are attacker-influenceable within the 300s replay window this is a slow memory leak.

### [minor/confirmed] backend/alembic/versions/m06_003_handover_gen_wm.py:16
**Migration revision id deviates from the AG-00-frozen id, which contracts/ownership.md says the implementation table must match line-for-line.**

Evidence: revision = "m06_003_handover_gen_wm"; contracts/ownership.md:796 and 08 §1.4 freeze `m06_003_handover_generation_watermarks` (and ownership.md:806 lists it as a down_revision of the merge). backend/alembic/versions/m00_004_dh2_heads.py:13-18 therefore also lists shortened ids (m00_004_dh2_heads, m32_002_op_handover_outbox) instead of the frozen m00_004_data_handover_v2_heads / m32_002_handover_projection_outbox. `scripts/check_migrations.py` passes (single head m00_004_dh2_heads), so this is a documentation/traceability divergence rather than a broken chain, but any cross-repo doc or runbook that greps the frozen id will miss it.

### [minor/confirmed] backend/app/domain/handover/service.py:164
**items emits `"unfiltered_total": null` when q is empty instead of omitting the optional field.**

Evidence: `"unfiltered_total": unfiltered if q.strip() else None`. 00 §10.4 defines unfiltered_total as 可选字段 and the SDK golden sample (contract_samples/handover_v2/items_response.json) only ever carries an integer. A null for an optional integer field is a needless deviation for any consumer that type-checks the field before using it as a consistency hint.

### [minor/confirmed] backend/app/infra/repositories/handover.py:77
**list_items materializes the entire filtered result set and slices it in Python, so every items page pays a full scan plus a second full count, on top of the 9-type snapshot materialization.**

Evidence: `rows = await self._fetch_item_rows(...); total = len(rows); page_rows = rows[start:start+page_size]` — no LIMIT/OFFSET is ever pushed into SQL, and service.items() additionally calls build_snapshot_token (all 9 types materialized, infra/repositories/handover.py:83-88) and port.count() in the same call. For a departing employee with thousands of tasks each of the ~9 items calls loads every matching row into memory. 00 §10.4 introduces the page/page_size bounds specifically as read-amplification protection (足以把下游数据库拖垮); bounding the parameters but then ignoring them in the query gives that protection away.

**Reviewer notes:** SCOPE: commits 39970cb (SDK vendor), 613eaee (registry+descriptor), 0aa1678 (endpoint v2 + preview/items). Reviewed at HEAD a22abad with a clean tree; ran backend/.venv pytest on tests/unit/handover, tests/contract, tests/unit/authz, plus the three contract scripts.

WHAT VERIFIES CLEAN

1) SDK vendor (39970cb) — fully clean. All four VENDORED.md credentials check out against the upstream repo: Version 0.4.0; build commit C 2700b27484f57e779482eff4447f12104afb6e2a = "chore(sdk): release easyauth-app-sdk 0.4.0"; provenance commit P 4a20dc584bc0712566a223ef5ff9f6140538af05 = "docs(sdk): 记录 0.4.0 构建提交与 wheel SHA-256"; `shasum -a 256 /Users/konata/code/EasyAuth/sdk/python/dist/easyauth_app_sdk-0.4.0-py3-none-any.whl` = 8e3a902328005deb096547904aee767d7ad07b5246fea89a8c489665614192a0, matching VENDORED.md exactly. I unzipped the wheel and diffed all 18 payload files against backend/vendor/easyauth-app-sdk/src/easyauth_app_sdk/ — 18/18 byte-identical (including the six contract_samples/handover_v2 JSONs and py.typed). The 21-entry per-file sha256 table in VENDORED.md 文件校验 also recomputes exactly. EXPECTED_SDK_VERSION = "0.4.0" (_bridge.py:49) == descriptor.SDK_VERSION == pyproject version; assert_sdk_version() runs in each easyauth_* adapter constructor and is pinned by tests/contract/easyauth/test_redaction_and_version.py:73-74. No __pycache__ is git-tracked. The 0.4.0 kernel does carry everything 05 §4.2 depends on: DEFAULT_MAX_BODY_BYTES = 256*1024, read_bounded_body (Content-Length pre-check + streaming N+1 truncation), event_type-vs-header comparison placed before the webhook.test short-circuit (lifecycle.py:147-153), HandoverBusinessError + ALLOWED_BUSINESS_STATUS {400,409,412,413,422,423,429}, fixed-text 500 with no str(error) leak, and manifest._validate_lifecycle allowing handover_asset_types.

2) Descriptor content (613eaee) — the output is correct even though its provenance is not (see finding #2). Verified at runtime: build_descriptor_payload(manifest=load_manifest()) yields lifecycle.capabilities == ["handover.v2"], 9 handover_asset_types, and the list is currently value-equal to descriptor_handover_asset_types(); all 9 have releasable=false, detail_supported=true; no nested lifecycle.handover object, no separate `capability` field (00 §9.1 / 05 §4.6 satisfied). The embedded easyproject_manifest.json lifecycle equals the draft JSON lifecycle.

3) Endpoint error surface (0aa1678) — all 10 new CCR codes are implemented with the CCR §5.2 statuses: WEBHOOK_TIMESTAMP_INVALID 400 (reason in {INVALID_TIMESTAMP, TIMESTAMP_SKEW}), WEBHOOK_PAYLOAD_CONFLICT 409 (IdempotencyConflictError), EVENT_UNSUPPORTED 422, EVENT_MODE_MISMATCH 422, IDENTITY_UNMAPPED 409, ASSET_TYPE_UNDECLARED 422, REQUEST_BODY_TOO_LARGE 413, SNAPSHOT_STALE 412, HANDOVER_TEMPORARILY_LOCKED 423, RATE_LIMITED 429; the 3 retained codes keep 401/409/422 and the repo's frozen 401 (not the SDK's 403) is preserved with an explicit comment. ProcessingInProgressError is not a subclass of IdempotencyConflictError, so the _map_domain_error ordering that splits 429 from 409 is sound. Body handling is right: read_bounded_body runs before verify_webhook, `await request.body()` appears nowhere on this route (only in openproject_webhooks.py / easyauth_webhooks.py), and the event_type-vs-header check precedes the webhook.test short-circuit. Lock ordering in execute (projects → tasks → templates → work_records → reminder rules) and the 412-before-409 rule (full-digest recompute at service.py:254 precedes per-row ownership checks at :259, and the per-row failure raises SnapshotStaleError/412, not 409) follow 00 §10.5.1 as corrected. Terminal-project → 409 HANDOVER_CONFLICT vs approval-lock → 423 (service.py:386-390) matches the 09 §5.2 trap warning. task_id validation uses re.fullmatch, so "137:1\n" is rejected (the §4.4 trap). The idempotency key is the full triple `handover:v2:{task_id}:{generation}:{batch_id}` (types.py:67-68) — batch_id present, per the §4.4 trap.

4) 05 §4.2 deviation worth recording but not filed as a defect: the endpoint does NOT call the SDK's lifecycle_http_response() kernel; it re-implements verify → event_type check → dispatch by hand. Defensible (the kernel's callbacks are sync and it renders 403 rather than this repo's frozen 401), but it bypasses the kernel's ALLOWED_BUSINESS_STATUS whitelist — _map_domain_error passes HandoverBusinessError.status_code through unfiltered. Harmless today (nothing raises HandoverBusinessError), but it is a second implementation that can drift from the SDK's. Similarly, 05 §4.2's "explicit snake_case Pydantic models with a header comment" was implemented as raw dicts; the output shape is correct.

ASSESSMENT OF THE "openapi-baseline.json regeneration still pending" CLAIM

Accurate, and the pending work is bigger than one JSON file — but note that no drift check fails today because of it. `python3 scripts/check_openapi.py` returns OK (168 endpoints, compared against backend/openapi.json). Two reasons: (a) check_baseline() only validates that the codes the baseline declares exist in error-bodies.json, and the baseline still declares just the original three (all of which exist); (b) check_current() only compares x-error-codes when the FastAPI-generated document declares them, and this route sets no openapi_extra, so the comparison is skipped (check_openapi.py:203-207). The gate that IS red today is a different one — check_permissions.py — see the blocker finding. So the accurate statement is "the CCR is approved but unimplemented and the gate is currently blind to it", not "the gate fails on it".

What breaks the moment the baseline is regenerated with the 13 codes: check_openapi.py:123-124 (`引用未知错误码`) fires for the six codes missing from contracts/test-vectors/error-bodies.json domainCodes — EVENT_MODE_MISMATCH, IDENTITY_UNMAPPED, ASSET_TYPE_UNDECLARED, REQUEST_BODY_TOO_LARGE, SNAPSHOT_STALE, HANDOVER_TEMPORARILY_LOCKED. (EVENT_UNSUPPORTED, WEBHOOK_PAYLOAD_CONFLICT and WEBHOOK_TIMESTAMP_INVALID are already in domainCodes; RATE_LIMITED is covered by check_openapi's GENERIC_ERROR_CODES.) error-bodies.json must therefore be extended in the SAME changeset as the baseline, or regeneration turns the gate red.

Regeneration entails, in order (CCR-DH2-EP-01 §6):
  1. contracts/tools/generate_baseline.py:58 — the endpoint tuple still reads summary "EasyAuth 交接 preview/execute" with the 3-code list; change to "EasyAuth 交接 preview/items/execute" plus the frozen 13. This must be first — the generator is the authority and hand-editing the JSON is silently overwritten (CCR §2, 05 §5.2 trap).
  2. Same file, x-http-error-map at generate_baseline.py:388-402 — add "412": ["SNAPSHOT_STALE"] and "423": ["HANDOVER_TEMPORARILY_LOCKED"], fold REQUEST_BODY_TOO_LARGE into "413" (today only FILE_TOO_LARGE), file the rest under existing 400/409/422. "429": ["RATE_LIMITED"] already exists — the CCR explicitly says do not re-add it. Skipping this leaves a baseline declaring SNAPSHOT_STALE while its own error map has no 412.
  3. Re-run the generator to rewrite contracts/openapi-baseline.json (endpoint count must stay 168 so check_baseline's counts.endpoints cross-check stays green).
  4. contracts/test-vectors/error-bodies.json — add the six codes above to domainCodes + httpMap (blocking, per above).
  5. contracts/test-vectors/webhook-hmac.json — today it mentions "handover" exactly once (the protectedEndpoints entry); the three positive and six negative vectors from CCR §6.3 are absent. Do not add a "tampered delivery header → 422" case (CCR §6.3 / 00 §10.1 forbid it).
  6. contracts/test-vectors/handover-lifecycle.json — does not exist yet; CCR §6.4 requires it (412 zero-write, gen 2→1 → 409 zero-write, approval lock → 423, same-triple replay → byte-identical summary).
All of contracts/** is an AG-00 shared-hot area (05 §5.7, contracts/ownership.md 共享热点), so these go as patches to AG-00 — as does the permissions.json sourceSha256 refresh in the blocker finding, which is the same class of file and can ride the same patch.



# Wave-0 review findings for EasyProject (a5a trio + gates shards)

## Shard (wave0): verdict issues_found

### [minor/confirmed] /Users/konata/code/EasyProject/contracts/ownership.md:450
**The verbatim copy dropped doc 08's meta-instruction into ownership.md itself, so the contract file now asserts a falsehood about its own contents and instructs the reader to add an M40 entry that is already present at line 381 (duplicate-owner risk).**

Evidence: ownership.md:450-467 now reads "#### work-record 所有权补登记（contracts/ownership.md 当前缺失）… 现有矩阵…没有 M40 / work-record 表的条目。补：" followed by a fenced ```markdown block containing the exact M40 entry. But 27a0415 already inserted that entry into the module matrix at ownership.md:381-389 (byte-identical, verified by diff against doc 08 lines 56-64). Failure scenario: the next agent/AG-00 reading contracts/ownership.md §1.1 follows the still-imperative "补：" instruction and appends a second `### M40 工作记录（AG-40 / W11）` block; ownership.md:5-6 declares "任何重复 owner 或未分配端点/表/路由阻断合并", so a duplicate registration is a merge-blocking condition. Doc 08 line 6-7 (落地方式) mandated verbatim append of §1/§2 正文 plus the matrix entry, so verbatim copying was correct — but the landed file needs a one-line annotation (e.g. "（已于本文件『模块矩阵』落地）") to stop being self-contradictory. Doc ref: 08 §1.1 「work-record 所有权补登记」.

### [minor/plausible] /Users/konata/code/EasyProject/contracts/ownership.md:158
**Module-matrix registration was applied asymmetrically: M32 got its new outbox table and M40 was added, but M06 — the module A5 actually owns — was not registered with the new `easyauth_handover_generations` table nor the `backend/app/domain/handover/**` file root that the same landed ruling assigns to it.**

Evidence: The landed ruling assigns `easyauth_handover_generations`（新表）to M06 (ownership.md:427, doc 08 §1.1 row 2) and authorizes A5 to move code into `backend/app/domain/handover/**` (doc 08 §1.6, landed at ownership.md ~848). But the M06 matrix entry at ownership.md:158 still reads "- 表：`authz_permission_catalog`、`authz_user_permission_snapshots`、`easyauth_manifest_state`" and :161-164 lists no `domain/handover/**`. Meanwhile M32's line 333 WAS updated to add `op_handover_projection_outbox`. ownership.md:5-6 states "任何重复 owner 或未分配端点/表/路由阻断合并". Failure scenario: at the next AG-00 gate the table/file-ownership sweep over 模块矩阵 finds `easyauth_handover_generations` and `backend/app/domain/handover/*` (already present as untracked files in the worktree) with no owning module entry, which by the file's own preamble blocks merge. Marked plausible because doc 08 mandated only the M40 and M32 matrix edits, so the omission is literal-compliant; flagged because the doc's own rationale for 补登记 ("现有矩阵…没有条目") applies identically here.

### [minor/confirmed] /Users/konata/code/EasyProject/scripts/quality-gate.sh:35
**The lockfile guard still accepts `package-lock.json` as sufficient, but the installer it guards now requires `pnpm-lock.yaml`, so the guard's fail-fast path is dead and a mis-locked checkout dies inside pnpm with an unrelated message instead of the intended diagnostic.**

Evidence: quality-gate.sh:35 `if [ ! -f frontend/package-lock.json ] && [ ! -f frontend/pnpm-lock.yaml ]` was written for the old `npm ci` on line 39; 1a71ac9 changed line 39 to `pnpm install --frozen-lockfile` but left the guard untouched. Failure scenario: a checkout carrying only `frontend/package-lock.json` passes the guard (no `!! frontend 缺少 lockfile` message, FAILED stays 0), then line 39 aborts with pnpm's "Headless installation requires a pnpm-lock.yaml file" and, under `set -euo pipefail` (line 9), kills the whole gate mid-step-5 without the diagnostic the guard exists to print. CI does not have this hole: .github/workflows/ci.yml:108-112 gates on `frontend/pnpm-lock.yaml` specifically. ownership.md:98-99 (G1 裁定) already froze "frontend 以 pnpm-lock.yaml 为锁", so the package-lock.json branch is stale. Low real-world impact: the repo currently ships only frontend/pnpm-lock.yaml.

### [minor/confirmed] /Users/konata/code/EasyProject/scripts/quality-gate.sh:39
**The npm→pnpm alignment stopped at the install step: the frontend stage still shells out via `npm run`/`npx` and omits the `check:theme` and `vitest run` steps CI runs, so the script's line-2 claim of being isomorphic with ci.yml remains false and a local PASS still does not predict CI.**

Evidence: quality-gate.sh:2 declares "本地一键质量门禁（与 .github/workflows/ci.yml 同构）". After 1a71ac9, line 39 is `(cd frontend && pnpm install --frozen-lockfile && npm run lint && npx tsc --noEmit && npm run build)`, while ci.yml:119-124 runs `pnpm install --frozen-lockfile / pnpm run check:theme / pnpm run lint / pnpm exec tsc --noEmit / pnpm exec vitest run / pnpm run build`. Failure scenario: a change that breaks `frontend/scripts/check-theme.mjs` invariants or any vitest spec passes the local gate green and is only caught after push — the same local-vs-CI divergence class that 05-easyproject-backend.md §7 step 0.5 exists to eliminate ("不做的话后面每次跑门禁都白跑"). Doc 05 §7 step 0.5 mandated only the `npm ci` → `pnpm install --frozen-lockfile` substitution, which was done exactly and at the right spot; the residual `npm run`/`npx` usage and the two missing steps pre-date this commit.

**Reviewer notes:** VERDICT SUMMARY — the four commits are substantively correct. No contract drift, no dropped ruling clause, no invented additions, no trap-warning regressions. All four findings are minor; none blocks the gate on semantics.

(1) VERBATIM FIDELITY — CLEAN (mechanically proven). `sed -n '15,749p' 08-easyproject-ag00-rulings.md` and `sed -n '414,1147p' contracts/ownership.md` are byte-for-byte identical (734 lines each, empty diff). Nothing dropped, paraphrased, or added inside the ruling body. Spot-verified that every trap-warning ("早期版本这样写会怎样") passage survived with its corrected behavior:
  - §2.1 no-copy-of-historical-署名 trap: corrected rule (`added_by = NULL` / `created_at = now` on new rows, byte-untouched on merge) landed, plus the explicit rejection of the 哨兵 dtuid alternative.
  - §2.2 lock-order trap: `projects` lock set = 显式项目类资产 ∪ 所有待写 task 的非空 project_id, including the "只锁 task 就穿透审批写保护、且不会返回 423" rationale.
  - §2.2 412-not-409 trap: "先重算全量 snapshot 摘要、后逐条校验", 412 零写入, and the instruction that domain-level 兜底 conflicts must still be reported as 412 rather than 透传成 409.
  - §2.3 idempotency ordering trap: claim_or_replay BEFORE business locks with the explicit override "§2.2 的那张表以本节为准"; `store_response` not being a new tail lock node; the preview/items-vs-execute watermark ordering trap; the IdempotencyConflictError → 409 WEBHOOK_PAYLOAD_CONFLICT vs ProcessingInProgressError → 429 RATE_LIMITED split-by-exception-class ruling; `wait_for_completion=False`.
  - §2.4 approval-lock trap: 423 HANDOVER_TEMPORARILY_LOCKED for recoverable locks vs 409 HANDOVER_CONFLICT for COMPLETED/CANCELLED, "不能直接把 PROJECT_LOCKED 改成 423", and the removal of 审批锁 from HANDOVER_CONFLICT's scope.
  - §1.3 M18 三分支 occurrence trap; M10/M19 assignee-cannot-be-collaborator merge rule; M40 creator-is-merge-not-409 rule; M32/M33 版本护栏 (only assignment_version + collaborators_hash, task.version diagnostic-only) and owner-CAS rules.
  - §1.4 `m32_002` unique key `(handover_task_id, generation, batch_id, task_id)` including the explicit correction of the earlier `handover_task_key_sha256` mistake.

(2) THE TWO MATRIX ADDITIONS ARE MANDATED, NOT INVENTED. Doc 08 lines 6-7 (落地方式) explicitly order "把 §1.1 的 M40 条目补进该文件的模块矩阵", and §1.1's 「work-record 所有权补登记」 supplies the exact M40 block plus "同时给 M32 补登记 `op_handover_projection_outbox`". The landed M40 entry (ownership.md:381-389) is byte-identical to doc 08 lines 56-64. The M32 edit (ownership.md:333) adds exactly `op_handover_projection_outbox` and nothing else. M33's entry was correctly left as "表：无" — doc 08 mentions M33 only as context (it is the consumer/write path, not the table owner) and orders no M33 change.

(3) PLACEMENT — matches the doc's literal instruction ("追加"), with one format deviation I did not raise as a finding. §1/§2 were appended at end-of-file after 「共享热点」; the M40 entry went into 模块矩阵 between M38 and the OpenProject W7–W10 汇总 (that 汇总's counts enumerate M32/M36/M37/M38 only, so no numeric contradiction was introduced). Deviation: every pre-existing ruling in this file is a `##`-level named section (W3 并行裁定 / G2 / G1 / W0) placed BEFORE 模块矩阵, whereas the two new rulings landed as `###` under new generic `## 1. 所有权裁定` / `## 2. system-actor 语义裁定` containers at the tail — doc 08 lines 3-4 say 体例沿用「W3 并行裁定」段落. Cosmetic, and forced by the verbatim-copy mandate (doc 08's own headings are `## 1.` / `## 2.`); the ruling headings still carry the required 日期+AG-00+门禁 form. Also verified doc 08 §2.1's self-reference `contracts/ownership.md:201,210` still resolves after the insertion (201 = M11 heading, 210 = M12 heading; the M40 insert is at 380, below them).

(4) CCR — CLEAN. `sed -n '14,188p' 09-easyproject-ccr.md` vs the landed file differs on exactly one line: the title demoted from `##` to `#`, correct for a standalone document. Doc 09's wrapper blockquote (lines 3-11, meta-instructions about the file itself) was correctly excluded rather than copied — the opposite and better call than what happened in ownership.md (finding #1). All 13 x-error-codes present and unique (3 retained + the 10 new: WEBHOOK_TIMESTAMP_INVALID 400, WEBHOOK_PAYLOAD_CONFLICT 409, EVENT_UNSUPPORTED 422, EVENT_MODE_MISMATCH 422, IDENTITY_UNMAPPED 409, ASSET_TYPE_UNDECLARED 422, REQUEST_BODY_TOO_LARGE 413, SNAPSHOT_STALE 412, HANDOVER_TEMPORARILY_LOCKED 423, RATE_LIMITED 429), each with its HTTP status and 保留/新增 marker; both post-table callouts (SNAPSHOT_STALE-must-not-fold-into-409, EVENT_MODE_MISMATCH-do-not-rename) survived, as did §6's warning that `429: ["RATE_LIMITED"]` already exists in the x-http-error-map and must not be re-added. Numbering CCR-DH2-EP-01 collides with nothing (prior CCRs are CCR-003 and CCR-OP-1~6, none stored as files — docs/implementation/ccr/ is a new directory created by bdbe983; neither contracts/workflow.md §6 nor docs/implementation/01 §12 mandates a path or a registry file, so no index was missed). Two-commit trail is clean: bdbe983 adds the file at 状态：PROPOSED (174 lines, one file, nothing else touched); be41946 changes exactly one line PROPOSED→APPROVED and nothing else. Non-finding worth surfacing: the document carries no 批准人/批准日期 field, so the APPROVED state is traceable only via be41946's commit message ("AG-00（本执行轮授权）批准"); doc 09's six-element format does not require an approver field, and the same-author (AG-05 acting as AG-00) self-approval appears sanctioned by this execution round rather than being a process breach.

(5) QUALITY-GATE — the change is exactly the mandated one. `git show 1a71ac9` is a single-line edit at scripts/quality-gate.sh:39, inside the correct `else` branch of the frontend stage, `npm ci` → `pnpm install --frozen-lockfile`, with `npm run lint && npx tsc --noEmit && npm run build` left untouched. The fix is real: frontend/ ships only pnpm-lock.yaml (no package-lock.json) and is a pnpm workspace root (pnpm-workspace.yaml, `@easy-enterprise/ui: workspace:*`), so `npm ci` did fail deterministically as 05 §7 step 0.5 describes. Nothing else regressed — `set -euo pipefail`, the FAILED accumulator, and all other steps are unchanged. Pre-existing and NOT introduced by this commit: inconsistent step labels (`5/6` at line 33 vs `6/7`/`7/7` at 45/54) and a header comment listing 6 steps for a 7-step script.

Files inspected: /Users/konata/code/EasyProject/contracts/ownership.md, /Users/konata/code/EasyProject/docs/implementation/ccr/CCR-DH2-EP-01-data-handover-v2-baseline.md, /Users/konata/code/EasyProject/scripts/quality-gate.sh, /Users/konata/code/EasyProject/.github/workflows/ci.yml, /Users/konata/code/EasyProject/contracts/workflow.md, /Users/konata/code/EasyProject/docs/implementation/01-并行开发与共享契约.md, /Users/konata/code/EasyProject/frontend/package.json, /Users/konata/code/EasyProject/frontend/pnpm-workspace.yaml, and the frozen docs /Users/konata/code/EasyAuth/docs/design/data-handover-v2/{08-easyproject-ag00-rulings.md, 09-easyproject-ccr.md, 05-easyproject-backend.md}.


## Shard (wave0): verdict issues_found

### [blocker/None] /Users/konata/code/EasyProject/backend/app/domain/identity/handover_identity.py:163
**纯绑定回填顺带重写 M07 目录投影列（display_name / is_active），超出 AG-00 冻结的 directory_users 写入白名单**

Evidence: 08 §1.1（已落地为本仓库 contracts/ownership.md:428）冻结：`directory_users` 本次允许写入的列「**仅** authentik_user_id、updated_at」；05 §2.1 第 3 条同样写死「只写 authentik_user_id…不碰任何时间戳」。实现的 _bind_pure 在调用 bind_verified_authentik_sub 之前先调 repo.upsert_directory_projection(display_name=…, is_active=…)（infra/repositories/directory.py:611-641 会 UPDATE display_name / is_active / updated_at）。具体故障：离职者本地行已由钉钉目录同步写成 display_name='张三'、is_active=false，但 authentik_user_id 仍为 NULL（从未登录，正是 P2 要解决的那批人）。交接 webhook 到达 → 段①本地按 sub 查不到 → 段②目录反查 → 段③先把 EasyAuth 侧的 name/active 覆盖回本地行：is_active 被翻回 true、display_name 被 EasyAuth 的 name（或 name 缺失时的 dtuid，见 infra/easyauth_directory/adapter.py:137）覆盖。后果一：EasyProject 目录接口默认 includeInactive=false（05 §5.6），离职者重新出现在在职名单里；后果二：下一次交接的 purpose='target' 校验读的正是这一行（handover_identity.py:88 _enforce_purpose_active），被复活的离职者会被判为合法接收人。单测 test_handover_identity.py:100 还把「本地无行时创建投影行」当成期望行为固化下来。

### [major/None] /Users/konata/code/EasyProject/backend/app/domain/handover/hints.py:41
**hint 从尾部截断，长项目名会把 §2.3 硬要求的截止日期/状态/标题整段挤掉**

Evidence: 05 §2.3 冻结每类 hint「必须包含」的字段（task_assigned/task_assigner = 所属项目+截止日期+当前状态；work_record_participant = 关联项目/任务+记录日期），并写明「hint 为空或只有 ID 视为未完成本项，验收用例须逐类断言」。渲染器把变长字段放在最前、_clip 只砍尾部。实测（直接调用该模块）：render_task_role_hint(project_name='项'*130, due_at=2026-09-01, status='IN_PROGRESS') 返回 120 字符且 '2026-09-01' 与 '进行中' 都不在结果里；projects.name 列宽 String(200)（infra/repositories/projects.py:82），130 字符是完全合法的取值。同理 render_work_record_participant_hint(related_label 200 字符) 丢掉记录日期，render_task_collaborator_hint 在项目名超长时丢掉整个任务标题。代管已废弃、主管只能靠 hint 判断归属，这类 hint 等于「只有一个被截断的名字」。test_hints.py:144 的 test_hint_clipped_to_max_chars 只断言长度与结尾省略号，没有断言必需要素仍在，所以该退化不会被任何用例挡住。

### [major/None] /Users/konata/code/EasyProject/backend/app/domain/handover/hints.py:50
**hint 的日期/时间按 UTC 直接截取，未走业务时区（Asia/Shanghai），日期可差一天、时间差 8 小时**

Evidence: AGENTS.md 不变量 8：「数据库与进程 UTC；业务日历解释 Asia/Shanghai（app/core/time.py）」，仓库已提供 business_date() / to_business_time()（app/core/time.py:38-42）。_fmt_date 对 datetime 直接取 .date()、_fmt_dt 直接 strftime，输入是库里 tz-aware 的 UTC 值（TaskRow.due_at、RecurringTemplateRow.next_run_at、WorkRecordRow.start_at 均为 DateTime(timezone=True)）。具体故障：截止 2026-09-01 00:00 CST 的任务存为 2026-08-31T16:00Z，hint 渲染成「截止2026-08-31」，比任务详情页早一天；每天 17:30 CST 生成的周期模板 next_run_at=09:30Z，hint 渲染成「下次2026-08-15 09:30」，与界面上的 17:30 差 8 小时。05 §2.3 规定 hint 承担主管判断归属的全部依据，日期/时间错位直接误导判断。模块 docstring 把责任推给调用方（『由调用方保证传入本地语义』），但契约里传下来的就是库里的 UTC 值。

### [major/None] /Users/konata/code/EasyProject/backend/app/domain/identity/errors.py:16
**新增第 14 个错误码 IDENTITY_TARGET_INACTIVE 并映射 422，与 CCR 冻结的 13 码清单及 08 §1.3 的 409 语义冲突**

Evidence: 09-easyproject-ccr.md §5.2 把本 operation 的 x-error-codes「冻结为完整 13 项」，其中没有 IDENTITY_TARGET_INACTIVE；05 §5.2 的门禁表把「新错误码的实现与返回」列为必须等 CCR APPROVED 的项，而已批准的 CCR 只覆盖那 13 个。语义上 08 §1.3（ownership.md:同段）对 M13 命令写死「项目终态、来源已非 owner/member、**目标 inactive** → ProjectHandoverConflict → 409 HANDOVER_CONFLICT」，并说明 identity 侧的 target-active 校验与锁内校验是同一条规则；契约 §10.6 的 409 行覆盖「人员无法识别 / 请求本身与 APP 的现实对不上」，422 行只是「载荷不被支持（未声明的资产类型、不支持的事件）」。故障：同一个「接收人已停用」条件，在身份解析阶段返回 422（EasyAuth 提示「应用声明与实现不一致」），在领域锁内复查时返回 409（提示「应用拒绝了本次交接」）。此外该码要真正从端点返回，必须先进 contracts/test-vectors/error-bodies.json 的 domainCodes（否则 tests/helpers/vectors.py:102 直接 KeyError），而测试向量属 AG-00 + CCR 范围，A5 不得自行新增。

### [minor/None] /Users/konata/code/EasyProject/backend/app/domain/handover/predicates.py:126
**is_live_for_asset_type 对 project_member 在缺 member_role 时 fail-open，OWNER 行会混进 project_member 口径**

Evidence: 函数 docstring 自述「缺字段视为不活 / 不在范围内」，其余三组分支确实在字段为 None 时 return False；唯独 project_member 分支写成 `if member_role is not None:` —— 调用方没取 role 时不排除 OWNER，直接返回 project_is_live(status)=True。§3.1.2 与 08 §1.3 都要求 member 选择器排除 OWNER 行（OWNER 只进 project_owned），否则 preview 会把同一个人的 OWNER 关系重复计一次，execute 又会把 OWNER 行当作普通成员行删除/合并，破坏「每项目恰有一个 OWNER」的部分唯一索引前提。这是共享选择器、preview/items/execute 共用，无任何用例覆盖 member_role=None（test_assets_registry.py 只传了 OWNER/MEMBER 两种显式取值）。

### [minor/None] /Users/konata/code/EasyProject/backend/app/domain/identity/handover_identity.py:147
**目录调用的兜底 except Exception 把 Permanent 类错误也报成 DIRECTORY_UNAVAILABLE(502)，让不可能成功的请求变成可重试**

Evidence: domain/ports/easyauth.py:71-93 把 Unauthorized / CapabilityDisabled / 契约畸形（_malformed）都归为 Permanent(retryable=False)，实现只显式处理 NotFound 与 Transient，其余全部落到 147 行兜底 → IdentityDomainError('DIRECTORY_UNAVAILABLE') → 502。契约 §10.6 的 5xx 行是「failed，可重试=是」，于是「应用未开通 directory 能力（403 PERMISSION_DENIED）」「凭据失效」这类要人工介入的确定性失败会被 EasyAuth 反复重试。只有 Transient（含 RateLimited）该映射为 DIRECTORY_UNAVAILABLE；Permanent 应按 §5.2/§10.6 归入不可重试的失败面。

### [minor/None] /Users/konata/code/EasyProject/backend/app/infra/repositories/directory.py:751
**真正上线的 PG 纯绑定实现零测试覆盖；§6 的「不写登录时间戳」保证只在内存 fake 上验证**

Evidence: grep 全量 backend/tests 对 bind_verified_authentik_sub 零命中。05 §6 要求 test_handover_identity.py 覆盖 P2 的四条，但用例全部跑在 InMemoryDirectoryUserRepository 上——该 fake 的 bind 方法 `del now`、数据结构里根本没有 updated_at/last_synced_at 列，结构上不可能发现 PG 实现误写登录时间戳或多写列的回归；仓库里已有同类 PG 集成用例的现成落点（tests/integration/directory/test_pg_directory_user_repository.py:212 覆盖了姊妹方法 upsert_directory_projection 的「不改 authentik_user_id / 登录时间」）。附带：PG 版的「行不存在则插入」分支（directory.py:823-838）写了 display_name/is_active/last_synced_at/created_at/row_version，同样超出 08 §1.1 的两列白名单，且把 is_active 硬编码为 True（离职者场景会插出一行 active 记录）。

### [minor/None] /Users/konata/code/EasyProject/backend/app/domain/identity/handover_identity.py:46
**resolve_handover_identity 的签名与 08 §1.3 冻结的裁定不一致（users: DirectoryUserRepository → user_repo_factory），未同步裁定文本**

Evidence: 08 §1.3（副本已落在本仓库 contracts/ownership.md:532-537）冻结了 M06 将要调用的签名 `resolve_handover_identity(*, authentik_sub, purpose, directory: DirectoryPort, users: DirectoryUserRepository, now)`，实现改成了 `user_repo_factory: UserRepoFactory` 并额外导出别名 resolve_dtuid。改动本身有正当理由（本仓库的仓储是 session 绑定的 BaseRepository，直接传 users 就会在 05 §2.1 禁止的「跨 HTTP await 持有 session」上翻车），但属于对冻结接口的单方面偏离：ownership.md 里的裁定原文仍写 `users:`，按裁定编码的 M06 调用方会对不上；生产用的短 session factory 也尚未提供（仅有 in_memory_user_repo_factory）。应走 AG-00 修订裁定文本，或在交付说明里显式登记该偏离。

**Reviewer notes:** 审查范围与结论\n\n1) 我按 merge 60d60d6 的提交内容审查（git show），不是工作树——工作树当前是脏的，且有另一路在跑的 WIP（任务 #9「六条命令 + M06 + endpoint v2」）正在改同一批文件。请注意两点：\n   - 本次被审查的 backend/tests/unit/handover/test_assets_registry.py（merge 版 216 行 / 15 个用例）在工作树里已被未提交的 66 行 / 4 个用例版本覆盖。丢掉的是：9 类逐类参数化断言、is_live_for_asset_type 分派入口的全部覆盖、注册表 vs 谓词分组全集相等断言、doc order 断言、以及「未知 asset_type 抛错」。新版还用了一个并不存在的工作记录状态 'CLOSED' 做断言（真实取值集见 domain/work_records/ports.py:18 = OPEN/COMPLETED/CANCELLED），属于 assert-not-live 的假阳性。这不是本次 merge 的缺陷，但它正在把本次交付的验收面吃掉，建议在合入 WIP 前恢复。\n   - HEAD 已是 613eaee（descriptor/§4.1），它给 assets.py 追加了 descriptor_handover_asset_types / lifecycle_manifest_section。本 merge 的 assets.py 不含这两个函数，边界判定按 merge 版做。\n\n2) 「37 个单测」核实为真、非注水：identity 13 + hints 9 + registry 15（其中 9 个来自 4 个 parametrize）= 37，逐个都在断言文档语义（source 允许 inactive / target 必须 active、纯绑定不动 first_login_at/last_login_at、冲突绑定 → IDENTITY_UNMAPPED、父项目终态压制任务、审批中项目仍算「活」→ 对应 423 可恢复语义、9 类 releasable=false）。已实际跑通（hints 9 passed、identity 13 passed）。主要空洞见 finding #2/#5/#7：hint 截断后必需要素是否仍在、project_member 缺 role 的 fail-open、PG 纯绑定 SQL 零覆盖。\n\n3) 边界纪律（第 4 项）总体干净：merge 只动了 12 个文件——domain/handover/{__init__,assets,hints,predicates}.py（新）、domain/identity/{handover_identity,errors,directory_repo}.py、infra/repositories/directory.py、三个测试文件。没有碰 api/v1/easyauth_lifecycle.py、domain/authz/lifecycle.py、contracts/**、openapi-baseline.json、test-vectors、descriptor 路由、job_registry，也没有 alembic revision。唯一实质越界是 finding #1 的列白名单（写了 directory_users 的 display_name/is_active）和 finding #4 的第 14 个错误码。\n\n4) §3.1.2 的两个陷阱点均按修正后的行为落地：任务类谓词连父项目一起看（避免 COMPLETED 项目下未完成任务反复 423 死循环）；审批中状态（PENDING_INITIATION_APPROVAL / CLOSING_APPROVAL）不算终态、仍进清单（对应 423 可恢复而非 409）。终态字符串与 domain/projects/ports.py:30-36、domain/tasks/ports.py:29、work_records/ports.py:18、recurring_task_templates.is_enabled 逐一核对一致；task_is_live(project_status=None) 放行与写路径 _ensure_project_unlocked（tasks/commands.py:896「独立任务不查锁」）一致，不是漏判。\n\n5) 未列为 finding 但值得知会：assets.py 用模块级 assert 做注册表/谓词漂移守卫，python -O 下会被剥掉；05 §3.4 的 WorkRecordRow 缺口要求写进 PR 描述与 docs/design/09-分期计划与风险清单.md，该文档目前只在未提交的工作树里被改动，合入前需确认落到 PR 描述。

