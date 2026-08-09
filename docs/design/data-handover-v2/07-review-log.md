# 07 · 复核记录与未决事项

> 本文件记录对 `00`–`06` 的两轮对抗式复核结果与处置。
> **它不是设计文档，而是"这套设计现在可不可信"的账本。** 开工前必读。

---

## 0. 当前状态：**不可进入实施**

第二轮复核（6 路并行，覆盖代管 scope / 并发幂等 / EasyAuth 后端 / EasyTrade / EasyProject / 跨文档一致性）
共产出约 70 条发现。机械性矛盾已修（见 §2），但**三处需要决策的结构性问题尚未解决**（§1），
其中任何一处不定，实施都会返工。

---

## 1. 未决：需要拍板的结构性问题

### 1.1 代管授权（D4）整体不成立，需重新选型 🔴

原设计（`00` §7.2）：用新 scope `HANDOVER_CUSTODY` 发放委托授权，并把离职者并入 assignee 的
`MANAGED_USERS`。**四条独立的致命问题，均已对照代码验证：**

| # | 问题 | 证据 |
|---|---|---|
| 1 | **并入 `MANAGED_USERS` 本身就是提权。** 该 scope 的解析结果按 scope 求值后喂给 assignee 的**全部**同 scope 授权。主管若已有 `customer.delete@MANAGED_USERS`，注入后就获得了对离职者客户的删除权——一项离职者自己都没有的能力 | `grants/query.py:224,270` |
| 2 | **代管无法按人区分。** 唯一约束是 `(grant, permission, scope_key)`，同一主管同时代管两人的同一 permission 直接撞键；共用一行则撤销任一任务会误撤另一个 | `grants/models.py` `grants_access_grant_permission_unique` |
| 3 | **序列化层直接丢弃。** `if scope != "MANAGED_USERS": return None`——任何带 `resolved` 的其他 scope 被静默丢掉 | `api/serializers.py:261` |
| 4 | **manifest 同步会冲掉。** `permission.supported_scopes = list(spec.supported_scopes)` 整体覆盖，下次推送即失效 | `applications/permission_template_storage.py:417` |

另外两个下游对未知 scope 都是**静默跳过**（EasyTrade `enterprise_platform/authz/core.py`、
EasyProject `domain/authz/types.py`），且 EasyProject 的 `MANAGED_USERS` 谓词会自动并入 SELF
（`scope_predicate.py`），与"仅 source_subject"直接冲突。

**候选方案见 §3.1。这一条不定，`00` §7、`01` §2.5/2.6/§4、`03` §3.1、`05` §2.2 全部要重写。**

### 1.2 D11「只转活的责任」被下游文档静默豁免 🔴

`00` §3 D11 与 §11 判例明确规定「待审批单据中当前审批人是离职者 → **必须转移**」，
但 `05` §3.1.1 与 README「已知缺口」把它列为本期不做；
`WorkRecordRow.created_by_` 明知承担当前归属语义，也只保证代管期可见——代管一结束又是黑洞。

**下游文档不能单方面豁免冻结决策。** 要么纳入本期（需扩展 EasyAuth 审批契约 + EasyProject 新增
owner 列与迁移），要么**显式修订 D11** 并写明例外与补做条件。

### 1.3 EasyProject 的实施可行性存疑 🟠

`05` §4.1.1 要求各领域提供 `system_handover` 命令。复核核实：现有命令**无法直接复用** ——
task reassign 要 actor / 角色 / scope / `state_version` / 幂等键 / reason 且拒绝审批锁且只能改 assignee；
project **根本没有 owner-change 命令**，`replace_members` 强制 OWNER 等于旧 owner；
recurrence patch 不支持 assignee/assigner。**而 webhook 没有合法的人类 actor。**

同时所有权跨 M03/M05/M06/M07/M08/M10/M13/M14/M18/M19/M40 十余个模块，
`contracts/ownership.md` 甚至没登记 work-record 表。

**需 AG-00 先做所有权与 system-actor 语义裁定**，否则 A5 无法启动。

---

## 2. 已修（本轮）

