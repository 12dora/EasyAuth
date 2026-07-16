# 实施执行顺序（给实施 agent 的任务卡，全部绝对路径）

> 第 8 篇。面向逐 PR 实施的 agent；设计裁量一律以第 1~7 篇为准，
> 发现契约与代码现实冲突时**停下报告**，不要在实现里悄悄偏离。

## 0. 全局约定（每个 agent 开工前必读）

**必读文档（按此顺序）**：

1. `/Users/konata/code/EasyAuth/docs/design/platform-directory-notify/README.md`（索引+十条决策）
2. `/Users/konata/code/EasyAuth/docs/design/platform-directory-notify/01-API契约-权威版.md`（契约测试逐字段对照它的 JSON 示例）
3. 本 PR 对应篇（各任务卡里列出）

**依赖与合入顺序**：

```
PR-1 ──┬──▶ PR-2（轨道 A，独立 agent + worktree）─────────┐
       └──▶ PR-3 ─▶ PR-4（轨道 B，同一 agent 连续做）──────┴──▶ PR-5
```

- PR-1 必须先合入生产分支，PR-2 与 PR-3/4 才能开工（都依赖 `AppCapability`）；
- 轨道 A/B 可并行（各自 worktree）；碰撞点只有
  `/Users/konata/code/EasyAuth/src/easyauth/api/urls.py` 与
  `/Users/konata/code/EasyAuth/docs/api/easyauth-public-api.md`：**PR-2 先合，PR-4 rebase**；
- PR-5 等 PR-2、PR-4 都合入且 `/Users/konata/code/EasyAuth/tests/contract_samples/` 就位后启动。

**本机测试环境（macOS，2026-07 核实）**：

- 仓库根 `/Users/konata/code/EasyAuth/.venv` 是 **Linux aarch64 容器产物，不可用也不要重建**；
- 用 uv 管理的解释器自建临时 venv：

```bash
~/.local/share/uv/python/cpython-3.12.13-macos-aarch64-none/bin/python3.12 -m venv /tmp/easyauth-impl-venv
/tmp/easyauth-impl-venv/bin/pip install -e '/Users/konata/code/EasyAuth[dev]'
cd /Users/konata/code/EasyAuth && /tmp/easyauth-impl-venv/bin/pytest tests/unit/<本PR范围> -x
```

- **存量失败（与你的改动无关，勿修）**：
  `tests/integration/auth/test_local_admin_login.py::test_change_password_rejects_invalid_new_password[short...]`、
  `tests/integration/integrations/test_dingtalk_stream.py::test_handler_acks_ok_and_marks_duplicate`（需 localhost:6379）；
- basedpyright 在 all 模式下有存量报错，基线口径：**只保证新增/修改文件零新告警**；
- ruff 配置在 `/Users/konata/code/EasyAuth/pyproject.toml`，提交前跑
  `/tmp/easyauth-impl-venv/bin/ruff check <改动文件>`。

**每个 PR 的统一验收门**：本 PR 测试目录全绿 + 迁移可 `migrate` 正向与
`migrate <app> <前一编号>` 逆向 + `pytest tests/unit -x` 无回归 + ruff 干净。

---

## PR-1 基座（无行为变化，最先合入）

**读**：第 2 篇 §1、§4、§5；第 5 篇 §1、§4。

| 动作 | 绝对路径 | 说明 |
|---|---|---|
| 改 | `/Users/konata/code/EasyAuth/src/easyauth/applications/models.py` | 追加 `AppCapability` 模型 + `CAPABILITY_*` 常量（字段级定义照抄第 2 篇 §1） |
| 建 | `/Users/konata/code/EasyAuth/src/easyauth/applications/capabilities.py` | `app_capability_enabled(app_id, capability)` / `app_capability_config(app_id, capability)` 两个读取函数 |
| 建 | `/Users/konata/code/EasyAuth/src/easyauth/applications/migrations/0023_*.py` | `makemigrations applications` 生成（当前编号到 0022，以生成为准） |
| 改 | `/Users/konata/code/EasyAuth/src/easyauth/accounts/models.py` | `DingTalkUserMirror.Meta` 加 `accounts_dt_user_manager_idx`；`UserMirror.Meta` 加 `accounts_user_dingtalk_idx`（第 2 篇 §4 表） |
| 建 | `/Users/konata/code/EasyAuth/src/easyauth/accounts/migrations/`（makemigrations 生成） | 纯 AddIndex |
| 建 | `/Users/konata/code/EasyAuth/src/easyauth/admin_console/app_capability_api.py` | superuser-only 开关 API，风格对齐同目录 `credentials_api.py`/`managed_scope_policy_api.py`；开/关写审计 `app_capability_enabled`/`app_capability_disabled` |
| 改 | `/Users/konata/code/EasyAuth/src/easyauth/admin_console/urls.py` | 注册上述路由 |
| 改 | `/Users/konata/code/EasyAuth/src/easyauth/applications/permission_templates.py`（如顶层白名单在 `permission_template_parsing.py`，改那里） | manifest 顶层接受可选 `capabilities: ["directory","notify"]` 节：白名单校验、**只记录不产生任何授权副作用**（第 6 篇 §4） |
| 测 | `/Users/konata/code/EasyAuth/tests/unit/applications/`、`/Users/konata/code/EasyAuth/tests/unit/admin_console/` | 模型约束、读取函数、开关 API、审计、manifest 节校验 |

