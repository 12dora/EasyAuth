# 00 · 数据交接 v2：总体设计与跨系统契约

> **本文件是所有并行开发 agent 的唯一基准。** EasyAuth、EasyTrade、EasyProject 三个仓库的改造设计
> （`01`–`06` 六份，同目录）都从本文件派生。
> 本文件中的字段名、事件名、状态值、错误码是**冻结契约**，任何一方不得单独修改；确需变更时先改本文件，再同步全部下游文档。

---

## 1. 背景与问题

员工离职后数据交接困难：老员工的数据不能自助交接，也不能由管理员一次性交接给其他员工，只能人工逐个系统复制，
应用一多必然遗漏。

现状盘点（2026-08-10，基于主线代码）：

| 能力 | 现状 | 结论 |
|---|---|---|
| 离职检出 → 冻结权限 → 建交接单 | 已实现（`accounts/services.py:56`、`lifecycle/offboarding.py:92`） | 保留 |
| 逐 APP 指定接收人、两阶段 preview/execute | 已实现（`lifecycle/handover.py`） | 扩展 |
| 待交接缓冲（无接收人时无限期挂起） | 已实现（`lifecycle/models.py:111`） | 保留并补齐可见性 |
| SDK 交接 webhook 内核 | 已实现（`sdk/python/src/easyauth_app_sdk/lifecycle.py`） | 扩展为 v2 |
| EasyTrade 下游落地 | 已实现，覆盖 4 类资产 | 扩展并修 bug |
| **自助交接（非超管可操作）** | **完全没有**，`admin_console/lifecycle_api.py` 全部 `require_superuser`，门户无任何 lifecycle 路由 | 新建 |
| **未接入 APP 的识别** | **静默当作"无数据"并标记成功**（`handover.py:122,325,590`） | 修正为阻塞 |
| **EasyProject 接入** | 未接入（只接了 directory/authz/approval/notify 四个适配器） | 新建 |
| **悬置期数据可见性** | 无。离职者不在任何人的 `MANAGED_USERS` 里（ADR-002 §19），其名下数据在业务系统里对所有人不可见 | 由交接单的资产明细承担（§7） |
| **部分交接 / 二次转交** | 无。execute 是全量、单接收人、不可逆 | 新建 |

### 1.1 三个必须解决的正确性问题

1. **系统在骗人**：未登记 `handover_url` 的 APP，交接单上显示"已完成"，与"确实没有该员工数据"无法区分。
   违反 `AGENTS.md`「不得使用静默默认值、空结果兜底或绕行逻辑掩盖真实问题」。
2. **悬置期黑洞**：交接单挂在待交接列表期间，下游未收到 execute，数据 owner 仍是离职者，而离职者已被移出所有人的
   可管人员集合 —— 那批客户、在途订单、未结应收对全公司不可见，业务停摆。
3. **EasyTrade 释放路径写坏不变量**：无接收人时把非空约束的 `Order.owner_user_id` 置 NULL
   （`easytrade/backend/app/domain/authz/easyauth_handover.py:123`），事务本应失败；而 `Inquiry` 又走了
   "保持原归属"的静默兜底分支。两个分支都必须改成显式契约。

---

## 2. 目标形态（一句话）

> 交接不再是"离职后由超管补救"，而是**一等的数据移交能力**：任何一次人员变动（离职、转岗、在职调整、纠错）
> 都产生一张有明确责任人、有截止压力、有完整资产清单、可逐条改派、全程审计的交接单；
> 没有任何一个 APP 能以"我没接入"的方式从这张单上隐身。

---

## 3. 已决策清单（不可再议，实现必须遵循）

| # | 决策 | 说明 |
|---|---|---|
| D1 | 交接主体是**主管 + 接收人** | 离职者本人在职期间可自行发起；离职时未走完则自动落到组织树上的主管；超管全权 |
| D2 | 主管**只接管"事"** | 主管是交接单负责人（`assignee`），负责指定真正的接收人；数据不会自动落到主管名下 |
| D3 | assignee 沿主管链**逐级向上**解析 | 跳过 departed/disabled，取第一个 active；整条链不可用则进**超管待认领池**。单子必须建得出来 |
| D4 | 悬置期的可见性靠**交接单本身** | ~~发限时代管授权~~（复核后废弃，见 §7）。改为在交接单里直接展示各 APP 的资产明细，主管据此判断归属；**不发放任何临时授权、不新增 scope、不碰 `MANAGED_USERS`** |
| D5 | 交接单 **14 天**，每天钉钉提醒 | 到期未完成则 `escalation_level += 1`，**自动上交上一级主管**，到顶落超管池。截止压力作用在单据上，不再涉及任何授权 |
| D6 | 未声明交接能力的 APP **阻塞** | 状态 `blocked`，交接单不能整体完成；超管填理由可强行 `skipped` |
| D7 | 在职提前交接**只搬数据，不动权限** | 用独立单据类型 `pre_offboard`（**与「转岗」不是一回事**，见 §6.1）；员工正常工作到最后一天；离职日到来时**同一张单升级为 offboard 并重新盘点** |
| D8 | 支持**二次转交** | 升级为通用数据移交：任意两名在职员工之间也可发起（`kind=reassign`），用于纠错与重分配 |
| D9 | 在职移交发起权在**主管** | 仅限自己管辖范围内；跨部门走超管；必填理由；执行后通知转出方/接收方/上级三方；全程审计 |
| D10 | 粒度：**按类型默认全选 + 逐条反选改派** | 一个 APP 内允许多个接收人（接收人下沉到条目级） |
| D11 | 范围标准：**只转"活的责任"** | 当前负责人、待办、待审批、未完成项全部转；创建人/评论/操作日志等历史事实一律不动。**两条显式例外见 §11.1**，不得由下游文档自行豁免 |
| D12 | 接收人**不需点同意** | 执行后通知即可。卡在接收人手上会让交接再次拖死 |
| D13 | 交接单完成 = 全部 APP action 处于 `done` 或 `skipped` | 存在任何 `blocked`/`pending`/`failed` 即未完成 |

### 3.1 必须修订的既有 ADR

| ADR | 现行条款 | 修订为 | 原因 |
|---|---|---|---|
| ADR-002 §36 | 自助申请审批人必须严格为 active **直属**主管；缺失时禁止提交，不允许向上找 | 改为：沿 `manager_chain` 逐级向上取第一个 active 主管；整链不可用时进超管待认领池 | 与 D3 直接抵触 |

> 修订 ADR 是 EasyAuth 后端 agent 的交付物之一，见 `01-easyauth-backend.md` §9。

---

## 4. 角色与权限矩阵

| 角色 | 判定方式 | 可做 |
|---|---|---|
| 当事人（subject） | 登录用户本人 | 在职期间对自己发起 `transfer` 单；查看自己单子的进度 |
| 负责人（assignee） | 单上的 `assignee` 字段 | 指定/改派接收人、preview、execute、查看明细、申请延期 |
| 主管（manager） | `DingTalkUserOrgContext.manager_chain` 上的 active 用户 | 对**自己管辖范围内**的在职员工发起 `reassign` 单 |
| 超管（superuser） | `require_superuser`（Authentik 组交集，每请求判定） | 全部权限；强行 `skip` 未接入 APP；认领超管池中的单 |

