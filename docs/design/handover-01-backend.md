# 数据交接 v2：EasyAuth 后端改造设计

> 基准文档：[`handover-00-overview-and-contract.md`](handover-00-overview-and-contract.md)（下称「契约」）。
> 本文件中出现的 D1–D13 编号、事件名、错误码、payload 形状均以契约为准，此处不重复定义，只给落地方案。
> **§6 的 HTTP API 契约是前端 agent（`handover-02-frontend.md`）的依赖，必须最先提交。**

---

## 1. 改造总览

| 模块 | 改动性质 | 说明 |
|---|---|---|
| `lifecycle/models.py` | 扩展 + 破坏性重构 | 新增 4 张表，`HandoverTask` 加 4 字段，`HandoverAppAction` 去掉接收人字段改为条目级 |
| `lifecycle/assignee.py` | **新建** | 主管链解析（契约 §8.2） |
| `lifecycle/custody.py` | **新建** | 代管授权发放/收回/上交（契约 §7） |
| `lifecycle/handover.py` | 重构 | webhook payload v2、新增 items 事件、blocked 判定 |
| `lifecycle/offboarding.py` | 扩展 | 建单时解析 assignee、发代管、升级路径 |
| `lifecycle/reassign.py` | **新建** | 在职移交建单与管辖校验（D8/D9） |
| `applications/models.py` | 扩展 | `App` 加交接能力三态与资产类型声明 |
| `webhooks/models.py` | 微调 | body 上限常量 |
| `grants/managed_users.py` | 扩展 | 代管期把 departed subject 并入集合（契约 §7.3） |
| `admin_console/lifecycle_api.py` | 扩展 | 新增 skip/claim/items 端点 |
| `portal/` | **新建一组端点** | 自助交接（D1），全部非超管 |
| `tasks/lifecycle.py` | **新建** | 到期上交、每日提醒两个 beat 任务 |
| `sdk/python/.../lifecycle.py` | 扩展 | v2 事件与 items 回调 |
| `docs/decisions/ADR-002` | 修订 | 契约 §3.1 两条 |

**硬约束提醒**（`AGENTS.md`）：项目未上线，**不保留旧形态、不写兼容层**。
`HandoverAppAction.to_user` / `execution_to_user` 直接删除，不做双写、不留过渡字段；
相关迁移直接改列，不保留旧列。所有文档必须中文。

---

## 2. 数据模型变更

### 2.1 `HandoverTask`（`lifecycle/models.py:109`，修改）

新增字段：

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `assignee` | `FK(UserMirror, on_delete=PROTECT, null=True, blank=True, related_name="handover_assignments")` | 可空 | 当前负责人；`superuser_pool` 时为 `NULL` |
| `assignee_state` | `CharField(max_length=16, choices=ASSIGNEE_STATE_CHOICES, default=ASSIGNEE_STATE_SUPERUSER_POOL)` | CheckConstraint | `manager` / `subject` / `superuser_pool` |
| `escalation_level` | `PositiveSmallIntegerField(default=0)` | — | 当前 assignee 在主管链上的层级 |
| `generation` | `PositiveIntegerField(default=1)` | — | 执行轮次，升级/重新盘点时 +1（契约 §8.3） |

新增常量：

```python
ASSIGNEE_STATE_MANAGER: Final = "manager"
ASSIGNEE_STATE_SUBJECT: Final = "subject"
ASSIGNEE_STATE_SUPERUSER_POOL: Final = "superuser_pool"
ASSIGNEE_STATE_VALUES: Final[tuple[str, ...]] = (
    ASSIGNEE_STATE_MANAGER, ASSIGNEE_STATE_SUBJECT, ASSIGNEE_STATE_SUPERUSER_POOL,
)

HANDOVER_KIND_REASSIGN: Final = "reassign"   # 加入 HANDOVER_KIND_CHOICES / _VALUES
```

**约束变更**（关键）：现有 `lifecycle_task_one_open_per_subject` 会挡住 `reassign` 与离职单并存，
必须改为只约束 `offboard`/`transfer`：