| 类别 | 内容 |
|---|---|
| 契约示例自相矛盾 | `inquiry_open` 声明 `releasable=false` 却示例 `release`；订单默认 skip 却报 `transferred:23`；items 带 `q` 却 `total:187`；`from_user_id` 三处写法不一 |
| 守恒公式歧义 | 改为全量恒等式，右边恒等于 preview 的 `count`，无 `default_action` 分支 |
| 分批 vs 快照令牌 | 二者原本互斥（首批改数据后次批必然 token 失效）。明确**每批重新 preview 取新 token** |
| 幂等键 | 三元组 `(task_id, generation, batch_id)` 统一到 00/01/03/05 与事件表 |
| `nothing_selected` | 删除。全 skip 是合法 no-op，零资产 APP 需要它确认完成 |
| 补零掩盖违约 | APP 漏报已声明类型改为直接 `failed`，删除补零逻辑（违反 `AGENTS.md`） |
| 字段名 | `OverrideSpec.asset_id` → `id`，对齐冻结契约 |
| 资产类数 | EasyProject 统一为 9 类（残留 11 类） |
| 契约样本 | 改从 `easyauth_app_sdk.contract_samples` 包内读取，缺失必须 fail |
| 迁移 | `to_user → grant_receiver` 明确用 `RenameField` |
| 文案 | 前端 `release`（释放为无主）与 `skip`（暂不处理）分开 |
| 事实更正 | 全局 scope 实际叫 `ALL` 不是 `GLOBAL` |

---

## 3. 已接受但尚未落文档的发现（下一轮修）

### 3.1 代管选型候选（对应 §1.1）

| 方案 | 做法 | 代价 |
|---|---|---|
| A 泛化人员集合 scope | 把「带 resolved 的人员集合 scope」抽象成一等契约：解析层、序列化层、SDK、两个下游的 scope 处理全部支持任意此类 scope，每条 custody grant 自带精确 `resolved.user_ids` | 改动面最大，但唯一能正确表达"按人委托" |
| B 砍掉代管 | 悬置期不给主管任何业务系统权限；改为在 EasyAuth 门户的交接单里直接展示各 APP 的资产明细（items 接口已有），主管据此判断给谁 | 最小；代价是主管**看不到业务上下文**（客户最近在谈什么），判断质量下降 |
| C 只读代管 | 只发只读能力，且仍需 A 的 scope 机制 | 未真正降低复杂度 |

### 3.2 并发与执行（切片 2，14 条）

- 授权转移**先于**数据 webhook 执行（`handover.py:182` vs `:190`）→ webhook 失败时"数据没搬、权限已转"，状态机表达不了。必须改为数据成功后再幂等转授，并引入 `data_completed` / `grants_completed` 子状态。
- 永久失败的 action 让整张单**既不能跳过也不能取消**（`skip_action` 卡 `attempts`、`cancel_task` 卡 `attempts__gt=0`）→ 死锁。
- `refresh_task_status()` 只升不降，且 preview 成功后未调用 → 升级重置或 capability 恢复后出现「task in_progress 但全部 action pending」。
- 单个 `execution_payload` 无法承载多批历史，需 append-only `HandoverExecutionAttempt`，唯一约束 `(action, generation, batch_seq)`。
- 执行互斥需持久化租约行（含 owner/fence），短事务 `select_for_update` 跨 worker/Celery 不成立。
- `HandoverGrantItem` / `CustodyGrant` 缺 generation，升级后新旧混用。

### 3.3 EasyAuth 后端（切片 3）

- 门户 guard 只查 session subject + active，本地超管会生成 active `local-admin:` UserMirror → **可冒充员工调用自助 API**。门户必须显式拒绝本地管理员。
- 「通知全体超管」当前不可实现：超管资格只在请求期远程查 Authentik，没有可枚举的本地成员表。
- `我的 MANAGED_USERS` 不是全局概念（按 app + grant 策略求值，且可能实时调目录并 503）→ reassign 的管辖判定需要独立的、由目录同步维护的主管闭包。
- 错误体与仓库现状冲突（现有结构含 `details`、大写 `ErrorCode`）；缺 401/404/409/429/503、CSRF 与限流规定。
- `tasks/lifecycle.py` 已存在（不是"新建"）；beat 直接投递不走 outbox；schedule 只接受 float interval，crontab 需扩展。
- 多个不变量未落库：asset action / capability / revoke trigger 缺 check、`generation` 允许 0、未约束 assignee ≠ subject。

