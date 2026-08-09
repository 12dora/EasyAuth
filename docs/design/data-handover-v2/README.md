# 数据交接 v2 · 设计文档集

本目录是本次「离职/转岗/在职数据交接」改造的**全部**设计文档，覆盖 EasyAuth、EasyTrade、
EasyProject 三个仓库。文档统一放在这里，各仓库不再分散存放。

> ⚠ **当前状态：不可进入实施。** 两轮对抗式复核共产出约 70 条发现，机械性矛盾已修，
> 但代管授权模型、D11 的下游豁免、EasyProject 实施可行性三处结构性问题尚未定案。
> **开工前必读 [`07-review-log.md`](07-review-log.md)。**

## 阅读顺序

| # | 文档 | 负责 agent | 仓库 |
|---|---|---|---|
| 00 | [总体设计与跨系统契约](00-overview-and-contract.md) | **全体必读** | — |
| 01 | [EasyAuth 后端改造设计](01-easyauth-backend.md) | A1 | EasyAuth |
| 02 | [EasyAuth 前端改造设计](02-easyauth-frontend.md) | A2 | EasyAuth |
| 03 | [EasyTrade 后端改造设计](03-easytrade-backend.md) | A3 | EasyTrade |
| 04 | [EasyTrade 前端改造设计](04-easytrade-frontend.md) | A4 | EasyTrade |
| 05 | [EasyProject 后端接入设计](05-easyproject-backend.md) | A5 | EasyProject |
| 06 | [EasyProject 前端改造设计](06-easyproject-frontend.md) | A6 | EasyProject |
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
| A4 EasyTrade 前端 | A3 落地候选接口改造（`04` §3.1 描述需求，后端实现属 A3）后 |
| A5 EasyProject 后端 | 修 P1/P2 可立即开工；**交接端点本身须等 CCR APPROVED**（`05` §5.2） |
| A6 EasyProject 前端 | **立即** —— `is_active` 与 `includeInactive` 都已存在，无后端前置依赖 |

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

1. **EasyProject 待审批单据的审批人转移**：需要扩展 EasyAuth 审批契约以转移审批实例的当前处理人，
   超出本次范围。见 `05` §3.1.1。
2. **EasyProject `WorkRecordRow.created_by_` 的归属语义**：字段名是历史式的但实际充当当前归属，
   改它需要独立的领域改造（新增显式 owner 列 + 迁移 + 鉴权切换）。见 `05` §3.4。
3. **webhook HMAC 未覆盖 `X-EasyAuth-Event` / `X-EasyAuth-Delivery`**：可利用面窄，且 EasyProject 的
   冻结测试向量已把签名串写死，改动需单独立项。本次的补偿是**强制校验 event 头与 body `mode` 一致**。
   见 `00` §10.1。

## 关键决策速查

完整 13 条见 `00` §3。最容易被实现者忽略的四条：

- **D2**：主管只接管"事"，不接管数据 —— 数据**不会**自动落到主管名下。
- **D6**：未声明交接能力的 APP 状态是 `blocked`，**不是**"已完成"；整单永不 `completed`。
- **D7**：在职提前交接**只搬数据、不动权限**；离职日到来时同一张单升级并**重新盘点**。
- **D11**：只转"活的责任"；创建人、评论、操作日志等历史事实一律不动。