```python
models.UniqueConstraint(
    fields=["subject_user"],
    condition=Q(status__in=TASK_OPEN_STATUSES)
              & Q(kind__in=(HANDOVER_KIND_OFFBOARD, HANDOVER_KIND_TRANSFER)),
    name="lifecycle_task_one_open_lifecycle_per_subject",
)
```

新增约束：

```python
models.CheckConstraint(
    condition=Q(assignee_state__in=ASSIGNEE_STATE_VALUES),
    name="lifecycle_task_assignee_state_supported",
),
# superuser_pool 必须无 assignee; 其余状态必须有 assignee。
models.CheckConstraint(
    condition=(
        Q(assignee_state=ASSIGNEE_STATE_SUPERUSER_POOL, assignee__isnull=True)
        | (~Q(assignee_state=ASSIGNEE_STATE_SUPERUSER_POOL) & Q(assignee__isnull=False))
    ),
    name="lifecycle_task_assignee_shape",
),
```

### 2.2 `HandoverAppAction`（`lifecycle/models.py:163`，破坏性修改）

**删除**：`to_user`、`execution_to_user`、`policy`、`execution_policy`（接收人下沉到条目级，D10；
`policy.unowned_strategy` 被 `default_to_user_id=null` 语义取代）。

**新增**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `generation` | `PositiveIntegerField(default=1)` | 建 action 时从 `task.generation` 拷贝；升级时重置 |
| `execution_payload` | `JSONField(default=dict, blank=True)` | 实际发出的 execute 请求体快照，不可变审计凭据 |
| `blocked_reason` | `CharField(max_length=64, blank=True)` | `capability_undeclared` / `descriptor_unreachable` |
| `skip_reason` | `TextField(blank=True)` | 超管强行跳过的理由（D6） |
| `skipped_by` | `CharField(max_length=128, blank=True)` | 超管 actor id |

**状态枚举新增**：`ACTION_STATUS_BLOCKED: Final = "blocked"`，加入 `ACTION_STATUS_CHOICES` / `_VALUES`。
`ACTION_FINISHED_STATUSES` **保持** `(done, skipped)` 不变 —— `blocked` 不是终结态，这正是 D13 的实现基础。

### 2.3 `HandoverAssetType`（新表）

preview 返回的资产分类落库，同时承载"这一类归谁"的默认接收人。

```python
class HandoverAssetType(models.Model):
    action = FK(HandoverAppAction, on_delete=CASCADE, related_name="asset_types")
    generation = PositiveIntegerField()                      # 与 action.generation 一致
    type_key = CharField(max_length=64)                      # 契约 §10.3 的 type
    label_snapshot = CharField(max_length=120)
    count = PositiveIntegerField(default=0)
    detail_supported = BooleanField(default=False)
    releasable = BooleanField(default=False)
    default_to_user = FK(UserMirror, on_delete=PROTECT, null=True, blank=True,
                         related_name="handover_default_receiving_types")
    selected = BooleanField(default=True)                    # 该类是否参与本次 execute
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["action", "generation", "type_key"],
                name="lifecycle_asset_type_unique_per_generation",
            ),
        ]
        ordering = ["action_id", "generation", "type_key"]
```

- `selected=False` 的类型**不进** execute 的 `assignments`（契约 §10.5 语义 4）。
- `default_to_user=NULL` 且 `selected=True` ⇒ 整批释放；若 `releasable=False` 则 §5.4 校验拒绝。

### 2.4 `HandoverAssetOverride`（新表）

逐条改派（D10）。

```python
class HandoverAssetOverride(models.Model):
    asset_type = FK(HandoverAssetType, on_delete=CASCADE, related_name="overrides")
    asset_id = CharField(max_length=128)                     # 契约 §5.3，对 EasyAuth 不透明
    label_snapshot = CharField(max_length=120, blank=True)
    to_user = FK(UserMirror, on_delete=PROTECT, null=True, blank=True,
                 related_name="handover_override_receiving")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["asset_type", "asset_id"],
                name="lifecycle_asset_override_unique",
            ),
        ]
        ordering = ["asset_type_id", "asset_id"]
```

### 2.5 `CustodyGrant`（新表，契约 §7）