**管辖范围判定**：`manager` 对 `subject` 有管辖权 ⟺ `subject` 出现在 `manager` 的 `MANAGED_USERS` 解析结果中
（复用 `grants/managed_users.py:resolve_managed_users`）。跨管辖范围的移交返回 `403 out_of_managed_scope`，
提示改由超管操作。

---

## 5. 身份标识契约（跨系统最容易出错的地方）

### 5.1 唯一人员标识

**所有跨系统 payload 中的人员字段一律使用 `authentik_user_id`（Authentik OIDC `sub`，配置为 `user_uuid` 模式）。**
EasyAuth 内部即 `UserMirror.authentik_user_id`（`accounts/models.py:21`）。

各 APP 的本地映射现状：

| APP | 本地业务外键 | 与 `authentik_user_id` 的关系 | 结论 |
|---|---|---|---|
| EasyTrade | `users.external_user_id`（`external_source="authentik"`） | **就是 sub**，有部分唯一索引（`shared/models.py:109`） | 天然满足，无需改造 |
| EasyProject | `directory_users.dingtalk_user_id`（dtuid） | 同表存 `authentik_user_id`（**可空**，部分唯一索引），首次登录才补绑（`infra/repositories/directory.py:45`、`m07_001_directory_tables.py:51`） | **必须补齐未登录者的映射**，见 §5.2 |

### 5.2 EasyProject 的映射义务（硬要求）

EasyProject 收到 `from_user_id` / `to_user_id`（均为 sub）后必须解析为本地 `dtuid`。

- 解析不到时**必须显式失败**，返回 **HTTP 409**（错误体沿用各自仓库既有约定，见 §10.6），
  由 EasyAuth 把该 action 置为 `failed` 并把响应体原样展示出来。
- **严禁**按姓名/邮箱模糊匹配（违反 EasyProject 不变量 1），**严禁**静默跳过。
- 从未登录过 EasyProject 的员工没有 sub 绑定，这是**真实且常见**的情况：EasyProject 必须提供一条
  从 EasyAuth 目录接口（`GET /api/v1/directory/users`，SDK 已封装）按 sub 反查 dtuid 并回填绑定的路径。
  详见 `05-easyproject-backend.md` §2.1。

### 5.3 资产标识

`asset_id` 是 APP 内部的字符串主键（UUID 或数字转字符串均可），**对 EasyAuth 不透明**。
EasyAuth 只做存储与回传，不解析、不排序、不校验格式。长度上限 128 字节。

---

## 6. 交接单模型（EasyAuth 侧，对下游不可见但决定 payload）

### 6.1 单据类型 `kind`

| kind | 触发 | subject 状态 | 是否动权限 |
|---|---|---|---|
| `offboard` | 目录同步检出离职（自动）；超管手动建单 | `departed` | 权限已在检出时全部撤销 |
| `transfer` | **转岗**（岗位变了，人还在）。既有类型，不改语义 | `active` | **必须动**：按 `TransferPlan` 的差异清单撤旧授权、加新授权 |
| `pre_offboard` | **新增**。在职员工自助发起的提前交接（人要走了，但还没走） | `active` | **一点不动**（D7） |
| `reassign` | **新增**。主管发起的在职员工之间数据移交；交接纠错 | 双方均 `active` | 不动 |

> **`transfer` 与 `pre_offboard` 必须分开，不能合并成一个类型。** 两者对权限的处理正好相反：
> 转岗是"换岗位"，权限必须跟着岗位重算（这正是既有 `TransferPlan`/`OnboardingTemplateRevision`
> 差异计算的用途）；提前交接是"人要走了先把活交出去"，权限一动都不能动，否则员工在剩下的
> 在职期里没法工作。把两者塞进同一个 kind 会让实现方在"要不要调用授权差异逻辑"上二选一，必错一半。

`pre_offboard` → `offboard` 的**升级**是唯一允许的 kind 变更（D7），见 §8.3。
`transfer`（转岗）单**不参与**升级：转岗完成即完成，若此人后续离职，那是一张新的 `offboard` 单。

### 6.2 单据状态机

```
                    ┌──────────────────────────────────────────┐
                    │                                          │
  [建单] ──> pending ──(任一 action 进入非 pending)──> in_progress │
                    │                                          │
                    └──(全部 action ∈ {done, skipped})──> completed
                    │
                    └──(超管取消)──────────────────────> cancelled
```

- `completed` 的判定见 D13，由 `refresh_task_status()` 在**每次** action / 团队项状态变更后重算
  —— 包括 preview 成功（现有代码在 preview 后没调用它，是缺陷）。
- **状态汇总必须是全量纯函数，允许 `in_progress → pending` 回退。** 现有实现只升不降
  （`lifecycle/core.py:119`），升级重置或 capability 恢复后会出现「task 是 `in_progress`、
  但所有 action 都是 `pending`」的自相矛盾。
- `started` 的判定要排除 `pending` / `blocked` / `skipped` 三种初始态，否则一张全部未接入或
  全部声明无数据的单，会在建单当场就被判成 `in_progress`，从未经历 `pending`。
- 存在 `blocked` action 时**永远不会**到达 `completed`。
- **`failed` 不得让单据死锁。** 现有 `skip_action` 在 `attempts` 非零时拒绝、`cancel_task` 在任一
  action `attempts > 0` 时拒绝；而 401/403/413/422 按 §10.6 是不可重试的 `failed` 且 `attempts` 已非零
  —— 这张单会变得**既不能跳过也不能取消**。
  v2 规定：只禁止对**真正在途**的 batch（`executing` / `async_pending`）做跳过与取消；
  `failed` 状态必须允许超管填理由后转 `skipped`，也允许整单 `cancelled`。
- `cancelled` 单可删除；`completed` 单不可删除、不可重开（纠错走 `kind=reassign` 新单，D8）。

### 6.3 负责人状态 `assignee_state`

与 `status` 正交，描述"这张单现在压在谁头上"：

| assignee_state | 含义 | assignee 字段 |
|---|---|---|
| `manager` | 由主管链上某一级主管负责 | 该主管的 `UserMirror` |
| `subject` | 在职员工自助发起，本人负责 | subject 本人 |
| `superuser_pool` | 主管链走完仍无 active 主管，或超时逐级上交到顶 | `NULL` |

`escalation_level`（整数，从 0 起）记录当前 assignee 在主管链上的层级；每次超时上交 +1。

---

## 7. 悬置期的可见性（D4/D5，**已重新选型**）

> **本节在第二轮复核后整体重写。** 原方案是「给主管发限时代管授权，让他在业务系统里看到离职者的数据」，
> 该方案经验证不可实现且带安全漏洞（四条独立致命问题，见 `07-review-log.md` §1.1），已**整体废弃**。

### 7.1 问题回顾

离职检出后，当事人的授权被全部撤销、账号被禁用，他也随之从所有人的 `MANAGED_USERS` 中消失。
于是在交接完成之前，他名下的客户、在途订单、未结应收在**业务系统里对所有人不可见**。
主管要决定"这批东西给谁"，却看不到这批东西是什么。

### 7.2 选定方案：**在交接单里看，不在业务系统里看**

不给主管任何业务系统的临时权限。改为：**交接单本身就是那份清单。**