### 3.4 EasyTrade（切片 4）

- **descriptor 形状冲突**：不是手写，而是经 `easyauth_manifest_export._lifecycle()` 产出，该校验器只接受并只返回 `{handover_url, onboard_url, capabilities}`（`:109,117-121`）。设计里的嵌套 `lifecycle.handover` 会被拒绝或剥掉。应扩既有结构（已有 `lifecycle.capabilities` 列表）。
- 8 类资产的终态判定普遍不全：订单缺 `cancelled_at`；询盘缺 `deleted_at`/`lost_at`；任务应为 `status='OPEN' AND voided_at IS NULL`；样品申请缺三个 CLOSED 状态；需求终态集应为 `COMPLETED/REJECTED/MERGED`（`ON_HOLD` 仍活跃）。
- `receivable_open` 谓词忽略有效归属：`domain/ar/ownership.py` 定义 owner 为 NULL 时继承订单负责人，现有 `_open_receivables()` 只看显式 owner。
- 只校验了 `release`，**未校验 `transfer` 的接收人非空** → 可空列静默释放、非空列 flush 时才炸。
- override id 未先验证存在/仍属当事人/仍匹配谓词就排除出默认集 → 无效 id 被静默跳过而非 409。
- 副作用缺失：任务改派须清 `reminder_dismissed_at`；订单改 owner 须写 `order.update` 审计；客户释放公海应走 `auto_release` 而非 `transfer` 事件。
- `/api/v1/user-candidates` 始终过滤 `active=true`，`fetchUserCandidateById()` 其实不按 id 取——离职者当前值仍会显示失败。
- `tasks_scope.py` 用 `created_by_user_id` 参与鉴权 → 代管期会连带暴露"仅由该人创建"的任务。

### 3.5 EasyProject（切片 5）

- `06` 的「无后端改动」不成立：`isActive` 只在**目录 API** 有，task/project/board/work-record 的 `UserBrief` 都没有状态字段。
- 「仅看已离职人员的数据」现有过滤 API 表达不了（任务只有 `assigneeId[]`，项目只有单值 owner/member）。
- 审批列表响应根本不返回 requester；周期模板前端界面不存在。
- 终态口径不全：项目须排除 `COMPLETED/CANCELLED`；三类 task 同上；三类 recurrence 须 `is_enabled=true`；work-record participant 须 `status='OPEN'`。
- `project_member` 定义含 OWNER 而 §4.3 说只处理非 OWNER → 重复计数；OWNER 部分唯一索引非 deferrable，先升级接收人会立即冲突。
- CCR 范围不止错误码：custody scope / permission baseline 也要变，且 `generate_baseline.py` 本身需改，否则再生会覆盖。
- 401 与契约 §10.1 的 403 定级冲突需裁定。

### 3.6 跨文档（切片 6）

- D5 冻结 14 天，`01` 却允许环境变量覆盖 + 超管续期。
- D9 规定跨部门由超管发起，但冻结 API 没有超管跨范围创建 `reassign` 的端点。
- `01` 要求每 APP 独立 `grant_receiver`，但冻结 API/DTO 无该字段，`02` 又删光了 APP 级接收人 UI。
- `02` 的 `HandoverAction` 类型没有 `summary`，但 done 界面要展示它。
- README 的 SDK 串行头 / CCR 门禁 / A6 立即开工，与 `00`/`03`/`05` 正文的旧说法并存。
- README 声称强制校验 event header 与 body `mode`，两个下游都没安排实现与验收用例。

---

## 4. 复核方法学备忘

两轮复核里出现过**结论对但理由反了**的情况（提醒 recipient 那条：复核称"改了会被判 stale"，
实际是**不改才 stale**，且 `reminder_enqueue.py:313-315` 是整组 fail-closed）。

因此规矩是：**复核结论值得采纳，给出的理由必须自己对照代码验证。**
本文件中标注了代码位置的条目均已验证；未标注位置的属尚待验证。