```python
CUSTODY_REVOKE_TRIGGER_CHOICES = (
    ("action_finished", "action_finished"),
    ("task_completed", "task_completed"),
    ("task_cancelled", "task_cancelled"),
    ("escalated", "escalated"),
    ("manual", "manual"),
)

class CustodyGrant(models.Model):
    task = FK(HandoverTask, on_delete=CASCADE, related_name="custody_grants")
    custodian = FK(UserMirror, on_delete=PROTECT, related_name="custody_grants")
    escalation_level = PositiveSmallIntegerField(default=0)
    expires_at = DateTimeField()                             # 建单时刻 + CUSTODY_TTL_DAYS
    revoked_at = DateTimeField(null=True, blank=True)
    revoke_trigger = CharField(max_length=24, blank=True, choices=CUSTODY_REVOKE_TRIGGER_CHOICES)
    last_reminded_on = DateField(null=True, blank=True)      # 每日提醒去重
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # 同一交接单同一时刻只允许一份未收回的代管授权。
            models.UniqueConstraint(
                fields=["task"],
                condition=Q(revoked_at__isnull=True),
                name="lifecycle_custody_one_active_per_task",
            ),
        ]
        ordering = ["task_id", "-created_at"]
```

`CUSTODY_TTL_DAYS: Final = 14`，可由 `EASYAUTH_HANDOVER_CUSTODY_TTL_DAYS` 覆盖（D5）。

### 2.6 `CustodyGrantItem`（新表）

记录代管授权实际发出了哪些条目，收回时精确回收，**不误伤 custodian 自有授权**。

```python
class CustodyGrantItem(models.Model):
    custody = FK(CustodyGrant, on_delete=CASCADE, related_name="items")
    app = FK(App, on_delete=PROTECT, related_name="custody_grant_items")
    authorization_group = FK(AuthorizationGroup, on_delete=SET_NULL, null=True, blank=True)
    permission = FK(Permission, on_delete=SET_NULL, null=True, blank=True)
    scope_key = CharField(max_length=64, blank=True)
    applied = BooleanField(default=False)     # False 表示 custodian 本来就有, 未重复发放
    revoked_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(authorization_group__isnull=False, permission__isnull=True)
                           | Q(authorization_group__isnull=True, permission__isnull=False)),
                name="lifecycle_custody_item_target_shape",
            ),
        ]
```

### 2.7 `App` 交接能力声明（`applications/models.py:102`，修改，契约 §9）

| 字段 | 类型 | 说明 |
|---|---|---|
| `handover_capability` | `CharField(max_length=16, choices=..., default=HANDOVER_CAPABILITY_UNDECLARED)` | `declared` / `none` / `undeclared` |
| `handover_asset_types` | `JSONField(default=list, blank=True)` | descriptor 同步下来的资产类型声明 |
| `handover_capability_declared_by` | `CharField(max_length=128, blank=True)` | 声明 `none` 时的超管 actor |
| `handover_capability_declared_at` | `DateTimeField(null=True, blank=True)` | 同上 |
| `handover_capability_synced_at` | `DateTimeField(null=True, blank=True)` | descriptor 最近一次成功同步时间 |

约束：

```python
models.CheckConstraint(
    condition=(
        Q(handover_capability=HANDOVER_CAPABILITY_NONE,
          handover_capability_declared_by__gt="", handover_capability_declared_at__isnull=False)
        | ~Q(handover_capability=HANDOVER_CAPABILITY_NONE)
    ),
    name="applications_app_handover_none_requires_declaration",
),
```

即：声明「本 APP 无用户级数据」必须留下人和时间，不能是默认值飘进来的。

### 2.8 迁移

| App | 迁移 | 内容 |
|---|---|---|
| `applications` | `00XX_app_handover_capability.py` | §2.7 五字段 + 约束 |
| `lifecycle` | `00XX_handover_v2_schema.py` | §2.1–§2.6 全部；删除 `HandoverAppAction.to_user`/`execution_to_user`/`policy`/`execution_policy` |

`lifecycle` 迁移必须是**一个**迁移文件完成删列与建表，避免中间态。
数据迁移：存量 `HandoverAppAction.to_user` 不做转换（未上线，无需保留），迁移里直接删列。