- `preview` 已经给出每类资产的数量；
- `items` 已经给出逐条明细（名称 + 一行摘要 `hint`），支持分页与搜索；
- 主管在 EasyAuth 门户的交接单页面里直接翻这份明细，逐条决定给谁。

也就是说：**做交接这件事所需的信息，全部由交接单自己提供，不依赖任何跨系统的临时授权。**

### 7.3 这个取舍换掉了什么

| | 得到 | 失去 |
|---|---|---|
| 安全 | 零新增权限面。不发任何临时授权，不碰 `MANAGED_USERS`，不新增 scope | — |
| 改动面 | EasyAuth 无需新增 scope / 委托授权模型；**两个下游的 scope 处理一行都不用改** | — |
| 判断质量 | — | 主管只能看到名称与摘要，**看不到业务上下文**（这个客户最近在谈什么、这单卡在哪） |

**失去的那一项是真实代价**，缓解手段是把 `hint` 用好 —— 契约允许每条明细带一行 ≤120 字符的摘要，
各 APP 应当把最能帮助判断归属的信息放进去（EasyTrade：最近跟进时间 + 在途单数；
EasyProject：所属项目 + 截止日期）。这是各 APP 设计文档里的硬要求，不是可选项。

若日后确认摘要不足以支撑判断，再单独立项做「人员集合 scope 泛化」，届时代管可以作为独立能力回归。
**本期不做，也不为它预留任何字段或分支。**

### 7.4 超时上交（D5 保留，但不再涉及授权）

交接单仍有截止压力，只是压力不再通过"权限到期"表达，而是直接作用在单据上：

| 事件 | 动作 |
|---|---|
| 建单 | `assignee` 按 §8.2 解析，`escalation_deadline = now + 14 天` |
| 代办期内每天 | 钉钉提醒 assignee（`notify` 模块，按业务日去重） |
| 到期前 1 天 | 额外一次"即将上交"提醒 |
| 到期且单未完成 | `escalation_level += 1` → 沿主管链取下一级 active 主管 → 重置 `escalation_deadline` → 通知新旧 assignee 双方 |
| 主管链已到顶 | `assignee_state = superuser_pool`，`assignee = NULL`，改为每日向全体超管推认领通知 |
| 超管顺延（唯一例外口子） | 超管填理由后把 `escalation_deadline` 顺延 14 天，`escalation_level` 不变。**同一层级至多一次**，上交后重置。写审计 `handover_task_deferred`，单据上永久留痕 |

> **为什么给这个口子，以及为什么把它卡这么死**：assignee 正在处理却卡在第 14 天时，
> 硬上交只会让新 assignee 从头看一遍明细，纯粹的返工。但"能续期"本身就是 D5 想消灭的
> 拖延通道，所以限定为：只有超管能按、必填理由、每层级一次、永久留痕。
> **`HANDOVER_ESCALATION_DAYS` 不接受环境变量覆盖** —— 那是绕过 D5 的第二条通道。

`CUSTODY_TTL_DAYS` 这个名字随代管一起废弃，改为 `HANDOVER_ESCALATION_DAYS: Final = 14`。

### 7.5 随之取消的改动（重要）

代管一砍，下面这些**本期全部不做**，各下游文档已同步：

| 原计划 | 状态 | 说明 |
|---|---|---|
| 新增 scope `HANDOVER_CUSTODY` | **取消** | 不再需要 |
| `CustodyGrant` / `CustodyGrantItem` 两张表 | **取消** | — |
| 把 departed 用户并入 `MANAGED_USERS` | **取消** | 这本身就是提权（`07` §1.1 第 1 条） |
| ADR-002 §19 修订（允许非 active 入集） | **取消** | 该条款保持原样，无需修订 |
| EasyTrade 去掉 `row.active` 过滤（原 B3） | **取消** | 没有代管就不会有 departed 用户进入 scope 集合 |
| EasyProject 改为消费快照（原 P1） | **降级为已知偏差** | 它确实违反下游契约，但与本次交接无关，另行立项 |
| EasyTrade / EasyProject 前端改造（`04` / `06`） | **取消** | 离职者不会出现在下游列表里，F1/F2/F3 三个故障都不会发生 |

**唯一保留的 ADR 修订**是 ADR-002 §36（自助申请审批人允许沿主管链向上），它由 D3 驱动，与代管无关。

## 8. 关键流程

### 8.1 离职（kind=offboard）

```
目录同步检出 departed
  └─ apply_directory_status(): UserMirror.status=departed, 撤销全部当前授权（既有逻辑，不改）
  └─ start_offboarding():
       ├─ ensure_handover_task(kind=offboard)  ← 若已存在 open 的 transfer 单，走 §8.3 升级
       ├─ 快照授权 → HandoverGrantItem
       ├─ 按快照涉及的 App 生成 HandoverAppAction
       │    └─ 未声明交接能力的 App → status=blocked（§9）
       ├─ 解析 assignee（§8.2）
       ├─ 移出所有团队 + 排队禁用 Authentik 账号（既有逻辑，不改）
       └─ 首次钉钉通知 assignee
```

### 8.2 assignee 解析算法（D3）

```
resolve_assignee(subject, start_level=0):
    ctx = DingTalkUserOrgContext.get(
        source_slug=subject.dingtalk_source_slug,
        corp_id=subject.dingtalk_corp_id,
        user_id=subject.dingtalk_userid,
    )
    if ctx 不存在 or ctx.stale or not ctx.manager_chain:
        # 目录数据不可用时不能阻断建单（离职单是自动建的）
        记录 audit(assignee_resolution_degraded)
        return (None, superuser_pool, 0, degraded=True)

    for level, entry in enumerate(ctx.manager_chain[start_level:], start=start_level):
        # manager_chain 的元素是映射 {"user_id": ..., "name": ...}，不是裸字符串
        # （directory_sync.py 用 _mapping(item) 逐项落库）
        manager_userid = entry.get("user_id") if isinstance(entry, dict) else None
        if not manager_userid:
            记录 audit(assignee_chain_entry_malformed); continue   # 畸形元素跳过并留痕，不静默
        m = UserMirror.objects.filter(
            dingtalk_source_slug=subject.dingtalk_source_slug,   # 钉钉 userid 只在
            dingtalk_corp_id=subject.dingtalk_corp_id,           # (source, corp) 内唯一
            dingtalk_userid=manager_userid,
        ).first()
        if m and m.status == active and m != subject and not m.is_local_admin:
            return (m, manager, level, degraded=False)
    return (None, superuser_pool, len(ctx.manager_chain), degraded=False)
```

三个容易写错的点：

- `manager_chain` 的元素是**映射**（`{"user_id","name"}`），不是 userid 字符串数组。
- 钉钉 userid **只在 `(source_slug, corp_id)` 内唯一**，跨企业可能重复，查询必须带上这两个维度。
- EasyAuth **没有** `UserMirror.by_dingtalk_userid()` 这样的便捷方法，需要按上面三个字段自行查询；
  若要新增便捷方法，必须带 source/corp 参数，不能只接 userid。

- **不设层数上限**（已决策：逐级向上找到顶）。
- 主管本人同期离职 → 自动跳过，继续向上，天然覆盖"部门整体裁撤"。
- `stale=True` 时**不 fail-closed**：这是与权限查询相反的取舍。权限查询宁可 503 也不能少给或多给权限；
  建单则宁可先落到超管池，也不能丢单。此差异必须写进 ADR-002 修订说明。