范围外：console 前端开关页（G1 冒烟直接调 console API 即可，前端页为后续可选项）。

---

## PR-2 目录 API（轨道 A，依赖 PR-1）

**读**：第 1 篇 §0、§D、§X；第 5 篇 §2、§4、§5。

| 动作 | 绝对路径 | 说明 |
|---|---|---|
| 建 | `/Users/konata/code/EasyAuth/src/easyauth/api/directory_views.py` | 5 个函数视图（D1~D5）。认证/限流/审计三段式照抄 `/Users/konata/code/EasyAuth/src/easyauth/api/views.py:45-122` 的 `query_user_permissions` 结构；能力检查用 PR-1 的 `app_capability_enabled` |
| 建 | `/Users/konata/code/EasyAuth/src/easyauth/api/directory_payloads.py` | 镜像行 → 契约 JSON 的拼装（user_ref 解析、`dt:` 前缀、manager 摘要、部门名 join） |
| 改 | `/Users/konata/code/EasyAuth/src/easyauth/api/urls.py` | 追加 5 条 `apps/<str:app_key>/directory/...` 路由（无尾斜杠，命名对齐现有） |
| 改 | `/Users/konata/code/EasyAuth/docs/api/easyauth-public-api.md` | 新增 `## 5. 用户目录`；**同时把原 §5 Webhook→§7、§6 SDK→§8 重编号**（PR-4 只追加 §6，不再动编号） |
| 建 | `/Users/konata/code/EasyAuth/tests/contract_samples/directory/*.json` | 第 1 篇 §D 每个 JSON 示例一份样例文件（PR-5 复用） |
| 测 | `/Users/konata/code/EasyAuth/tests/unit/api/test_directory_views.py` | 契约测试逐字段对照样例；覆盖：`user_id` 为 null 条目、`dt:` 引用、include_inactive、404 reason 区分、429 带 Retry-After、能力未开通 403 文案、Cache-Control 头 |

实现提醒：查询基表是 `DingTalkUserMirror`（`status=="active"` 派生 `active`），
LEFT 关联 `UserMirror`（键 `dingtalk_corp_id`+`dingtalk_userid`）；搜索过滤参考
`/Users/konata/code/EasyAuth/src/easyauth/admin_console/users_api.py:117` 的写法但
**独立实现，不共享代码**（第 7 篇 §1 表）。

---

## PR-3 通知底座（轨道 B 前半，依赖 PR-1）

**读**：第 2 篇 §2、§3；第 4 篇全文；第 3 篇 §0。

| 动作 | 绝对路径 | 说明 |
|---|---|---|
| 建 | `/Users/konata/code/EasyAuth/src/easyauth/notify/__init__.py`、`apps.py`、`models.py`、`services.py`、`migrations/__init__.py` | 新 Django app；`models.py` 照第 2 篇 §2/§3 字段级定义；`services.py` 做受理（校验/2048 字节组装校验/解析合并收件人/幂等/配额判定/事务内 `enqueue_task`） |
| 改 | `/Users/konata/code/EasyAuth/src/easyauth/config/settings/base.py` | `INSTALLED_APPS` 加 `easyauth.notify`（仅此一行，Celery 接线留给 PR-4） |
| 建 | `/Users/konata/code/EasyAuth/src/easyauth/notify/migrations/0001_initial.py` | makemigrations 生成 |
| 改 | `/Users/konata/code/EasyAuth/src/easyauth/integrations/dingtalk/api_client.py` | 追加 `DINGTALK_OAPI_BASE_URL` 常量与 `send_work_notification` / `get_send_progress` / `get_send_result` 三方法（oapi 例外注释引用第 4 篇 §1；`?access_token=` 查询参数分支；复用现有 `get_access_token` 缓存） |
| 测 | `/Users/konata/code/EasyAuth/tests/unit/notify/`（新目录）、`/Users/konata/code/EasyAuth/tests/unit/integrations/` | 第 7 篇 §4.1 中「收件人解析/受理幂等/msg 组装」三组；钉钉 HTTP 全 mock（对齐现有 `tests/unit/integrations/` 的 stub 方式） |

---

## PR-4 通知管道 + API（轨道 B 后半，依赖 PR-3；rebase 到 PR-2 之后）

**读**：第 3 篇全文；第 1 篇 §N；第 5 篇 §3、§5。

