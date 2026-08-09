# 09 · EasyProject CCR（可直接提交）

> 本文件是按 `EasyProject/contracts/workflow.md` §6 的六要素写成的**契约变更请求正文**。
> AG-00 审核后原样提交进 EasyProject 的 CCR 流程。
>
> **它是 M06 交接端点实施的门禁**：CCR APPROVED 之前，冻结基线、生成器、测试向量、
> 新错误码的实现与返回、descriptor 输出变更**都不能动**。
> 与 `08` 的两份 AG-00 裁定是**两道独立门禁**，不要混为一谈。
>
> **开工第一天就提** —— 审批周期长于代码实现。

---

## CCR-DH2-EP-01：EasyProject 数据交接 v2 基线元数据补齐

- **状态**：PROPOSED
- **提出人**：AG-00
- **日期**：2026-08-10
- **受影响 operation**：`postEasyauthLifecycleHandover`（1 个，既有）

---

### 1. 冲突描述

冻结基线里这个 operation **已经存在**：

```text
POST /api/v1/easyauth/lifecycle/handover
operationId = postEasyauthLifecycleHandover
x-owner-agent = AG-06 / x-owner-module = M06
x-auth = easyauth-hmac / x-required-permissions = []
x-error-codes = [WEBHOOK_SIGNATURE_INVALID, HANDOVER_CONFLICT, VALIDATION_ERROR]
```

但两处已经跟不上契约 v2：

1. `summary` 仍写「EasyAuth 交接 preview/execute」，而 v2 在**同一个 URL** 上定义
   **preview / items / execute 三个事件**（items 是新增**事件**，不是新增 HTTP path，
   靠 `X-EasyAuth-Event` 分发）。
2. `x-error-codes` 只有 3 项，无法表达 v2 的失败面：身份解析失败、事件不受支持、
   事件与 body 不一致、体积超限、投递冲突、资产类型未声明。

按现状实现，这些失败只能挤进 `VALIDATION_ERROR`，或者干脆返回一个未登记的错误码 ——
后者会被契约门禁直接判漂移。

---

### 2. 不能在模块内部适配的原因

`x-error-codes`、operation `summary`、受保护 endpoint 向量都是**冻结契约资产**，模块 owner 无权直接改。

更关键的一点：**只改生成后的 `openapi-baseline.json` 是无效的。**
`contracts/tools/generate_baseline.py` 才是基线的权威再生入口，它硬编码了这个 endpoint 的元数据；
不改生成器，下一次再生会把新增的错误码原样覆盖掉，而且不会有任何报错。

---

### 3. 影响面

| 项 | 数量 |
|---|---|
| 修改的既有 operation | **1** |
| 新增 operation | 0 |
| 新增 HTTP path | 0 |
| 新增 permission code | 0（继续 `easyauth-hmac`，`x-required-permissions=[]`） |
| 新增 scope | **0** —— 代管授权方案已整体废弃（契约 §7），两个下游都不需要新 scope |
| OpenAPI schema 变化 | 0 —— 成功响应体由外部 snake_case webhook 契约约束，基线只冻结 error response 元数据 |
| 数据库迁移 | 不属于本 CCR，按 `08` §1.4 的所有权裁定执行 |

---

### 4. 兼容方案

纯增量，无破坏性变更：

- URL、`operationId`、HMAC security、既有三个错误码、标准 `ErrorBody` **全部保留不动**；
- preview / execute 的调用方迁移到 v2 payload；items 走同一 operation + `X-EasyAuth-Event` 分发，
  **不新增独立 URL** —— 那会产生三个重复的 HMAC operation，且每个都要单独登记与维护向量；
- 验签失败继续返回 **401**。契约 §10.6 允许各下游在 401/403 之间沿用本仓库既有约定，
  EasyAuth 侧两者处置完全相同（`failed` 且不可重试）。这一点在本 CCR 里写明，避免日后被当成不一致；
- descriptor 以 `capabilities` 含 `"handover.v2"` 作为**唯一**能力判定，并使用**平铺**的
  `handover_asset_types`（不是嵌套的 `lifecycle.handover` 对象）。

---

### 5. 变更内容

#### 5.1 `summary`

改为「EasyAuth 交接 preview/items/execute」。

#### 5.2 `x-error-codes` 冻结为完整 10 项

