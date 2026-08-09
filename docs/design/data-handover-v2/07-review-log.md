# 07 · 复核记录与未决事项

> 本文件记录对全部设计文档的历次对抗式复核结果与处置。
> **它不是设计文档，而是"这套设计现在可不可信"的账本。** 开工前必读。

---

## 0. 当前状态

### 第三轮（2026-08-10，7 路并行）—— A5 的解阻材料已备齐（门禁待批）

本轮做了两件事：**起草解阻材料**，以及**七片对抗式复核**。

**解阻材料**（新增两份文档）：

| 文档 | 内容 | 下一步 |
|---|---|---|
| [`08`](08-easyproject-ag00-rulings.md) | AG-00 的两份裁定：**所有权**（逐表 owner + 六个 `system_handover` 命令签名 + 三条并行 revision + 评审签署回滚）与 **system-actor 语义**（actor 表示、锁内版本、幂等键、审批锁、豁免边界、通知责任） | AG-00 审核 → 追加进 `EasyProject/contracts/ownership.md` |
| [`09`](09-easyproject-ccr.md) | 按 `contracts/workflow.md` 六要素写全的 CCR 正文，11 个错误码 | AG-00 提交进 CCR 流程 |

A5 的开工前置从"等两份不存在的裁定"变成"等三样可机械核对的凭据"（README「A5 的三道门禁」）。

**复核**：七片（跨文档一致性 / EasyAuth 后端 / EasyAuth 前端 / EasyTrade / EasyProject /
安全并发 / 可实施性）共产出 **约 130 条**，其中 BLOCKER 约 60 条。**全部逐条对照代码验证后落文档**。

本轮最值得记住的几条（都不是文字问题，是照做必错）：

| # | 问题 | 后果 |
|---|---|---|
| 1 | **`HandoverExecutionAttempt` 单表自相矛盾** —— 既 append-only 又要回填结果 | 一次请求的最终成败无处安放。拆成不可变 Batch + append-only DeliveryAttempt |
| 2 | **413 分批与 action 级 `done` 互斥** | 第一批成功后 action 置 `done`，第二批既不能 execute 也不能 retry，剩余资产永远搬不走而单据显示已完成 |
| 3 | **异步 202 路径直接置 `done`** | 既不落 `data_completed_at` 也**根本不转授权限**，离职者授权原地不动 |
| 4 | **202 没有任何轮询任务** | `async_pending` 是个死胡同，永远到不了终态，租约也永不释放 |
| 5 | **租约没有过期字段** | worker 崩一次，条件唯一约束就永久锁死 `(subject, app)` |
| 6 | **快照失效与身份冲突都用 409** | 两者处置相反（退回重预演 vs 判失败），而 EasyAuth 被禁止解析响应体 —— 无从区分。改用 **412** |
| 7 | **`event_type` 校验只写了接收端** | EasyAuth 自己的 `webhook.test` body 里没有该字段，新 SDK 一上线联调门禁永远过不去 |
| 8 | **descriptor 有三道白名单不是两道** | EasyAuth 自己的 `_LifecyclePayload` 是 `extra="forbid"`，下游推 manifest 直接抛校验错 |
| 9 | **`ApprovalRule.approver_userids` 存的是 sub 不是 dtuid** | 按 dtuid 替换一项都匹配不到，规则里仍挂着离职者且不报错 |
| 10 | **OpenProject 人员投影整段漏掉** | assignee 投影成 OP 自定义字段而 M34 对账「永不改人员字段」—— OP 侧永久停在离职者身上且无自动修复 |
| 11 | **execute 没绑定用户看过的 preview 版本** | 并发重新预演会把用户从没见过的数据一起搬走 |
| 12 | **override 整体 PUT 却没有读回接口** | 刷新页面后改一条就把其余全部静默删掉 |
| 13 | **跨表 `CheckConstraint`** | Django 判 `models.E041`，迁移直接失败 |
| 14 | **迁移章节写「删除 `to_user`」** | 与 §2.2 的 `RenameField` 矛盾，删了 `transfer_selected_grants()` 就没有输入 |

### 前两轮：三处结构性问题全部定案

第二轮复核（6 路并行，覆盖代管 scope / 并发幂等 / EasyAuth 后端 / EasyTrade / EasyProject / 跨文档一致性）
共产出约 70 条发现。机械性矛盾已修（见 §2）。三处结构性问题中：

- §1.1 代管授权 —— ✅ **定案：整体砍掉**，范围随之大幅收窄
- §1.2 D11 被下游静默豁免 —— ✅ **定案：审批责任纳入本期，`WorkRecord` 写成显式例外**
- §1.3 EasyProject 实施可行性 —— ✅ **定案：完整做**。两份裁定与 CCR 已起草（`08`/`09`），**但门禁尚未通过**（CCR 仍是 `PROPOSED`，裁定正文也还没合进 `EasyProject/contracts/ownership.md`），A5 目前只能做 README「现在就能做」的三项

