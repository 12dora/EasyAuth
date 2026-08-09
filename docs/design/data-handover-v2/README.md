# 数据交接 v2 · 设计文档集

本目录是本次「离职/转岗/在职数据交接」改造的**全部**设计文档，覆盖 EasyAuth、EasyTrade、
EasyProject 三个仓库。文档统一放在这里，各仓库不再分散存放。

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

**`00` 是唯一基准。** 里面的字段名、事件名、状态值、HTTP 状态码语义对所有仓库冻结；
任何一方需要变更，先改 `00`，再同步全部下游文档，不得在自己仓库内单方面调整。

## 并行边界

- **A1 / A3 / A5**（三个后端）可立即并行开工，都只依赖 `00` §10 的 webhook 契约。
- **A2** 依赖 `01` §6 的 HTTP API 契约章节 —— A1 必须**先提交该章节**。
- **A4 / A6** 各自依赖同仓库后端的一个小接口改动（候选接口分流 / 目录响应补 `isActive`），
  该改动落地后即可开工，无需等整个后端完成。

## 跨仓库对齐的机械保证

A1 产出 `EasyAuth/tests/contract_samples/handover_v2/` 下的六份 golden JSON
（preview / items / execute 的请求与响应）。A3 与 A5 的契约测试**直接读这批样本**做逐字段比对，
不靠人工对齐。样本变更即所有下游测试失败，这是契约漂移的第一道拦截。

## 需要人走流程的两件事

1. **EasyProject CCR**：给既有操作 `postEasyauthLifecycleHandover` 补 6 个错误码
   （`05` §5.2）。周期长于代码实现，开工第一天就提，但不阻塞其他开发。
2. **EasyAuth ADR-002 修订**：两条现行条款与本设计抵触，修订文本见 `01` §9。

## 关键决策速查

完整 13 条见 `00` §3。最容易被实现者忽略的四条：

- **D2**：主管只接管"事"，不接管数据 —— 数据**不会**自动落到主管名下。
- **D6**：未声明交接能力的 APP 状态是 `blocked`，**不是**"已完成"；整单永不 `completed`。
- **D7**：在职提前交接**只搬数据、不动权限**；离职日到来时同一张单升级并**重新盘点**。
- **D11**：只转"活的责任"；创建人、评论、操作日志等历史事实一律不动。