---

## 3. assignee 解析（`lifecycle/assignee.py`，新建）

```python
@dataclass(frozen=True, slots=True)
class AssigneeResolution:
    user: UserMirror | None
    state: str                  # ASSIGNEE_STATE_*
    level: int
    degraded: bool              # True 表示目录数据不可用而落池

def resolve_assignee(subject: UserMirror, *, start_level: int = 0) -> AssigneeResolution: ...
```

实现要点：

1. 读 `DingTalkUserOrgContext`（`accounts/models.py:219`）取 `manager_chain`（自下而上）。
2. `manager_chain` 为空 **或** `stale=True` → 返回 `(None, superuser_pool, 0, degraded=True)`，
   写审计 `handover_assignee_resolution_degraded`。
   **不 fail-closed**：离职单是自动建的，宁可落超管池也不能丢单（契约 §8.2 已说明与权限查询取舍相反的理由）。
3. 从 `start_level` 起遍历，逐个用 `dingtalk_userid` 查 `UserMirror`；跳过：
   - 不存在的
   - `status != active` 的
   - `authentik_user_id` 以 `LOCAL_ADMIN_SUBJECT_PREFIX` 开头的（`accounts/local_admin.py`，break-glass 账号不参与生命周期）
   - 就是 subject 本人的
4. 找到即返回 `(user, manager, level, degraded=False)`；走完返回 `(None, superuser_pool, len(chain), False)`。
5. **不设层数上限**（D3）。

`apply_assignee(task, resolution, *, actor_id)`：写字段 + 审计 `handover_assignee_assigned` + 触发通知。

---

## 4. 代管授权（`lifecycle/custody.py`，新建）

### 4.1 发放 `grant_custody(task) -> CustodyGrant | None`

- `task.assignee is None` → 直接返回 `None`（超管池不发代管，契约 §7.4）。
- `task.kind in (transfer, reassign)` → 返回 `None`（当事人在职，主管本就有可见范围，D7/D9）。
- 同事务内：
  1. 建 `CustodyGrant(expires_at=now + CUSTODY_TTL_DAYS)`。
  2. 遍历 `task.grant_items`（`HandoverGrantItem`），按 `(app, group|permission, scope_key)` 去重。
  3. 对每条：若 custodian 在该 app 的**当前** `AccessGrant` 里已有等价条目 → 建
     `CustodyGrantItem(applied=False)`，**不发放**；否则写入 custodian 的当前 `AccessGrant`
     （`grant_type=timed`, `expires_at=custody.expires_at`），并建 `CustodyGrantItem(applied=True)`。
  4. 发放走既有授权写入路径（递增 `AccessGrant.version`，`AccessGrantPermission.source_note`
     记 `custody:task={id}`），保证 `snapshot_version` 变化、下游 5 分钟内刷新到。
  5. 审计 `handover_custody_granted`。

### 4.2 可见范围接入（`grants/managed_users.py`，修改，契约 §7.3）

`resolve_managed_users()` 在按策略解析出集合后，**追加**一步：

```python
custody_subjects = UserMirror.objects.filter(
    handover_tasks__custody_grants__custodian=viewer,
    handover_tasks__custody_grants__revoked_at__isnull=True,
    handover_tasks__custody_grants__expires_at__gt=now,
).values_list("authentik_user_id", flat=True)
```

并入结果集合。**这是全系统唯一允许非 active 用户进入 `MANAGED_USERS` 的位置**，
代码处必须留注释指向 ADR-002 修订条款。

注意 `_resolved_digest()`（`grants/query.py:320`）参与 `snapshot_version` 计算，
代管人员并入后 digest 自然变化，下游缓存会正确失效，无需额外处理。

### 4.3 收回 `revoke_custody(custody, *, trigger)`

- 对 `applied=True` 的 `CustodyGrantItem`，从 custodian 当前 `AccessGrant` 中移除对应条目并递增 version。
- `applied=False` 的只标记 `revoked_at`，**不动** custodian 自有授权。
- 写 `handover_custody_revoked`。