### 8.3 在职提前交接与离职日升级（D7）

```
在职期间：
  员工本人在门户发起 kind=pre_offboard 单
    ├─ 快照当前授权 → HandoverGrantItem
    ├─ assignee = 本人（assignee_state=subject）
    └─ execute 时：只发 webhook 搬数据，跳过一切授权改写

离职日：
  start_offboarding() 发现已有 open 的 pre_offboard 单
    │  （若已有的是 open 的 transfer 转岗单, 则该转岗单先按既有逻辑收尾/取消, 再新建 offboard 单）
    ├─ 该单 kind: pre_offboard → offboard（唯一允许的 kind 变更）
    ├─ assignee: 本人 → 按 §8.2 重新解析为主管
    ├─ generation += 1，全部 action 按当前 capability 重新判定初始状态
    │    （逐字段重置清单见 `01` §5.1.2 —— 尤其 data_completed_at 必须清空，
    │     否则新一轮 execute 会走「只补转授权」的续跑分支，这两周的新数据一条都不搬）
    │    上一轮超管的强行 skip **不继承**，未接入的 APP 重新回到 blocked
    ├─ 重新快照授权 → 新一轮 HandoverGrantItem
    └─ 对每个 APP 重新 preview
       └─ 已交接干净的 APP 会返回 count=0，assignee 一键确认即 done
       └─ 这两周新产生的数据会重新出现在清单里
```

`generation` 是幂等边界：同一 `task_id` 的第二轮 execute 携带 `generation=2`，下游必须视为**新的一次执行**，
而不是重复投递。见 §10.5.2。

**若提前交接单在离职前就已 `completed`**：不升级、不重开（`completed` 单不可重开是硬规则，§6.2），
而是**新建一张 `offboard` 单**。"一人同时只有一张 open 单"的约束只管 open 单，已完成的不挡新建。
新单会重新盘点全部 APP，把提前交接之后新产生的数据揪出来；已经交接干净的 APP 自然返回 `count=0`。
两张单在审计上首尾相接，历史完整。

因此升级路径只在**存在 open 的 `pre_offboard` 单**时触发，这是唯一情形。

### 8.4 二次转交（D8/D9）

```
主管在门户对在职下属发起 kind=reassign 单
  ├─ 校验：subject 与 to_user 均 active，且 subject ∈ 发起人的 MANAGED_USERS
  │        否则 403 out_of_managed_scope
  ├─ 必填 reason（≥10 字符）
  ├─ assignee = 发起人（assignee_state=manager, escalation_level=0）
  ├─ 不动任何权限（D7 同理）
  ├─ 走与 offboard 相同的 preview/execute 流程
  └─ execute 成功后通知三方：转出方、接收方、发起人的上一级主管
```

`reassign` 单不受"一人一张 open 单"约束的限制方式：唯一约束改为

```python
UniqueConstraint(
    fields=["subject_user"],
    condition=Q(status__in=OPEN) & Q(kind__in=("offboard", "transfer", "pre_offboard")),
)
```

即 `reassign` 可与生命周期单并存，也允许同一 subject 有多张 open 的 reassign 单
（不同 APP、不同批次的重分配是正常操作）。

> **`pre_offboard` 必须在约束里。** 少了它，同一个人可以建出任意多张 open 的提前交接单，
> 而 §8.3 的升级逻辑写的是「发现**已有** open 的 `pre_offboard` 单就升级它」——
> 有两张时根本无从选择，升级路径直接失效。
> 权威定义见 `01` §2.1 的 `lifecycle_task_one_open_lifecycle_per_subject`。

---

## 9. APP 交接能力声明（D6）

### 9.1 声明位置

APP 在 descriptor（`/.well-known/easyauth-app.json`）中声明。

> **形状必须迁就既有实现，不能另造。** EasyTrade 的 descriptor 不是手写的，而是经
> `backend/app/domain/authz/easyauth_manifest_export.py` 的 `_lifecycle()` 产出，
> 该校验器**只接受也只返回** `{handover_url, onboard_url, capabilities}` 三个键
> （`:109,117-121`）。早期设计里的嵌套 `lifecycle.handover` 对象会被直接拒绝或剥掉。
>
> 因此 v2 **扩展既有结构**，不新增嵌套层：

```json
{
  "lifecycle": {
    "handover_url": "https://app.example.com/api/v1/easyauth/lifecycle/handover",
    "onboard_url": null,
    "capabilities": ["handover.v2"],
    "handover_asset_types": [
      { "type": "customer",     "label": "名下客户",   "detail_supported": true, "releasable": true },
      { "type": "inquiry_open", "label": "进行中询盘", "detail_supported": true, "releasable": false }
    ]
  }
}
```

- `capabilities` 里出现 `"handover.v2"` 即表示已实现 v2 三事件（preview / items / execute）。
  这是**唯一**的能力判定依据，不再另设 `capability` 字段。
- `handover_asset_types` 是新增键。`_lifecycle()` 的 `_require_fields` 与返回字典**必须同步扩展**，
  否则该键会被静默剥掉 —— 这是 EasyTrade / EasyProject 各自设计文档里的明确任务。
- 声明「本 APP 无用户级数据」的方式：`capabilities` 含 `"handover.none"`，且
  `handover_asset_types` 为空数组。运营在控制台做此声明时必须留下人和时间（§9.1 约束）。

三态判定：

| descriptor 情况 | 含义 | action 初始状态 |
|---|---|---|
| `capabilities` 含 `handover.v2` 且 `handover_url` 非空 | 已接入 | `pending` |
| `capabilities` 含 `handover.none` | 运营显式声明无用户级数据 | `skipped`（标注声明人与时间） |
| 其余（含拉取失败） | 未声明 | **`blocked`** |

`releasable=false` 表示该类资产**不允许无接收人释放**（如 EasyTrade `Inquiry.owner_user_id` 非空约束）。
EasyAuth 在 execute 前校验：对 `releasable=false` 的类型指定 `to_user_id=null` 时，直接返回
`422 asset_type_not_releasable`，**不发 webhook**。这修掉了现状里"静默保持原归属"的兜底分支。

### 9.1.1 capability 变化后的恢复（blocked 不是死路）

APP 后来接入了交接，历史上被判 `blocked` 的单必须能自动恢复，否则只剩"永久阻塞"或"强行跳过"两条路，
而两条都是坏结局。

`sync_handover_capability()` 成功把某 APP 从 `undeclared` 改为 `declared` 时，必须触发一次
**reconcile**：

```
对该 App 下所有 status=blocked 且所属 task 仍 open 的 action:
    加行锁 → 校验 App.handover_capability 仍为 declared 且 handover_url 非空
           → action.status = pending
           → action.blocked_reason = ""
           → action.generation = task.generation   # 与当前轮次对齐
           → 审计 handover_action_unblocked(app_key, task_id)
           → refresh_task_status(task)             # 可能从 in_progress 退回 pending
    随后给这些单的 assignee 各发一次钉钉通知：「{APP} 已接入交接，有新的待处理项」
```

反方向（`declared` → `undeclared`，通常是 descriptor 拉取失败）**不得**把已有的 `pending`/`previewed`
action 改回 `blocked` —— 那会让正在处理的人莫名其妙。只在**建单时**判定初始状态；
运行中的拉取失败只写告警，不改既有 action。

