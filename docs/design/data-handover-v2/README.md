# 数据交接 v2 · 设计文档集

本目录是本次「离职/转岗/在职数据交接」改造的**全部**设计文档，覆盖 EasyAuth、EasyTrade、
EasyProject 三个仓库。文档统一放在这里，各仓库不再分散存放。

> **当前状态：三轮对抗式复核完成，A5 的开工阻塞已解除。**
>
> - **代管授权整体砍掉**（第一处结构性问题）。悬置期的可见性改由交接单自身的资产明细承担（契约 §7）。
>   随之取消：`04`/`06` 两份下游前端文档、EasyTrade 的 B3、EasyProject 的 P1、ADR-002 §19 修订。
> - **审批责任纳入本期**（`WorkRecord` 写成 D11 显式例外，见 `00` §11.1、`01` §4.5）。
> - **EasyProject 完整做**。两份 AG-00 裁定已起草于 [`08`](08-easyproject-ag00-rulings.md)、
>   CCR 正文已起草于 [`09`](09-easyproject-ccr.md)；A5 的开工前置从"等两份不存在的裁定"
>   变成"等三样可机械核对的凭据"（见下方「A5 的三道门禁」）。
>
> 三轮复核累计约 200 条发现，全部逐条对照代码验证后落文档。
> **开工前必读 [`07-review-log.md`](07-review-log.md)** —— 那里列了第三轮找出的
> 14 条「照做必错」的问题，都是实现时最容易踩的。

## 阅读顺序

| # | 文档 | 负责 agent | 仓库 |
|---|---|---|---|
| 00 | [总体设计与跨系统契约](00-overview-and-contract.md) | **全体必读** | — |
| 01 | [EasyAuth 后端改造设计](01-easyauth-backend.md) | A1 | EasyAuth |
| 02 | [EasyAuth 前端改造设计](02-easyauth-frontend.md) | A2 | EasyAuth |
| 03 | [EasyTrade 后端改造设计](03-easytrade-backend.md) | A3 | EasyTrade |
| 04 | [EasyTrade 前端改造设计](04-easytrade-frontend.md) | ~~A4~~ **本期取消** | EasyTrade |
| 05 | [EasyProject 后端接入设计](05-easyproject-backend.md) | A5 | EasyProject |
| 06 | [EasyProject 前端改造设计](06-easyproject-frontend.md) | ~~A6~~ **本期取消** | EasyProject |
| 07 | [复核记录与未决事项](07-review-log.md) | **全体必读** | — |
| 08 | [EasyProject AG-00 两份裁定](08-easyproject-ag00-rulings.md) | AG-00 审批 → A5 依据 | EasyProject |
| 09 | [EasyProject CCR 正文](09-easyproject-ccr.md) | AG-00 提交 | EasyProject |

**`00` 是唯一基准。** 里面的字段名、事件名、状态值、HTTP 状态码语义对所有仓库冻结；
任何一方需要变更，先改 `00`，再同步全部下游文档，不得在自己仓库内单方面调整。

## 并行边界（复核后修正，原来的"三个后端立即并行"不成立）

A3 / A5 的实现要用到 v2 SDK（新的 `items` 回调、`handover_payloads` TypedDict、256 KiB 上限）
与契约样本，这些都是 A1 的产出。所以真实次序是**一个短的串行头 + 大段并行**：

**第 0 步（A1 独做，尽量短）**：发布 **SDK vNext**。这一步不需要 EasyAuth 后端实现完成，
只需要契约固定 —— 契约在 `00` 里已经冻结，所以这步是纯打包工作。

**交付内容（缺一项下游就开不了工，见 `01` §8）**：

| # | 内容 |
|---|---|
| 1 | `lifecycle.py` 的三事件内核（新增 items 回调） |
| 2 | `event_type` 一致性校验，**位置在 `webhook.test` 短路之前** |
| 3 | `handover_payloads` TypedDict（每个 Request 含 `event_type`） |
| 4 | `DEFAULT_MAX_BODY_BYTES` 提到 256 KiB |
| 5 | `manifest.py` 的 `_validate_lifecycle()` 白名单放行 `handover_asset_types` |
| 6 | 目录接口 `get_directory_user_by_authentik_sub(sub)`（EasyProject P2 的硬依赖） |
| 7 | 包内契约样本 `easyauth_app_sdk/contract_samples/handover_v2/*.json`，并在 `pyproject.toml` 的 package-data 里显式包含 |
| 8 | 回调异常边界改为固定文案，不再拼 `str(error)` |

**解锁凭据必须是可机械核对的三样东西**，不是"我发布了"这句话：

1. **版本号锁死**：`easyauth-app-sdk` 的 `pyproject.toml` version、
   `descriptor.SDK_VERSION`、`uv.lock`、CHANGELOG 四处**取同一个值**；
2. **两个 SHA**：构建所用的 **commit SHA** 与产出 **wheel 的 SHA-256**，记进 CHANGELOG；
3. **下游各自更新 `VENDORED.md`**（EasyTrade / EasyProject 的 vendor 目录各有一份），
   写上同一组版本号与 SHA。

**A3 / A5 以自己仓库的 `VENDORED.md` 更新完成为开工信号**，不是以"A1 说发完了"为信号。
只改源码不改版本号、或只发包不同步 `descriptor.SDK_VERSION`，都会让下游 vendor 到不同的提交
而没人发现。

**之后全部并行**：