| 错误码 | HTTP | 说明 | 状态 |
|---|---:|---|---|
| `WEBHOOK_SIGNATURE_INVALID` | 401 | HMAC 验签失败 | 保留 |
| `HANDOVER_CONFLICT` | 409 | 审批锁、当前归属已变、迟到的旧 generation 等业务冲突 | 保留 |
| `VALIDATION_ERROR` | 422 | JSON / 字段形状不合法 | 保留 |
| `WEBHOOK_TIMESTAMP_INVALID` | 400 | timestamp 非法或超 300 秒窗口 | **新增** |
| `WEBHOOK_PAYLOAD_CONFLICT` | 409 | 同 `(task_id, generation, batch_id)` 不同 canonical payload hash | **新增** |
| `EVENT_UNSUPPORTED` | 422 | `X-EasyAuth-Event` 不是 preview/items/execute/test | **新增** |
| `EVENT_MODE_MISMATCH` | 422 | 事件头与 body 的 `event_type` 不一致（契约 §10.1 的强制安全补偿） | **新增** |
| `IDENTITY_UNMAPPED` | 409 | Authentik `sub` 无法映射为本地 dtuid | **新增** |
| `ASSET_TYPE_UNDECLARED` | 422 | 请求里的资产类型未在 descriptor 声明 | **新增** |
| `REQUEST_BODY_TOO_LARGE` | 413 | 请求体超过 256 KiB | **新增** |
| `SNAPSHOT_STALE` | **412** | `snapshot_token` 与当前数据不一致（契约 §10.5.1） | **新增** |

> **`SNAPSHOT_STALE` 必须与 `HANDOVER_CONFLICT` 分开成两个状态码。**
> EasyAuth 只看状态码不解析响应体（契约 §10.6）：412 让它把 action **退回 `pending` 重新预演**，
> 409 判 `failed`。合在 409 里，"清单变了"会被永久标成失败，用户无路可走。

> `EVENT_MODE_MISMATCH` 的名字沿用「mode」是历史原因，判定依据已升级为 body 里的
> `event_type` 字段（契约 §10.1）。**不改名**：错误码一旦进基线就是冻结资产，
> 为了措辞再走一次 CCR 不值得。

---

### 6. 同步修改清单（CCR 批准后由 AG-00 在同一变更集完成）

1. **`contracts/tools/generate_baseline.py`** ← **必须先改这里**
   - endpoint summary 改为 preview/items/execute；
   - 上述 10 个错误码写进生成源；
   - 不新增 path / permission / scope / schema。
2. **`contracts/openapi-baseline.json`**
   - 由生成器**重新生成**，不手工长期维护。**禁止只手改 JSON。**
3. **`contracts/test-vectors/webhook-hmac.json`**
   - 保留既有 endpoint 与签名正反例（该文件已把 handover URL 列入受保护 endpoint）；
   - 新增 preview / items / execute 三个**正例**；
   - 新增**反例**：timestamp 超窗、未知 event、事件头与 body `event_type` 不一致、
     把事件头改成 `webhook.test`、items 带 `mode` 或缺 `asset_type`/`snapshot_token`、
     同三元组不同 body；
   - 继续冻结验签失败为 **401**。
4. **`contracts/test-vectors/error-bodies.json`**
   - 补齐全部新码的标准 `{"detail":{"code","message","traceId"}}` 样本；
   - 不改跨系统状态码语义（EasyAuth 不解析下游错误体字段）。
5. **SDK / contract golden**
   - SDK 增加 items 事件、v2 TypedDict、256 KiB 默认上限、`handover_asset_types` 的 manifest 白名单、
     以及 `event_type` 一致性校验；
   - golden 样本作为 **SDK 包内资源**分发，EasyProject 的契约测试**缺样本必须失败**，
     不允许 skip 通过。

---

### 7. 回滚方式

| 场景 | 步骤 |
|---|---|
| **尚未启用 v2** | 回退生成器变更 → 重生成 baseline 与向量 → 应用代码回到旧 endpoint 行为 |
| **已经启用 v2** | ① 先从 descriptor 的 `capabilities` 移除 `handover.v2`，让 EasyAuth 停止发起新的 v2 请求；② 确认无 execute 在途；③ 再回退应用、SDK、生成器、baseline 与向量 |

**已写入的幂等记录、generation 水位、审计与业务历史，不得因为 CCR 回滚而删除。**
数据恢复走**新 generation 的补偿性交接** —— 契约 §10.5.2 规定旧 generation 必须被拒绝，
"重放上一轮"这条路本来就不通。

---

### 8. CCR 批准前的可做 / 不可做边界

按 `contracts/workflow.md` §6「AG-00 批准前所有 Agent 继续用旧契约」：

| 可以先做 | 必须等 APPROVED |
|---|---|
| `05` §2.1 身份映射（P2，纯内部实现） | 交接端点的 v2 改写 |
| `05` §2.3 `hint` 取数（只读） | 新错误码的实现与返回 |
| `05` §3.1.2 终态谓词的共享选择器（只读） | descriptor 输出变更 |
| 上述各项的单元测试 | 测试向量更新、契约测试 |

各领域的 `system_handover` 命令**另受 `08` 的所有权裁定门禁**，与本 CCR 无关，不要混淆。