§3.2–§3.6 中与代管无关的发现**已全部落入各自文档**（见各节标题的状态标记）。

**仍未处理的少数项**（都不是 blocker，且都已在正文里显式记为缺口）：

| 项 | 为什么暂不处理 |
|---|---|
| 建立权威超管收件人镜像 | 「通知全体超管」当前实现不了（超管资格只在请求期远程判定）。本期改为控制台常驻告警条，镜像列为独立后续项 |
| 钉钉在途审批实例转办（以及逐条清单） | 客户端无转办接口；`ApprovalInstance` 也不存当前审批人、与 `ApprovalRule` 无关联，因此**清单本身也做不到**。补做条件：先持久化当前审批人，再确认钉钉转办 API。见 `00` §11.1 |
| `EasyProject WorkRecordRow` 归属列 | D11 的显式例外，需独立领域改造 |
| HMAC 覆盖 event/delivery 头 | 改签名串要同步全部下游与已冻结的向量，成本高。本期补偿升级为**在 body 里加签名覆盖的 `event_type` 字段**（四事件无例外，SDK 在 `webhook.test` 短路前比对）——原先的「校验 event 与 body `mode` 一致」有两个洞：`items` 没有 `mode`，`webhook.test` 根本不看 body |
| EasyProject 消费快照（原 P1） | 代管砍掉后失去本期依据，降级为已知偏差另行立项 |

---

## 1. 未决：需要拍板的结构性问题

### 1.1 ~~代管授权（D4）整体不成立~~ —— ✅ **已定案：整体砍掉**

原设计旧稿（已被现行 `00` §7.2 整体替换）：用新 scope `HANDOVER_CUSTODY` 发放委托授权，并把离职者并入 assignee 的
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

**处置（已定案）**：采用 §3.1 **方案 B** —— **砍掉代管**，悬置期的可见性改由交接单自身的资产明细承担。
已重写 `00` §7、`01` §2.5/§4/§9，并连带取消：`03` 的 B3、`05` 的 P1、ADR-002 §19 修订、
以及 `04`/`06` 两份下游前端文档（离职者不再进入任何人的 `MANAGED_USERS`，F1/F2/F3 三个故障不会发生）。

代价是主管只能靠 `items.hint` 判断归属，因此 `hint` 从"可选摘要"升级为**硬要求**，
各 APP 文档已列出逐类必含要素与验收断言。

### 1.2 ~~D11 被下游文档静默豁免~~ —— ✅ **已定案**

`00` §3 D11 与 §11 判例明确规定「待审批单据中当前审批人是离职者 → **必须转移**」，
但 `05` §3.1.1 与 README「已知缺口」把它列为本期不做；
`WorkRecordRow.created_by_` 明知承担当前归属语义，也只保证代管期可见——代管一结束又是黑洞。

**处置（已定案）**：审批责任**纳入本期**，`WorkRecordRow.created_by_` 写成 D11 的显式例外。
已在契约新增 §11.1「D11 的两条显式例外」，并在 `01` 新增 §4.5「审批责任改派」。

但复核后查清：**"审批人"其实是两件被混在一起的事，可行性天差地别**（这一点原复核也没分开）：

| | 事实 | 本期 |
|---|---|---|
| EasyAuth 自身的权限申请审批 | `AccessRequestApprover.approver` 是本地表、直接外键 `UserMirror`（`access_requests/models.py:339`） | **必做**，沿**申请人**（不是离职者）的主管链改派 |
| 钉钉审批**规则**的审批人配置 | `ApprovalRule.approver_userids` 是本地 JSON 列表（`applications/models.py:717`） | **必做**，替换离职者；替换后为空则快速失败进超管待办 |
| 钉钉**在途实例**的当前审批人 | `ApprovalInstance` 既**不存**当前审批人（只有 `originator_user`），**也与 `ApprovalRule` 没有任何关联字段**（`workflows/models.py:147-183`）；钉钉客户端只有 `create_process_instance`/`get_process_instance`，**无转办接口** | **连逐条列清单都做不到** —— 按 APP 粗匹配必然同时漏报误报，条数是假数字。本期只做**按 APP 的存在性警示 + 钉钉入口**，不列实例、不报条数 |

第三行是本期真正的缺口，补做条件：确认钉钉开放平台提供转办 API 后，封装该调用并在
`ApprovalInstance` 上跟踪当前审批人。

### 1.3 ~~EasyProject 实施可行性存疑~~ —— ✅ **已定案：完整做，但先阻塞**