调用点：
- action 到达 `done`/`skipped` → 只收该 app 的条目（逐 APP 收，契约 §7.4）
- 整单 `completed` / `cancelled` → 全收

### 4.4 到期上交 `escalate_custody(custody)`（D5）

```
revoke_custody(custody, trigger="escalated")
res = resolve_assignee(task.subject_user, start_level=task.escalation_level + 1)
if res.user is None:
    task.assignee = None; task.assignee_state = superuser_pool
    task.escalation_level = res.level
    审计 handover_custody_escalated(to=None) + 通知全体超管
else:
    apply_assignee(task, res)
    grant_custody(task)                       # 新的 14 天
    审计 handover_custody_escalated + 通知新旧 assignee 双方
```

---

## 5. 交接执行改造（`lifecycle/handover.py`）

### 5.1 建 action 时的能力判定（契约 §9.1）

`_snapshot_app_actions()` 中，对每个 App：

| `App.handover_capability` | action 初始 status | 附加 |
|---|---|---|
| `declared` | `pending` | 按 `handover_asset_types` 预建 `HandoverAssetType` 占位（count 待 preview 填） |
| `none` | `skipped` | `skip_reason = "运营已声明本应用无用户级数据"`，`skipped_by = 声明人` |
| `undeclared` | **`blocked`** | `blocked_reason = "capability_undeclared"` |

删除 `_handover_hook_url()` 返回空串即静默成功的分支（`handover.py:590`）与
`HOOK_NOT_DECLARED_RESULT`（`handover.py:122,325`）—— 这是契约 §1.1 第 1 条要修的正确性缺陷。
`declared` 但 `AppWebhookConfig.handover_url` 为空 ⇒ **数据不一致**，直接抛
`HandoverError("declared 能力与 webhook 配置不一致")`，快速失败，不兜底。

### 5.2 descriptor 同步

新增 `applications/handover_capability.py`：

```python
def sync_handover_capability(app: App) -> None: ...
```

- 拉取 `/.well-known/easyauth-app.json`，解析 `lifecycle.handover`（契约 §9.1）。
- 成功 → 写 `handover_capability=declared`、`handover_asset_types`、`handover_capability_synced_at`；
  同步 `AppWebhookConfig.handover_url`。
- 拉取失败或缺 `lifecycle.handover` → **不覆盖**已有的 `none` 声明；否则置 `undeclared`，
  action 建单时即 `blocked`（`blocked_reason="descriptor_unreachable"`）。
- 挂到既有 manifest 同步入口（`api/manifest_sync_views.py`）与控制台"重新同步"按钮。

### 5.3 preview（契约 §10.3）

```python
def preview_action(action) -> HandoverAppAction
```

- payload 加 `generation`。
- 响应校验：每个 `type` 必须在 `App.handover_asset_types` 中声明过，否则 action → `failed`，
  `last_error="undeclared_asset_type: {type}"`。
- 用响应**重建**该 `(action, generation)` 下的 `HandoverAssetType` 行（`count`/`label_snapshot`），
  保留已存在行的 `default_to_user` / `selected`（重新 preview 不应清空用户已做的选择）。
- 响应中缺失的已声明类型视为 `count=0`，仍建行（契约要求 APP 返回 0 值，此处是防御性补齐并记
  `last_error` 警示不一致 —— **不静默**）。

### 5.4 execute 前置校验（契约 §10.5 语义 5）

`validate_assignments(action)` 在发请求前跑，任一不通过即 `422`，**不发 webhook**：

| 校验 | 错误码 |
|---|---|
| `selected=True` 且 `releasable=False` 且 `default_to_user=NULL` | `asset_type_not_releasable` |
| override 的 `to_user=NULL` 且该类 `releasable=False` | `asset_type_not_releasable` |
| 任一接收人 `status != active` | `receiver_not_active` |
| 任一接收人 == `task.subject_user` | `receiver_is_subject` |
| 全部 `selected=False` | `nothing_selected` |

### 5.5 execute（契约 §10.5）

- 组 payload：`assignments` 由 `HandoverAssetType`（`selected=True`）与其 `overrides` 生成。
- 把完整请求体写入 `action.execution_payload`（不可变审计凭据），替代原 `execution_to_user`/`execution_policy`。
- `transfer_selected_grants(action)` 的调用条件收紧：**仅 `kind == offboard` 时执行**（D7 —— 在职提前交接
  与在职移交都不动权限）。