### 9.2 blocked 的表现

- 交接单详情里该 APP 一行显示红色「未接入交接」，附「该 APP 尚未实现数据交接，无法确认是否有遗留数据」。
- 整单永远不会 `completed`（D13）。
- 控制台顶部常驻告警：「N 个 APP 未接入数据交接，M 张交接单被阻塞」。
- 超管可 `POST .../actions/{app_key}/skip`，**必填 reason**，写审计 `handover_action_skipped`，
  单据上永久显示「已由 {超管} 于 {时间} 强行跳过：{理由}」。

---

## 10. Webhook 契约 v2（冻结）

### 10.1 通用规范（沿用现有，不变）

- 传输：HTTPS POST，`Content-Type: application/json; charset=utf-8`
- 签名：`X-EasyAuth-Signature` = HMAC-SHA256(secret, `timestamp + "." + raw_body`)，
  `X-EasyAuth-Timestamp`，重放窗口 300 秒（`sdk/python/src/easyauth_app_sdk/webhook.py:68`）

  > **已知弱点（本次不改，但必须知道）**：签名串**不覆盖** `X-EasyAuth-Event` 与
  > `X-EasyAuth-Delivery`，而这两个头分别决定路由与去重。理论上在 300 秒窗口内可以替换它们。
  >
  > 实际可利用面很窄：body 里带 `mode` 字段，路由与载荷不一致会被下游校验拒绝；
  > 幂等键是 `(task_id, generation, batch_id)` 而非 delivery id，替换 delivery 也换不出重复执行。
  >
  > **不在本次改的理由**：EasyProject 的 `contracts/test-vectors/webhook-hmac.json` 已把
  > `signingString` 冻结为 `timestamp + "." + raw_body`（标注 `W0-ADJUDICATED`），改签名串要额外一次
  > 契约变更并同步全部下游与向量，成本远高于收益。
  >
  > **必须做的补偿**：下游收到请求后**必须校验 `X-EasyAuth-Event` 与 body 的 `mode` 一致**
  > （`preview`/`execute` 对应各自 mode，`items` 无 mode 字段），不一致返回 422。
  > 这条是强制的，写进各 APP 的验收用例。
  >
  > 把 event/delivery 纳入签名列为后续独立改造项，需单独立项与 CCR。
- 去重：`X-EasyAuth-Delivery`
- 事件名：`X-EasyAuth-Event`
- 请求体上限：**从 64 KiB 提升到 256 KiB**（`assignments.overrides` 可能较长），
  SDK `DEFAULT_MAX_BODY_BYTES` 同步调整
- 验签失败 → **401 或 403**（各下游沿用自己仓库既有约定：EasyTrade 403、EasyProject 401，
  后者的反例向量已冻结在 `contracts/test-vectors/webhook-hmac.json`）；未知事件 → 422；
  业务异常 → 500（SDK 内核已实现）。EasyAuth 侧两者处置完全相同（`failed` 且不可重试，见 §10.6），
  因此**不要求统一**。

### 10.2 事件一览

| 事件 | 方向 | 幂等 | 说明 |
|---|---|---|---|
| `webhook.test` | EasyAuth → APP | — | 已有，不变 |
| `lifecycle.handover.preview` | EasyAuth → APP | 只读 | **payload 变更** |
| `lifecycle.handover.items` | EasyAuth → APP | 只读 | **新增**，明细分页 |
| `lifecycle.handover.execute` | EasyAuth → APP | `(task_id, generation, batch_id)` | **payload 重大变更** |

### 10.3 `lifecycle.handover.preview`

请求：

```json
{
  "task_id": "137:easytrade",
  "generation": 1,
  "kind": "offboard",
  "from_user_id": "3f1a5c88-0e21-4b7a-9c3d-77e5a1f0b912",
  "mode": "preview"
}
```

响应 200：

```json
{
  "snapshot_token": "et-2026-08-10T10:22:41.331Z-9f2c",
  "assets": [
    { "type": "customer",        "label": "名下客户",     "count": 187 },
    { "type": "order_in_transit","label": "在途订单",     "count": 23  },
    { "type": "inquiry_open",    "label": "进行中询盘",   "count": 41  },
    { "type": "task_open",       "label": "未完成任务",   "count": 9   }
  ]
}
```

- `snapshot_token` 必填，见 §10.5.1。

- `type` 必须是 descriptor 中声明过的 `asset_types`，否则 EasyAuth 返回 `422 undeclared_asset_type` 并置 action 为 `failed`。
- `count=0` 的类型也必须返回，不得省略（省略与"不支持"无法区分）。
- 响应不含明细，明细走 §10.4。

### 10.4 `lifecycle.handover.items`（新增）

请求：

```json
{
  "task_id": "137:easytrade",
  "generation": 1,
  "snapshot_token": "et-2026-08-10T10:22:41.331Z-9f2c",
  "from_user_id": "3f1a5c88-0e21-4b7a-9c3d-77e5a1f0b912",
  "asset_type": "customer",
  "page": 1,
  "page_size": 50,
  "q": "华东"
}
```

- `page` 从 1 起；`page_size` 取值 1–200，EasyAuth 默认传 50
- `q` 可为空串，APP 自行决定在哪些字段上模糊匹配；不支持搜索的 APP 忽略该字段即可

响应 200：

```json
{
  "items": [
    { "id": "9b2c…", "label": "上海某某国际贸易有限公司", "hint": "最近跟进 2026-07-30 · 在途 3 单" },
    { "id": "4d81…", "label": "宁波某某进出口",           "hint": "最近跟进 2026-06-11" }
  ],
  "page": 1,
  "page_size": 50,
  "total": 2,
  "unfiltered_total": 187
}
```

（示例带了 `q="华东"`，故 `total` 是过滤后的 2；`unfiltered_total` 是可选字段。）

- `id`：§5.3 定义的 `asset_id`
- `label`：给人看的名字，≤120 字符
- `hint`：辅助判断的一行摘要，可空，≤120 字符
- `total`：**按 `q` 过滤之后**的总数。仅当 `q` 为空串时，`total` 必须等于同一 `snapshot_token` 下
  preview 返回的 `count`；`q` 非空时两者本就不应相等。若 APP 想同时给出未过滤总数，可另加
  可选字段 `unfiltered_total`（EasyAuth 只用它做一致性提示，不参与任何判定）

仅当 descriptor 里该类型 `detail_supported=true` 时 EasyAuth 才会调用此事件。

### 10.5 `lifecycle.handover.execute`

请求：

```json
{
  "task_id": "137:easytrade",
  "generation": 1,
  "batch_id": 1,
  "snapshot_token": "et-2026-08-10T10:22:41.331Z-9f2c",
  "kind": "offboard",
  "from_user_id": "3f1a5c88-0e21-4b7a-9c3d-77e5a1f0b912",
  "mode": "execute",
  "assignments": [
    {
      "asset_type": "customer",
      "default_action": "transfer",
      "default_to_user_id": "8c44…",
      "overrides": [
        { "id": "9b2c…", "action": "transfer", "to_user_id": "d017…" },
        { "id": "4d81…", "action": "release" },
        { "id": "7a10…", "action": "skip" }
      ]
    },
    {
      "asset_type": "order_in_transit",
      "default_action": "skip",
      "overrides": [
        { "id": "o-2291", "action": "transfer", "to_user_id": "8c44…" }
      ]
    },
    {
      "asset_type": "inquiry_open",
      "default_action": "skip",
      "overrides": []
    }
  ]
}
```