`05` §4.1.1 要求各领域提供 `system_handover` 命令。复核核实：现有命令**无法直接复用** ——
task reassign 要 actor / 角色 / scope / `state_version` / 幂等键 / reason 且拒绝审批锁且只能改 assignee；
project **根本没有 owner-change 命令**，`replace_members` 强制 OWNER 等于旧 owner；
recurrence patch 不支持 assignee/assigner。**而 webhook 没有合法的人类 actor。**

同时所有权跨 M03/M05/M06/M07/M08/M10/M13/M14/M18/M19/M40 十余个模块，
`contracts/ownership.md` 甚至没登记 work-record 表。

**处置（已定案）**：EasyProject **完整做**（preview + items + execute 全量），
但 **A5 阻塞，等 AG-00 完成两项裁定后才开工**：

1. **所有权裁定**：交接触及 M03/M05/M06/M07/M08/M10/M13/M14/M18/M19/M40，
   `contracts/ownership.md` 需补登记（含尚未登记的 work-record 表），明确 M06 只编排、各领域 owner 出命令。
2. **system-actor 语义裁定**：webhook 触发没有人类 actor，而现有命令都要求 actor / `state_version` /
   幂等键 / reason 且会被审批锁拒绝。需要定义一个系统 actor 身份及其在审计、锁、版本读取上的语义。

在裁定完成前，A5 可以做的只有：§2.1 身份映射（P2）、§2.3 `hint`、以及各领域内部的只读查询实现。

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

## 3. 已接受的发现与落文档情况

### 3.1 代管选型候选（对应 §1.1）

| 方案 | 做法 | 代价 |
|---|---|---|
| A 泛化人员集合 scope | 把「带 resolved 的人员集合 scope」抽象成一等契约：解析层、序列化层、SDK、两个下游的 scope 处理全部支持任意此类 scope，每条 custody grant 自带精确 `resolved.user_ids` | 改动面最大，但唯一能正确表达"按人委托" |
| B 砍掉代管 | 悬置期不给主管任何业务系统权限；改为在 EasyAuth 门户的交接单里直接展示各 APP 的资产明细（items 接口已有），主管据此判断给谁 | 最小；代价是主管**看不到业务上下文**（客户最近在谈什么），判断质量下降 |
| C 只读代管 | 只发只读能力，且仍需 A 的 scope 机制 | 未真正降低复杂度 |

### 3.2 并发与执行（切片 2）—— ✅ 已落文档

- 授权转移**先于**数据 webhook 执行（`handover.py:182` vs `:190`）→ webhook 失败时"数据没搬、权限已转"，状态机表达不了。必须改为数据成功后再幂等转授，并引入 `data_completed` / `grants_completed` 子状态。
- 永久失败的 action 让整张单**既不能跳过也不能取消**（`skip_action` 卡 `attempts`、`cancel_task` 卡 `attempts__gt=0`）→ 死锁。
- `refresh_task_status()` 只升不降，且 preview 成功后未调用 → 升级重置或 capability 恢复后出现「task in_progress 但全部 action pending」。
- 单个 `execution_payload` 无法承载多批历史，需 append-only `HandoverExecutionAttempt`，唯一约束 `(action, generation, batch_seq)`。
- 执行互斥需持久化租约行（含 owner/fence），短事务 `select_for_update` 跨 worker/Celery 不成立。
- `HandoverGrantItem` / `CustodyGrant` 缺 generation，升级后新旧混用。

### 3.3 EasyAuth 后端（切片 3）—— ✅ 主要项已落文档

- 门户 guard 只查 session subject + active，本地超管会生成 active `local-admin:` UserMirror → **可冒充员工调用自助 API**。门户必须显式拒绝本地管理员。
- 「通知全体超管」当前不可实现：超管资格只在请求期远程查 Authentik，没有可枚举的本地成员表。
- `我的 MANAGED_USERS` 不是全局概念（按 app + grant 策略求值，且可能实时调目录并 503）→ reassign 的管辖判定需要独立的、由目录同步维护的主管闭包。
- 错误体与仓库现状冲突（现有结构含 `details`、大写 `ErrorCode`）；缺 401/404/409/429/503、CSRF 与限流规定。
- `tasks/lifecycle.py` 已存在（不是"新建"）；beat 直接投递不走 outbox；schedule 只接受 float interval，crontab 需扩展。
- 多个不变量未落库：asset action / capability / revoke trigger 缺 check、`generation` 允许 0、未约束 assignee ≠ subject。

### 3.4 EasyTrade（切片 4）—— ✅ 已落文档