- 成功后：`action.status = done` → 触发 §4.3 逐 APP 收回代管 → `refresh_task_status(task)`。

### 5.6 items（契约 §10.4，新增）

```python
def fetch_action_items(action, *, asset_type: str, page: int, page_size: int, q: str) -> dict
```

- 仅当该类型 `detail_supported=True` 才允许调用，否则 `400 detail_not_supported`。
- **透传不落库**（明细可能上千条，落库无意义且会过期）；前端翻页即实时回源。
- 校验 `total` 与同 generation 的 `HandoverAssetType.count` 一致；不一致时**不报错**但在响应里带
  `stale=true`，前端提示"清单已变化，建议重新预演"。

---

## 6. HTTP API 契约（**前端 agent 的依赖，冻结**）

### 6.1 门户（自助，`/portal/api/v1/`，D1）

认证：既有门户会话（OIDC 登录的 active `UserMirror`），**不需要超管**。
授权：见每行的「可访问条件」。越权一律 `404`（与既有门户一致，防枚举）。

| 方法 | 路径 | 可访问条件 | 说明 |
|---|---|---|---|
| GET | `/me/handover-tasks` | 登录即可 | 返回两组：`as_assignee`（我负责的）、`as_subject`（我是当事人的） |
| POST | `/handover-tasks/self-transfer` | 登录即可，且自己无 open 的 offboard/transfer 单 | 在职提前交接建单（D7），`kind=transfer`，assignee=本人 |
| POST | `/handover-tasks/reassign` | `subject ∈ 我的 MANAGED_USERS` 且双方 active | 在职移交（D9），必填 `reason`（≥10 字符），否则 `422 reason_required` |
| GET | `/handover-tasks/{task_id}` | 我是 assignee 或 subject | 单据详情，含各 APP action、资产分类、代管剩余天数 |
| GET | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}/items` | 同上 | 明细分页，query: `page`、`page_size`、`q` |
| PATCH | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}` | 我是 assignee | body: `{"selected": bool, "default_to_user_id": str\|null}` |
| PUT | `/handover-tasks/{task_id}/actions/{app_key}/assets/{type}/overrides` | 我是 assignee | body: `{"overrides":[{"asset_id":"...","to_user_id":"..."\|null,"label":"..."}]}`，整体替换 |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/preview` | 我是 assignee | |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/execute` | 我是 assignee | |
| POST | `/handover-tasks/{task_id}/actions/{app_key}/retry` | 我是 assignee | 仅 `failed` 可重试 |
| GET | `/handover-candidates` | 登录即可 | 选人控件数据源，query `q`；只返回 active 且非本人；`kind=reassign` 时限定在我的 `MANAGED_USERS` 内 |

**错误码**（门户专用，均为 `{"error":{"code","message"}}`）：

| HTTP | code | 触发 |
|---|---|---|
| 403 | `out_of_managed_scope` | reassign 的 subject 不在我的管辖范围（契约 §4） |
| 409 | `open_task_exists` | 自助建单时已有 open 的 offboard/transfer 单 |
| 422 | `reason_required` | reassign 未填理由或不足 10 字符 |
| 422 | `receiver_not_active` / `receiver_is_subject` / `asset_type_not_releasable` / `nothing_selected` | §5.4 |
| 400 | `detail_not_supported` | 该资产类型不支持明细 |

### 6.2 交接单详情响应体（前端据此建类型）

