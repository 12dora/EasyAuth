# 数据交接 v2 · 设计文档集

本目录是本次「离职/转岗/在职数据交接」改造的**全部**设计文档，覆盖 EasyAuth、EasyTrade、
EasyProject 三个仓库。文档统一放在这里，各仓库不再分散存放。

> **当前状态：代管授权已废弃，范围大幅收窄。**
> 两轮对抗式复核共产出约 70 条发现。第一处结构性问题（代管授权模型）已定案：**整体砍掉**，
> 悬置期的可见性改由交接单自身的资产明细承担（契约 §7）。
> 随之取消的还有：`04`/`06` 两份下游前端文档、EasyTrade 的 B3、EasyProject 的 P1、ADR-002 §19 修订。
>
> 另两处也已定案：**审批责任纳入本期**（`WorkRecord` 写成 D11 显式例外，见 `00` §11.1、`01` §4.5）；
> **EasyProject 完整做但 A5 阻塞**，等 AG-00 裁定所有权与 system-actor 语义。
> **开工前必读 [`07-review-log.md`](07-review-log.md)。**

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

**`00` 是唯一基准。** 里面的字段名、事件名、状态值、HTTP 状态码语义对所有仓库冻结；
任何一方需要变更，先改 `00`，再同步全部下游文档，不得在自己仓库内单方面调整。

## 并行边界（复核后修正，原来的"三个后端立即并行"不成立）

A3 / A5 的实现要用到 v2 SDK（新的 `items` 回调、`handover_payloads` TypedDict、256 KiB 上限）
与契约样本，这些都是 A1 的产出。所以真实次序是**一个短的串行头 + 大段并行**：

**第 0 步（A1 独做，尽量短）**：发布 **SDK vNext**，含
`lifecycle.py` 的三事件内核、`handover_payloads` 类型、以及**打包进 SDK 的契约样本**
（`easyauth_app_sdk.contract_samples`）。打版本号并记录 SHA。这一步不需要 EasyAuth 后端实现完成，
只需要契约固定 —— 契约在 `00` 里已经冻结，所以这步是纯打包工作。

**之后全部并行**：

| Agent | 可开工条件 |
|---|---|
| A1 EasyAuth 后端 | 立即 |
| A2 EasyAuth 前端 | A1 提交 `01` §6 的 API 契约章节后 |
| A3 EasyTrade 后端 | SDK vNext 发布后 |
| ~~A4 EasyTrade 前端~~ | **本期取消**（代管废弃，F1/F2/F3 不会发生） |
| A5 EasyProject 后端 | **阻塞**。开工前置：AG-00 的所有权裁定 + system-actor 语义裁定 + CCR APPROVED。裁定前只能做 §2.1 身份映射与 §2.3 `hint`（`07` §1.3） |
| ~~A6 EasyProject 前端~~ | **本期取消**（同上） |

## 跨仓库对齐的机械保证

契约样本（preview / items / execute 的请求与响应）**随 SDK 分发**，不放在 EasyAuth 仓库里让下游
跨目录去读 —— 下游 CI 独立检出，兄弟目录必然不存在，那样的测试会稳定退化成 skip。

各仓库的契约测试用 `importlib.resources` 从 SDK 包内读取样本做逐字段比对。
**样本缺失必须让测试失败，不允许 skip 通过。** 样本变更即所有下游测试失败，这是契约漂移的第一道拦截。

## 需要人走流程的两件事

1. **EasyProject CCR**：给既有操作 `postEasyauthLifecycleHandover` 补 6 个错误码（`05` §5.2）。
   周期长于代码实现，开工第一天就提。**它是 M06 交接端点实施的门禁** —— 只有 P1/P2 修复与各领域的
   `system_handover` 命令可以先行，端点改写、错误码、descriptor、测试向量都要等 APPROVED。
2. **EasyAuth ADR-002 修订**：两条现行条款与本设计抵触，修订文本见 `01` §9。

## 已知缺口（明确不做，但必须记着）

1. **钉钉在途审批实例的转办**：`ApprovalInstance` 不存当前审批人，钉钉客户端无转办接口。
   本期改为在交接单上只读呈现 + 跳转链接 + 「需人工转办」标记。见 `00` §11.1、`01` §4.5.3。
   （EasyAuth 自身的权限申请审批人、以及钉钉审批规则的审批人配置，**本期都必做**，不在缺口之列。）
2. **EasyProject `WorkRecordRow.created_by_` 的归属语义**：字段名是历史式的但实际充当当前归属，
   改它需要独立的领域改造（新增显式 owner 列 + 迁移 + 鉴权切换）。见 `05` §3.4。
3. **人员集合 scope 泛化 / 代管授权**：本期已砍（`00` §7）。若日后主管反馈"只看名称和摘要判断不了归属"，
   再单独立项。
4. **webhook HMAC 未覆盖 `X-EasyAuth-Event` / `X-EasyAuth-Delivery`**：可利用面窄，且 EasyProject 的
   冻结测试向量已把签名串写死，改动需单独立项。本次的补偿是**强制校验 event 头与 body `mode` 一致**。
   见 `00` §10.1。

## 关键决策速查

完整 13 条见 `00` §3。最容易被实现者忽略的四条：

- **D6**：未声明交接能力的 APP 状态是 `blocked`，**不是**"已完成"；整单永不 `completed`。
- **D7**：在职提前交接**只搬数据、不动权限**；离职日到来时同一张单升级并**重新盘点**。
- **D11**：只转"活的责任"；创建人、评论、操作日志等历史事实一律不动。