语义（**唯一权威定义**）：

1. 每个 `asset_type` 在 `assignments` 中**最多出现一次**；重复出现由 EasyAuth 在发送前拒绝。
2. `default_action` 是该类型**未被 override 覆盖的全部条目**的处置方式，三选一：

   | `default_action` | 含义 | 必填字段 | 前置条件 |
   |---|---|---|---|
   | `transfer` | 转给指定接收人 | `default_to_user_id`（非 null） | 接收人 active 且不是当事人 |
   | `release` | 释放为无主 | — | 该类型 `releasable=true` |
   | `skip` | **原样不动** | — | 无 |

3. `overrides` 是逐条例外，每条同样带 `action`，取值与语义完全一致（`transfer` 需 `to_user_id`，
   `release` 需 `releasable=true`，`skip` 表示这一条不动）。同一 `id` 只能出现一次。
4. **未出现在 `assignments` 中的 `asset_type` 等价于 `default_action="skip"`**，一条都不动。

> **为什么必须有 `skip` 而不能用 `to_user_id=null` 兼表两义**：
> 「不动」和「释放为无主」是两件完全不同的事，而 `releasable=false` 的类型**不允许**无主。
> 若用 `null` 同时表达两者，那么所有 `releasable=false` 的类型（EasyTrade 的在途订单、进行中询盘、
> 未完成任务，以及 EasyProject 的全部 9 类）都将**无法部分交接** —— 想转其中 3 条就必须整批转，
> D10 的「逐条反选改派」对它们彻底失效。三值 `action` 把这两个语义彻底分开。
>
> 于是「只转一部分」的标准写法是：`default_action="skip"` + `overrides` 列出要转的条目
> （见上例的 `order_in_transit`）。这条路径对 `releasable` 取值**没有任何依赖**，任何类型都能用。

5. EasyAuth 在发出请求前完成全部校验（见 `01-easyauth-backend.md` §5.4），因此下游收到的
   `assignments` 必然满足上述前置条件。下游仍应做防御性校验：`action="release"` 落在
   `releasable=false` 的类型上时返回 **HTTP 422**，不得静默改成保持原状。

响应 200（同步完成）：

```json
{
  "summary": {
    "customer":         { "transferred": 185, "released": 1, "skipped": 1, "merged": 0, "failed": 0 },
    "order_in_transit": { "transferred": 1,   "released": 0, "skipped": 22, "merged": 0, "failed": 0 },
    "inquiry_open":     { "transferred": 0,   "released": 0,  "skipped": 41, "merged": 0, "failed": 0 }
  }
}
```

**summary 的字段是冻结的五元，任何 APP 不得自行增删**：

| 字段 | 含义 |
|---|---|
| `transferred` | 归属被改写为某个接收人的条目数 |
| `released` | 被置为无主的条目数（仅 `releasable=true` 的类型可能非零） |
| `skipped` | 按 `action="skip"` 明确不动的条目数 |
| `merged` | **接收人已经在里面，因此删除来源方关系行而非改写**。复合主键的成员/协作/参与关系会出现这种情况（EasyProject 多类资产、EasyTrade 无）。它是一种成功结果，但**必须与 `transferred` 分开报**，否则"转了 5 条"和"其中 3 条其实是合并掉的"就分不出来 |
| `failed` | 该类型内单条失败但整体未回滚的条目数。**正常情况下恒为 0** —— execute 要求整事务成败一致（§10.5）。非 0 意味着 APP 实现了部分成功语义，EasyAuth 会把该 action 判为 `failed` 并要求重试 |

**守恒公式**（EasyAuth 会校验，不满足则把 action 判为 `failed` 并展示差额）：

```
transferred + released + skipped + merged + failed == 该类型在本轮 assignments 覆盖到的条目总数
```

**口径固定为全量**：右边是该 `asset_type` 在本次快照下的**全部**条目数（等于 preview 的 `count`），
与 `default_action` 取什么值无关。被 `skip` 的条目计入 `skipped`。

这样公式恒等、无分支，下游实现和 EasyAuth 校验都不会有第二种解释。
上例中 23 张在途订单里 1 张被 override 转移、22 张按默认 skip，故 `transferred:1, skipped:22`。

响应 202（异步，沿用现有机制）：返回 `Location` 头指向状态查询 URL，EasyAuth 轮询
（`handover.py:261 poll_async_action`，逻辑不变）。

### 10.5.1 快照令牌与并发（execute 的安全前提）

`generation` 只是"第几轮盘点"，**它不是数据快照**。preview / items / execute 是三次独立的实时查询，
中间数据会变。不加约束就会出现两类事故：

- preview 时 187 个客户，execute 时变成 191 个 —— **4 个没被任何人看过的客户被一起搬走了**。
- override 里的某个 `asset_id` 在这期间已经不属于当事人（被别人认领了）—— 却仍被改写归属。

因此契约增加 `snapshot_token`：

1. `preview` **响应**必须返回 `snapshot_token`（APP 自定义的不透明字符串，≤128 字节；
   可以是最大更新时间戳、内容 hash 或版本号，EasyAuth 不解析）。
2. `items` 与 `execute` **请求**回带同一个 `snapshot_token`。
3. APP 在 `execute` 时必须校验：**当前数据状态是否仍与该 token 一致**。
   不一致则返回 **HTTP 409**，EasyAuth 把 action 打回 `previewed` 之前并提示"清单已变化，请重新预演"。
4. 逐条校验同样是硬要求：每个被改写的条目必须**当前仍属于 `from_user_id`** 且**仍属于该 `asset_type`**；
   否则整体 409，**不允许**跳过该条继续处理其余条目（那是静默兜底）。

### 10.5.1.1 执行顺序：**数据先，授权后**（修既有缺陷）

现有代码在调用数据 webhook **之前**就执行了授权转移
（`lifecycle/handover.py:182` 的 `transfer_selected_grants()` 早于 `:190` 的 `signed_hook_post()`）。
webhook 失败时 action 标 `failed`，**但权限已经转走了** —— 状态机根本表达不了"数据没搬、权限已转"，
重试也恢复不了。

v2 固定顺序，并用子状态把中间态显式化：

```
executing
  └─ 1. 发数据 webhook（execute）
        失败 → failed（权限一动未动，重试安全）
        202  → async_pending → 轮询
        200  ↓
  └─ 2. data_completed        ← 数据已落地，权限尚未转
  └─ 3. 幂等转授 grant_receiver 的权限（仅 kind=offboard 且 grant_receiver 非空）
        失败 → failed，但**保留 data_completed 子状态**，重试只重做第 3 步
  └─ 4. done
```

- 第 3 步必须**幂等**：重试时若目标授权已存在则跳过，不重复递增 version。
- `data_completed` 是持久化字段，不是内存态；重试路径靠它决定从哪一步续跑。
- `kind` 非 `offboard` 时第 3 步直接跳过（D7/D9：不动权限）。

### 10.5.2 资产互斥（同一批数据不能被两张单同时搬）