```json
{
  "id": 137,
  "kind": "offboard",
  "status": "in_progress",
  "generation": 1,
  "subject": { "user_id": "3f1a…", "name": "王某某", "department": "华东销售部", "status": "departed" },
  "assignee": { "user_id": "8c44…", "name": "李某某", "state": "manager", "escalation_level": 0 },
  "custody": { "expires_at": "2026-08-24T10:00:00Z", "days_left": 14, "active": true },
  "reason": "目录同步检出离职",
  "created_at": "2026-08-10T10:00:00Z",
  "actions": [
    {
      "app_key": "easytrade",
      "app_name": "EasyTrade",
      "status": "previewed",
      "blocked_reason": "",
      "skip_reason": "",
      "last_error": "",
      "asset_types": [
        {
          "type": "customer", "label": "名下客户", "count": 187,
          "detail_supported": true, "releasable": true,
          "selected": true,
          "default_to_user": { "user_id": "d017…", "name": "张某某" },
          "override_count": 2
        }
      ]
    },
    {
      "app_key": "easyproject",
      "app_name": "EasyProject",
      "status": "blocked",
      "blocked_reason": "capability_undeclared",
      "asset_types": []
    }
  ],
  "team_items": [ /* 既有形状不变 */ ]
}
```

`GET /me/handover-tasks` 的列表项是上述对象去掉 `actions`/`team_items`，另加
`pending_app_count`、`blocked_app_count`、`total_asset_count`。

### 6.3 控制台（`/console/api/v1/lifecycle/`，超管）

既有端点保留。新增：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `.../handover-tasks/{id}/actions/{app_key}/skip` | 强行跳过（D6），body `{"reason": "..."}`，`reason` 必填且 ≥10 字符 |
| POST | `.../handover-tasks/{id}/claim` | 超管认领 `superuser_pool` 中的单，assignee 置为该超管，`assignee_state=manager` |
| POST | `.../handover-tasks/{id}/custody/extend` | 手动续 14 天（不改 `escalation_level`），必填理由 |
| GET | `.../handover-blocked-apps` | 未接入 APP 汇总，供控制台顶部告警条 |
| POST | `.../apps/{app_key}/handover-capability` | 声明 `none`，body `{"reason": "..."}`；写 `declared_by`/`declared_at` |
| POST | `.../apps/{app_key}/handover-capability/sync` | 手动触发 §5.2 descriptor 同步 |

控制台复用 §6.1 的资产/明细端点，但走 `require_superuser` 且不做 assignee 校验。

---

## 7. 异步任务（`tasks/lifecycle.py`，新建）

| 任务 | 周期 | 逻辑 |
|---|---|---|
| `lifecycle_custody_expiry` | beat 每 10 分钟 | 扫 `revoked_at IS NULL AND expires_at <= now` 的 `CustodyGrant`，逐个 `escalate_custody()`。PostgreSQL 下 `select_for_update(skip_locked=True)` 分批，避免多 worker 抢同一批（与 `grants` 过期任务同款） |
| `lifecycle_custody_reminder` | beat 每天 09:00（Asia/Shanghai） | 对未收回且单未完成的代管发钉钉提醒；用 `last_reminded_on` 去重保证每日一次；到期前 1 天额外发"即将到期" |
| `lifecycle_superuser_pool_reminder` | beat 每天 09:05 | `assignee_state=superuser_pool` 且未完成的单，向全体超管推认领通知 |
| `lifecycle_blocked_apps_digest` | beat 每周一 09:10 | 汇总 `blocked` action，向超管推周报 |

全部通过 `outbox.enqueue_task` 入队，遵循既有「网络副作用出事务」的约定。
通知内容与收件人见契约 §13，模板放 `notify/messages.py`。

---

## 8. SDK 改造（`sdk/python/src/easyauth_app_sdk/lifecycle.py`）

1. 新增事件常量 `HANDOVER_ITEMS_EVENT: Final = "lifecycle.handover.items"`。
2. `lifecycle_http_response()` 增参 `on_handover_items: HandoverCallback`，按事件分发。
3. `DEFAULT_MAX_BODY_BYTES` 由 `64 * 1024` 改为 `256 * 1024`（契约 §10.1）。
4. `fastapi.py` 的挂载 helper 同步增加 items 回调参数。
5. 新增 `easyauth_app_sdk/handover_payloads.py`：v2 请求/响应的 `TypedDict` 定义
   （`PreviewRequest`/`PreviewResponse`/`ItemsRequest`/`ItemsResponse`/`ExecuteRequest`/`ExecuteResponse`），
   下游 APP 直接 import 使用，杜绝字段名手抄出错。