| 动作 | 绝对路径 | 说明 |
|---|---|---|
| 建 | `/Users/konata/code/EasyAuth/src/easyauth/tasks/notify.py` | `easyauth.notify.deliver_message` / `reconcile_send_results` / `prune_messages` 三个 `@shared_task` 薄壳，编排逻辑调 `notify/services.py`（任务参数与算法照第 3 篇 §1/§3/§5/§6） |
| 改 | `/Users/konata/code/EasyAuth/src/easyauth/config/settings/base.py` | ① `CELERY_IMPORTS`（316-325 行区段）加 `easyauth.tasks.notify`；② `CELERY_TASK_ROUTES`（313-315 行）加 `easyauth.notify.deliver_message` → 队列 `notify`；③ `CELERY_BEAT_SCHEDULE`（326-360 行）加 reconcile(60s)/prune(86400s)；④ 各 `EASYAUTH_NOTIFY_*` 默认值（第 2 篇 §1、第 3 篇 §4/§5/§6 出现的全部） |
| 改 | `/Users/konata/code/EasyAuth/src/easyauth/config/celery.py` | `_SUCCESS_HEARTBEATS` 登记 `easyauth.notify.deliver_message`（第 3 篇 §7 建议项） |
| 建 | `/Users/konata/code/EasyAuth/src/easyauth/api/notify_views.py` | N2 POST + N4 GET 两个函数视图；限流矩阵按第 5 篇 §5（`notify-post-rate` 按 app、日配额 429+Retry-After 到次日零点） |
| 改 | `/Users/konata/code/EasyAuth/src/easyauth/api/urls.py` | 追加 2 条 `apps/<str:app_key>/notify/messages...` 路由 |
| 改 | `/Users/konata/code/EasyAuth/docs/api/easyauth-public-api.md` | 追加 `## 6. 通知`（编号已由 PR-2 腾好） |
| 建 | `/Users/konata/code/EasyAuth/tests/contract_samples/notify/*.json` | 第 1 篇 §N 全部 JSON 示例 |
| 测 | `/Users/konata/code/EasyAuth/tests/unit/notify/`、`/Users/konata/code/EasyAuth/tests/unit/api/test_notify_views.py` | 第 7 篇 §4.1 的「状态机/对账/claim-lease/配额限流」四组 + §4.2 契约测试（202/200/409 三态、error_code 七值、聚合状态） |

Celery 全链路自测（第 7 篇 §4.3）：`EASYAUTH_OUTBOX_DISPATCH_SECONDS=1` 压缩等待，
断言 outbox 行 → 投递 → recipients 状态推进。

---

## PR-5 SDK + 集成指南（依赖 PR-2 + PR-4 合入）

**读**：第 6 篇全文；`/Users/konata/code/EasyAuth/tests/contract_samples/` 全部样例。

| 动作 | 绝对路径 | 说明 |
|---|---|---|
| 改 | `/Users/konata/code/EasyAuth/sdk/python/src/easyauth_app_sdk/client.py` | 7 个新方法（签名照第 6 篇 §1，含 docstring）+ `NOTIFY_TEMPLATE_*`、`DINGTALK_REF_PREFIX` 常量 |
| 改 | `/Users/konata/code/EasyAuth/sdk/python/src/easyauth_app_sdk/manifest.py` | 可选顶层节 `capabilities` 白名单 + `_validate_capabilities`（第 42 行附近的可选节白名单） |
| 改 | `/Users/konata/code/EasyAuth/sdk/python/src/easyauth_app_sdk/__init__.py` | `__all__` 补新常量 |
| 改 | `/Users/konata/code/EasyAuth/sdk/python/pyproject.toml` | `version = "0.2.0"`（第 7 行） |
| 改 | `/Users/konata/code/EasyAuth/sdk/python/src/easyauth_app_sdk/descriptor.py` | `SDK_VERSION = "0.2.0"`（第 13 行，**与 pyproject 必须同步**） |
| 建 | `/Users/konata/code/EasyAuth/sdk/python/CHANGELOG.md` | Keep a Changelog 格式；补记 0.1.0 既有能力 + 0.2.0 本次内容 |
| 建 | `/Users/konata/code/EasyAuth/sdk/python/tests/test_client_directory_notify.py` | stub server 回放 `tests/contract_samples/` 样例，验证 URL/query/body 组装（风格对齐同目录 `test_client.py`） |
| 改 | `/Users/konata/code/EasyAuth/docs/guides/easyauth-app-sdk-integration.md` | 新增 `## 用户目录与钉钉通知`（内容清单见第 6 篇 §5） |

SDK 测试命令：

```bash
cd /Users/konata/code/EasyAuth && PYTHONPATH=sdk/python/src /tmp/easyauth-impl-venv/bin/pytest sdk/python/tests
```

---

## 收尾（不属于任何实施 agent，人工执行）

- G1 冒烟（第 7 篇 §3 表）：钉钉 token 互用性、三模板真机展示、对账升级——需要
  console 操作与真实钉钉账号；
- 发布前检查单（第 7 篇 §3）：企业钉钉版本确认、
  `IntegrationSettings.dingtalk_agent_id` 配置、`deploy/` 下 worker 编排更新；
- 实施全部完成后在本目录回填「实施偏差记录」（若有）。