| Agent | 可开工条件 |
|---|---|
| A1 EasyAuth 后端 | 立即 |
| A2 EasyAuth 前端 | A1 提交 `01` §6 的 API 契约章节后 |
| A3 EasyTrade 后端 | SDK vNext 发布后 |
| ~~A4 EasyTrade 前端~~ | **本期取消**（代管废弃，F1/F2/F3 不会发生） |
| A5 EasyProject 后端 | **三道门禁**，见下表。**现在就能做**：`05` §2.1 身份映射的本地命中那一半、§2.3 `hint`、§3.1.2 终态谓词选择器 |
| ~~A6 EasyProject 前端~~ | **本期取消**（同上） |

### A5 的三道门禁与解锁凭据

「批准了」这句话不能当开工依据 —— 不同 agent 会在不同时点各自认为已经解锁。
三样凭据**必须同时具备**，且都是可以贴出来的东西：

| 门禁 | 凭据 | 解锁了什么 |
|---|---|---|
| AG-00 所有权裁定（`08` §1） | `EasyProject/contracts/ownership.md` 的**合入 commit SHA** | 各 owner 可以开始写 `system_handover` 命令；A5 可以写 M06 编排 |
| AG-00 system-actor 裁定（`08` §2） | 同上（两份裁定合入同一文件） | actor / 锁序 / 幂等 / 审批锁语义确定 |
| CCR（`09`） | **CCR 编号 + `status: APPROVED`** | 端点 v2 改写、新错误码、descriptor 输出、测试向量 |

- **提交人**：AG-06（A5）在开工第一天把三份材料交给 AG-00；
- **产物路径**：`08` / `09` 的正文原样落进 EasyProject 仓库对应位置；
- **时限**：AG-00 在 1 个工作日内批准或退回，退回必须写明理由；
- **三项未齐时**，A5 只允许做上表"现在就能做"的三项，**不得**碰任何跨模块表或契约文件。

## 跨仓库对齐的机械保证

契约样本（preview / items / execute 的请求与响应）**随 SDK 分发**，不放在 EasyAuth 仓库里让下游
跨目录去读 —— 下游 CI 独立检出，兄弟目录必然不存在，那样的测试会稳定退化成 skip。

各仓库的契约测试用 `importlib.resources` 从 SDK 包内读取样本做逐字段比对。
**样本缺失必须让测试失败，不允许 skip 通过。** 样本变更即所有下游测试失败，这是契约漂移的第一道拦截。

## 需要人走流程的三件事

1. **EasyProject CCR**：给既有操作 `postEasyauthLifecycleHandover` 补 8 个错误码。
   **可直接提交的正文见 [`09`](09-easyproject-ccr.md)。** 周期长于代码实现，开工第一天就提。
   **它是 M06 交接端点实施的门禁** —— 端点改写、错误码、descriptor、测试向量都要等 APPROVED。
2. **EasyProject AG-00 两份裁定**（所有权 + system-actor 语义）：正文见 [`08`](08-easyproject-ag00-rulings.md)，
   批准后追加进 `EasyProject/contracts/ownership.md`。**它是各领域 `system_handover` 命令的门禁**，
   与 CCR 是两道独立的门。
3. **EasyAuth ADR-002 修订**：**只剩 §36 一条**（自助申请审批人允许沿主管链向上，由 D3 驱动）。
   §19 的修订随代管废弃**一并取消**，该条款保持原样。修订文本见 `01` §9。

## 已知缺口（明确不做，但必须记着）

1. **钉钉在途审批实例的转办**：`ApprovalInstance` 既不存当前审批人，**也与 `ApprovalRule` 没有
   任何关联字段**，钉钉客户端又没有转办接口。因此本期**连"逐条列出受影响实例"都做不到** ——
   按 APP 粗匹配的清单会同时漏报误报，给出的条数是个假数字。
   降级为**存在性提示**：「本应用存在未终结的钉钉审批，可能有由他审批的条目，请到钉钉检查并人工转办」，
   不列逐条、不给条数。见 `00` §11.1、`01` §4.5.3。
   补做条件：先给 `ApprovalInstance` 持久化当前审批人，再确认钉钉转办 API 可用。
   （EasyAuth 自身的权限申请审批人、以及钉钉审批规则的审批人配置，**本期都必做**，不在缺口之列。）
2. **EasyProject `WorkRecordRow.created_by_` 的归属语义**：字段名是历史式的但实际充当当前归属，
   改它需要独立的领域改造（新增显式 owner 列 + 迁移 + 鉴权切换）。见 `05` §3.4。
3. **人员集合 scope 泛化 / 代管授权**：本期已砍（`00` §7）。若日后主管反馈"只看名称和摘要判断不了归属"，
   再单独立项。
4. **webhook HMAC 未覆盖 `X-EasyAuth-Event` / `X-EasyAuth-Delivery`**：改签名串需要同步全部下游与
   已冻结的测试向量，成本高，单独立项。本次的补偿是**在 body 里加签名覆盖的 `event_type` 字段**，
   四个事件无一例外，SDK 在 `webhook.test` 短路之前就比对。见 `00` §10.1。
   （早期写的"校验 event 头与 body `mode` 一致"已作废：`items` 没有 `mode`，
   而 `webhook.test` 在 SDK 里根本不看 body 就短路返回。）

## 关键决策速查

完整 13 条见 `00` §3。最容易被实现者忽略的四条：

- **D6**：未声明交接能力的 APP 状态是 `blocked`，**不是**"已完成"；整单永不 `completed`。
- **D7**：在职提前交接**只搬数据、不动权限**；离职日到来时同一张单升级并**重新盘点**。
- **D11**：只转"活的责任"；创建人、评论、操作日志等历史事实一律不动。