`reassign` 单可以与离职单并存、同一 subject 也可以有多张 open 的 `reassign`（§8.4）。
若两张单同时对同一批数据执行，先到者全搬走，后到者返回一堆 0 —— 看起来"成功"，实际什么都没发生。

约束：**EasyAuth 侧对 `(subject_user, app)` 加执行互斥**，同一当事人在同一 APP 上
任一时刻只允许一个 execute 在途（含 `async_pending`）。冲突时第二个请求立即返回
`409 handover_execution_in_flight`，不排队、不重试。

> **实现必须是持久化租约行，不能是短事务的 `select_for_update`。**
> webhook 调用发生在事务之外（`AGENTS.md`：网络副作用出事务），且 `async_pending` 可能持续很久，
> 跨 web worker 与 Celery 的短事务行锁根本盖不住这段时间。
>
> 具体：建一张 `HandoverExecutionLease`，`(subject_user, app)` 上加**条件唯一约束**
> （`released_at IS NULL`），行内记 `action_id` / `generation` / `batch_seq` / `acquired_at` /
> `owner`（worker 标识）/ `fence`（单调递增，防旧持有者回来写脏）。
>
> **超时不得直接解锁。** 租约过期只代表"可能卡住了"，必须先向下游确认该 `(task_id, generation,
> batch_id)` 的真实状态（下游幂等记录是权威），确认终结后才 fence 并释放。
> 直接强解会造成两个执行者同时改同一批数据。

这把互斥放在 EasyAuth 而不是各 APP，是因为只有 EasyAuth 知道全部在途单据。
APP 侧仍应保留自己的行锁作为第二道防线。

**幂等**：幂等键为 `(task_id, generation, batch_id)`。

- `batch_id` 是 EasyAuth 生成的单调递增整数，**同一 generation 内可以有多批**。
  它在 EasyAuth 内部的字段名是 `batch_seq`（`HandoverExecutionAttempt.batch_seq`、
  `HandoverExecutionLease.batch_seq`、`HandoverAppAction.batch_seq` 分配器）——
  **`batch_seq` 与线上契约字段 `batch_id` 是同一个值，不是两个编号**，
  发 payload 时原样填入，不做任何映射或重编号。作用域是 `(action, generation)`，从 1 起
  —— 这是 413 时"分批执行"能成立的前提（§10.6）。不引入它，第二批会被当成重放而静默丢弃。
- **每一批必须重新 preview 取新的 `snapshot_token`**：第一批已经改写了数据，沿用旧 token 的第二批
  必然校验失败。因此分批的正确流程是「preview → 执行第 1 批 → 重新 preview → 执行第 2 批 …」，
  每批携带自己那一轮的 token。**同一 token 只能用于一批。**
- 同一三元组重复投递：必须安全，且返回**与首次完全相同**的 `summary`。
- 同一三元组但 payload 不同：返回 **HTTP 409**（投递冲突），不得按新 payload 执行。
  APP 应存 canonical payload 的 SHA-256 用于比对。
- 迟到的旧 `generation`：**必须拒绝**（409），不得执行。APP 需记录该 `task_id` 见过的最大
  `generation`，小于它的一律拒绝。这防止升级后旧一轮的执行请求姗姗来迟把数据搬错。

### 10.6 错误响应（APP → EasyAuth）

**HTTP 状态码是唯一规范部分；响应体是参考信息。**

各下游应用有各自冻结的错误体约定，且互不兼容 —— EasyTrade 用
`{"error":{"code","message"}}`（小写下划线码），EasyProject 用
`{"detail":{"code","message","traceId"}}`（全大写码，`contracts/openapi-baseline.json` 的 `ErrorBody`）。
**EasyAuth 不得要求任何一方改自己的错误体**，那既是无谓的破坏性变更，也会逼出兼容层。

因此 EasyAuth 侧的规则是：

1. 按 **HTTP 状态码**决定 action 状态与是否可重试（下表）。
2. 响应体**原样截断存入** `action.last_error`（上限 2000 字符），在界面上直接展示给人看。
   不解析、不映射、不依赖任何字段名。
3. 响应体不是 JSON 或为空 **不构成额外错误**，按状态码处理即可。

| HTTP | 语义 | action 状态 | 可重试 | 界面提示 |
|---|---|---|---|---|
| 200 | 成功 | `done` | — | — |
| 202 | 异步受理 | `async_pending` | — | 轮询中 |
| 400 | 请求不合法（如时间戳超窗） | `failed` | 是 | 请求被应用拒绝 |
| 401 / 403 | 验签失败 | `failed` | 否 | 签名校验失败，请检查该应用的 webhook 密钥 |
| 409 | 人员无法识别 / 快照已失效 / 投递冲突 / 迟到的旧 generation | 见右 | 否 | 快照失效 → action 退回 `pending` 并提示「清单已变化，请重新预演」；其余 → `failed` |
| 413 | 请求体过大 | `failed` | 否 | 单独指定的条目过多，请分批执行 |
| 422 | 载荷不被支持（未声明的资产类型、不支持的事件） | `failed` | 否 | 应用声明与实现不一致 |
| 5xx | 应用内部错误 | `failed` | 是 | 可重试 |

> 各 APP 在自己的设计文档里按本表对齐**状态码**即可，错误码字符串沿用本仓库既有约定，无需统一。

---

## 11. 数据范围标准（D11）

每个 APP 在接入时**必须**在自己的设计文档里产出一张三列清单，逐字段判定：

| 分类 | 判定标准 | 处理 |
|---|---|---|
| **活的责任** | 该字段决定"现在谁该干这件事"或"谁能看到这条数据"，且对象尚未终结 | **转移**，纳入某个 `asset_type` |
| **历史事实** | 该字段记录"当时是谁做的" | **不动**。包括 `created_by`、评论作者、操作日志 actor、`confirmed_by`、`cancelled_by` 等一切过去式署名 |
| **个人配置** | 只对本人有意义（仪表盘布局、通知偏好） | **不动**，随账号停用自然失效 |

### 11.1 D11 的两条显式例外（已裁定）

D11 是冻结决策，**下游文档不得单方面豁免**。经复核确认，只有以下两条属于正式例外，
其余一律照 D11 执行：

| 例外 | 为什么 | 本期怎么办 | 补做条件 |
|---|---|---|---|
| **在途的钉钉审批实例，其当前审批人是离职者** | EasyAuth 不存实例的当前审批人（`workflows/models.py` 的 `ApprovalInstance` 只有 `originator_user`），钉钉客户端也只有 `create_process_instance` / `get_process_instance`，**没有转办接口**。能否程序化转办取决于钉钉开放平台是否提供该 API，本仓库无从确认 | 做**可行的那半**：离职时把 `ApprovalRule.approver_userids` 里的离职者替换为新主管，保证**新发起**的审批不再落到他头上。**在途实例需人工到钉钉里转办**，交接单上显式列出这些实例并给出钉钉跳转链接 | 确认钉钉转办 API 可用后，封装该调用并在 `ApprovalInstance` 上跟踪当前审批人 |
| **EasyProject `WorkRecordRow.created_by_dingtalk_user_id`** | 字段名是历史式的，实际承担当前归属与鉴权语义。转移它等于同时改写"谁写的"与"谁负责"两个语义 | **不转移**。记入 EasyProject 风险清单 | 先做独立领域改造：新增 `owner_dingtalk_user_id` 列 + 迁移 + 鉴权切换，再作为新 `asset_type` 加入 |