6. `sdk/python/CHANGELOG.md` 记为 **breaking**，版本号 minor 升级（未上线，不做兼容分支）。
7. `sdk/python/README.md` 补 v2 接入示例（中文）。

---

## 9. ADR 修订（契约 §3.1）

### ADR-002 修订点 1（§19）

在 `MANAGED_USERS` 定义后追加：

> **例外（数据交接代管）**：当查询者持有针对某交接单的未到期 `CustodyGrant` 时，该交接单当事人
> （`HandoverTask.subject_user`）会被并入其 `MANAGED_USERS`，**即使该用户为 `departed` 或 `disabled`**。
> 这是全系统唯一允许非 active 用户进入该集合的场景，目的是让交接负责人在业务系统里看得见待交接数据。
> 实现位置 `grants/managed_users.py`，代管授权到期或收回后自动消失。
> 下游应用因此**不得**以本地用户 inactive 为由从 scope 集合中剔除成员。

### ADR-002 修订点 2（§36）

原「审批人必须严格为申请人的 active 直属主管；缺少可解析的直属主管时禁止提交」改为：

> 审批人按 `manager_chain` 逐级向上取第一个 active 主管（跳过 departed/disabled/本地管理员/申请人本人）。
> 整条链不可用时进入超管待认领池，由超管审批。仍然**禁止**手动改填 App owner 或任意其他用户绕过。

新增 ADR-005「数据交接 v2 的能力声明与阻塞语义」，记录 D6 的决策与"静默成功"缺陷的修复。

---

## 10. 测试

| 文件 | 覆盖 |
|---|---|
| `tests/unit/lifecycle/test_assignee.py` | 主管链正常/跳过离职主管/整链失效落池/stale 落池/本地管理员跳过/不设层数上限 |
| `tests/unit/lifecycle/test_custody.py` | 发放后 `MANAGED_USERS` 含 departed subject；到期后不含；自有授权不被误收；逐 APP 收回；上交链路；到顶落池 |
| `tests/unit/lifecycle/test_capability.py` | 三态 → action 初始状态；`declared` 但无 URL 抛错；`none` 缺声明人被约束拒绝 |
| `tests/unit/lifecycle/test_assignments.py` | §5.4 五条校验；`selected=False` 不进 payload；override 唯一约束 |
| `tests/unit/lifecycle/test_upgrade.py` | transfer → offboard 升级：kind 变更、generation+1、action 重置、assignee 重解析、代管发放 |
| `tests/unit/lifecycle/test_reassign.py` | 管辖校验、必填理由、与 offboard 单并存不违反唯一约束、三方通知 |
| `tests/integration/test_portal_handover_api.py` | §6.1 全部端点的权限边界（非 assignee 拿到 404） |
| `tests/integration/test_handover_webhook_v2.py` | payload 形状逐字段比对 `tests/contract_samples/` 下的 golden JSON；幂等键 `(task_id, generation)` |
| `tests/unit/test_blocked_never_completes.py` | 存在 blocked 时 `refresh_task_status` 永不返回 completed（D13） |

新增 `tests/contract_samples/handover_v2/`：`preview_request.json`、`preview_response.json`、
`items_request.json`、`items_response.json`、`execute_request.json`、`execute_response.json`。
**EasyTrade 与 EasyProject 的契约测试直接复用这批样本**，这是跨仓库对齐的机械保证。

### 执行方式

后端测试走 Docker + uv（host `.venv` 不可用）：

```bash
docker run --rm -v "$PWD":/w -w /w <image> uv run --frozen pytest tests/unit/lifecycle -q
```

---

## 11. 交付顺序（本仓库内部）

1. **先提交 §6**（API 契约章节）→ 解锁前端 agent。
2. §2 模型 + 迁移 → `manage.py makemigrations --check` 无漂移。
3. §3 assignee → §4 custody → §5 handover 执行链。
4. §7 异步任务 → §8 SDK → §9 ADR。
5. §10 测试补齐。

每完成一项立即单独 commit；提交后必须重建前后端并确认构建命令成功结束（`AGENTS.md`）。
后端改动后必须重启 Django 开发服务，并用目标 URL 的真实 HTTP 响应验证新代码已加载。