- **descriptor 形状冲突**：不是手写，而是经 `easyauth_manifest_export._lifecycle()` 产出，该校验器只接受并只返回 `{handover_url, onboard_url, capabilities}`（`:109,117-121`）。设计里的嵌套 `lifecycle.handover` 会被拒绝或剥掉。应扩既有结构（已有 `lifecycle.capabilities` 列表）。
- 8 类资产的终态判定普遍不全：订单缺 `cancelled_at`；询盘缺 `deleted_at`/`lost_at`；任务应为 `status='OPEN' AND voided_at IS NULL`；样品申请缺三个 CLOSED 状态；需求终态集应为 `COMPLETED/REJECTED/MERGED`（`ON_HOLD` 仍活跃）。
- `receivable_open` 谓词忽略有效归属：`domain/ar/ownership.py` 定义 owner 为 NULL 时继承订单负责人，现有 `_open_receivables()` 只看显式 owner。
- 只校验了 `release`，**未校验 `transfer` 的接收人非空** → 可空列静默释放、非空列 flush 时才炸。
- override id 未先验证存在/仍属当事人/仍匹配谓词就排除出默认集 → 无效 id 被静默跳过而非 409。
- 副作用缺失：任务改派须清 `reminder_dismissed_at`；订单改 owner 须写 `order.update` 审计；客户释放公海应走 `auto_release` 而非 `transfer` 事件。
- `/api/v1/user-candidates` 始终过滤 `active=true`，`fetchUserCandidateById()` 其实不按 id 取——离职者当前值仍会显示失败。
- `tasks_scope.py` 用 `created_by_user_id` 参与鉴权 → 代管期会连带暴露"仅由该人创建"的任务。

### 3.5 EasyProject（切片 5）—— ✅ 已落文档

- `06` 的「无后端改动」不成立：`isActive` 只在**目录 API** 有，task/project/board/work-record 的 `UserBrief` 都没有状态字段。
- 「仅看已离职人员的数据」现有过滤 API 表达不了（任务只有 `assigneeId[]`，项目只有单值 owner/member）。
- 审批列表响应根本不返回 requester；周期模板前端界面不存在。
- 终态口径不全：项目须排除 `COMPLETED/CANCELLED`；三类 task 同上；三类 recurrence 须 `is_enabled=true`；work-record participant 须 `status='OPEN'`。
- `project_member` 定义含 OWNER 而 §4.3 说只处理非 OWNER → 重复计数；OWNER 部分唯一索引非 deferrable，先升级接收人会立即冲突。
- ~~CCR 范围不止错误码：custody scope / permission baseline 也要变~~ —— **该结论已随代管废弃过期**。
  实际影响面是 **0 新 scope、0 新 permission、0 新 operation、0 schema 变更**，只改 1 个既有 operation 的元数据。
  但 `generate_baseline.py` 本身必须改，否则再生会静默覆盖新增错误码 —— 这一条仍然成立，
  已写进 `09` §6 与 `05` §5.2。
- 401 与契约 §10.1 的 403 定级冲突需裁定。

### 3.6 跨文档（切片 6）—— ✅ 已落文档

- D5 冻结 14 天，`01` 却允许环境变量覆盖 + 超管续期。
- D9 规定跨部门由超管发起，但冻结 API 没有超管跨范围创建 `reassign` 的端点。
- `01` 要求每 APP 独立 `grant_receiver`，但冻结 API/DTO 无该字段，`02` 又删光了 APP 级接收人 UI。
- `02` 的 `HandoverAction` 类型没有 `summary`，但 done 界面要展示它。
- README 的 SDK 串行头 / CCR 门禁 / A6 立即开工，与 `00`/`03`/`05` 正文的旧说法并存。
- README 声称强制校验 event header 与 body `mode`，两个下游都没安排实现与验收用例。

---

## 5. 第三轮的处置原则（新增）

1. **凡是"这件事做不到"的，改成如实说做不到，并写清补做条件** —— 不许留下一个听起来能做、
   实现时才发现做不到的承诺。本轮据此降级了两处：钉钉在途审批实例的**逐条清单与条数**
   （`ApprovalInstance` 与 `ApprovalRule` 无关联，粗匹配的 N 是假数字）、
   以及**向全体超管推送**（没有可枚举的超管名单）。
2. **凡是"二选一，PR 里写明结论"的，本轮尽量当场定死** —— 两个下游各选一种实现，
   契约测试就没法复用。generation 水位、幂等键格式、错误码分工都已收敛为单一方案。
3. **凡是跨仓库的门禁，凭据必须可以贴出来** —— "批准了"不能当开工依据。
   SDK vNext 用「版本号 + commit SHA + wheel SHA-256 + 下游 `VENDORED.md`」，
   A5 用「ownership.md 合入 SHA + CCR 编号与 APPROVED 状态」。

---

## 4. 复核方法学备忘

两轮复核里出现过**结论对但理由反了**的情况（提醒 recipient 那条：复核称"改了会被判 stale"，
实际是**不改才 stale**，且 `reminder_enqueue.py:313-315` 是整组 fail-closed）。

因此规矩是：**复核结论值得采纳，给出的理由必须自己对照代码验证。**
本文件中标注了代码位置的条目均已验证；未标注位置的属尚待验证。