> **EasyAuth 自身的权限申请审批不在例外之列。** `AccessRequestApprover` 是本地表、`approver`
> 直接外键到 `UserMirror`，离职时**必须**把待审批申请的审批人改派给新主管（见 `01` §4.5）。
> 这是最常见的卡死场景：员工申请权限，单子挂在已离职的主管头上。

边界判例（已裁定，各 APP 直接照用）：

- 订阅/关注关系 → **归入个人配置，不转移**。接收人若需要，自行关注。
- 业绩目标（`PerformanceTarget`）→ **不转移**。业绩归属是历史事实，转移会造成考核失真。
- 草稿（未提交的报价单、文档）→ **不单独转移**，随其父对象（客户/订单）的归属自然继承访问权。
- 待审批单据中"当前审批人是离职者" → **必须转移**，属活的责任，单列一个 `asset_type`。

---

## 12. 审计事件清单（冻结）

全部写入 `AuditLog`（`audit/models.py:46`，append-only）。

| 事件 | 时机 | 关键字段 |
|---|---|---|
| `handover_task_created` | 建单 | kind, subject, created_by, reason |
| `handover_task_upgraded` | transfer → offboard 升级 | task, old_kind, generation |
| `handover_assignee_assigned` | assignee 解析/变更 | task, assignee, assignee_state, escalation_level |
| `handover_assignee_resolution_degraded` | 主管链缺失或 stale，落超管池 | task, reason |
| `handover_task_escalated` | 到期上交 | task, from_assignee, to_assignee, escalation_level |
| `handover_task_deferred` | 超管顺延截止时间（§7.4） | task, actor, reason, old_deadline, new_deadline, escalation_level |
| `handover_action_previewed` | preview 成功 | task, app_key, generation, assets |
| `handover_action_executed` | execute 成功 | task, app_key, generation, assignments 摘要, summary |
| `handover_action_failed` | execute 失败 | task, app_key, error code/message |
| `handover_action_blocked` | 建单时判定未接入 | task, app_key |
| `handover_action_skipped` | 超管强行跳过 | task, app_key, actor, reason |
| `handover_task_completed` | 全部 action 终结 | task |
| `handover_reassign_created` | 在职移交建单 | subject, initiator, reason |
| `handover_approver_reassigned` | 待审批申请的审批人改派 | task, access_request, from_approver, to_approver |
| `handover_approval_rule_approver_replaced` | 审批规则里的离职者被替换 | task, approval_rule, from_userid, to_userid |

---

## 13. 通知清单（钉钉工作通知，复用 `notify`）

| 通知 | 收件人 | 触发 | 频率 |
|---|---|---|---|
| 新交接单待处理 | assignee | 建单 / 升级 / 上交 | 即时 1 次 |
| 交接单每日提醒 | assignee | 单未完成 | 每日 1 次（按业务日去重） |
| 即将上交 | assignee | 上交前 1 天 | 1 次 |
| 已上交 | 原 assignee + 新 assignee | 超时上交 | 即时 |
| 超管池待认领 | 全体超管 | 单进入 `superuser_pool` 后仍未完成 | 每日 1 次 |
| 数据已移交给你 | 接收人 | execute 成功 | 即时（D12：仅通知，无需同意） |
| 你的数据已被移交 | 转出方（在职时） | `reassign` execute 成功 | 即时 |
| 下属数据发生移交 | 发起人的上一级主管 | `reassign` execute 成功 | 即时 |
| APP 未接入告警 | 全体超管 | 存在 `blocked` action | 每周 1 次 |

---

## 14. 并行开工边界

> **本节以 `README.md`「并行边界」为准，此处只做摘要。** 早期版本写的「A1/A3/A5 三个后端可完全并行」
> 与「A4/A6 立即开工」都已作废：前者忽略了下游要用 A1 产出的 SDK vNext 与契约样本，
> 后者对应的两份前端文档本期已取消。

| Agent | 仓库 | 文档 | 可开工条件 |
|---|---|---|---|
| A1 | EasyAuth | `01-easyauth-backend.md` | 立即。**第 0 步先独做 SDK vNext**（三事件内核 + `handover_payloads` 类型 + 打包进包内的契约样本），打版本号并记 SHA |
| A2 | EasyAuth | `02-easyauth-frontend.md` | A1 提交 `01` §6 的 HTTP API 契约章节后 |
| A3 | EasyTrade | `03-easytrade-backend.md` | SDK vNext 发布后 |
| ~~A4~~ | EasyTrade | ~~`04-easytrade-frontend.md`~~ | **本期取消**（代管废弃，F1/F2/F3 不会发生） |
| A5 | EasyProject | `05-easyproject-backend.md` | **阻塞**：AG-00 的所有权裁定 + system-actor 语义裁定 + CCR APPROVED。裁定前只能做 `05` §2.1 身份映射与 §2.3 `hint` |
| ~~A6~~ | EasyProject | ~~`06-easyproject-frontend.md`~~ | **本期取消**（同上） |

契约样本**随 SDK 分发**（`easyauth_app_sdk.contract_samples` 包内资源），下游用 `importlib.resources`
读取比对；**样本缺失必须让测试失败，不允许 skip 通过**。不得依赖兄弟目录路径 —— 下游 CI 独立检出，
那条路径必然不存在。

联调门禁：EasyAuth 的 `webhook.test` 事件对每个 APP 返回 200，且各 APP 的 descriptor 能被
`GET /.well-known/easyauth-app.json` 正确拉取，并解析出 `lifecycle.capabilities` 含 `"handover.v2"`
与非空的 `lifecycle.handover_asset_types`（§9.1 的形状，**不是**嵌套的 `lifecycle.handover` 对象）。

---

## 15. 验收标准（端到端，跨仓库）

1. 造一个测试员工，在 EasyTrade 与 EasyProject 各留下若干活的责任数据。
2. 在钉钉侧标记其离职 → 目录同步后：其权限被全部撤销、账号被禁用、交接单自动建出、assignee 为其直属主管、
   主管收到钉钉通知。
3. 主管登录 EasyTrade → **看不到**该离职者名下的客户（这是预期行为：不发任何临时授权）。
4. 主管在门户打开交接单 → 看到 EasyTrade 与 EasyProject 两行，各自列出资产分类与数量；
   展开明细能看到逐条名称与 `hint` 摘要（验证 §7.2 的可见性方案生效）。
5. 主管对「名下客户」展开明细，把其中 2 个改派给另一人，其余整批给接收人 → execute → 两个接收人在 EasyTrade 里
   各自看到对应客户。
6. 把某个 APP 的 descriptor 的 `lifecycle.capabilities` 去掉 `"handover.v2"` → 重新建单 → 该行显示「未接入交接」，
   整单不能完成；超管填理由跳过后整单完成。
7. 把 `escalation_deadline` 人为改到过去 → 跑一次上交任务 → 单子上交到上一级主管、`escalation_level` +1、双方均收到通知。
8. 用另一个在职员工发起 `kind=reassign`，把步骤 5 中接收人的部分客户再转给第三人 → 成功，且三方均收到通知。
9. 全流程审计事件齐全（§12 全部出现），无一条静默成功、无一条 mock 数据。
