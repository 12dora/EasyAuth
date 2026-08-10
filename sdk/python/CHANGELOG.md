# Changelog

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.4.0] - 2026-08-10

### Breaking

- 生命周期交接升级为 v2 三事件内核: 新增 `lifecycle.handover.items` 回调;
  **`on_handover_items` 在 `lifecycle_http_response` / `easyauth_lifecycle_router`
  上为必填参数**(无默认值; 接线期失败优于运行时 422)。
- 所有 body 必须含 `event_type` 且与 `X-EasyAuth-Event` 一致(校验在 `webhook.test`
  短路之前); 默认 body 上限由 64 KiB 提升至 **256 KiB**。
- 回调异常边界改为固定文案「交接回调执行失败，请查看应用日志」, **不再**拼接
  `str(error)`。
- 时间戳超窗验签失败映射为 **HTTP 400**(`TIMESTAMP_SKEW` / `INVALID_TIMESTAMP`),
  与签名/鉴权头失败分离; `WebhookVerificationError` 增加结构化 `reason` 字段。
- manifest `lifecycle.handover_asset_types[]` 的 `detail_supported` / `releasable`
  改为**必填布尔**(契约 §9.1 声明形状; 缺省或非 bool 拒绝)。

### Added

- `signature_failure_status: int = 403` 旋钮: 仅作用于签名不匹配/鉴权头缺失;
  EasyProject 传 `401`, EasyTrade 保持默认 `403`; 错误体含 `error.reason`。
- `HandoverBusinessError`: 业务回调可表达 400/409/412/413/422/423/429;
  可选 `retry_after: int | None` 渲染为响应头 `Retry-After`(契约 §10.6 的 429 退避通道)。
- 白名单外业务状态码降级 500 时写 SDK `warning`; 意外回调异常 `logger.exception`。
- `easyauth_app_sdk.handover_payloads` TypedDict(`Preview`/`Items`/`Execute` 的
  Request/Response; 每个 Request 含 `event_type`)。
- 包内契约样本 `easyauth_app_sdk/contract_samples/handover_v2/*.json`
  (via `package-data`, `importlib.resources` 可读)。
- manifest `lifecycle.handover_asset_types` 白名单放行。
- `verify_webhook` 支持空 body(异步状态查询 GET 分支)。
- `get_directory_user_by_authentik_sub` 纯委托别名; 文档明确既有
  `get_directory_user` 已接受裸 Authentik `sub`。

### Provenance

- 构建提交 C: _(P2 回填)_
- wheel: `sdk/python/dist/easyauth_app_sdk-0.4.0-py3-none-any.whl`
- wheel SHA-256: _(P2 回填)_

## [0.3.0] - 2026-07-16

### Added

- `EasyAuthClientError` 新增结构化字段：`error_code`、`details`、`retry_after`、
  `retry_after_seconds`、`retryable`、`transport_error`，并解析公共 API 统一错误 JSON 与
  `Retry-After`。
- `search_directory_users` 新增可选 `snapshot_id`，支持后续分页固定首屏目录快照；快照变化的
  `409 CONFLICT` 通过结构化错误交由调用方从第一页重新开始。

### Changed

- 网络错误、`429` 与 `5xx` 标记为可重试；`401`、`403`、`404`、`409`、`422` 标记为不可重试。
- manifest 顶层 `capabilities` 校验与服务端前向兼容语义对齐：按 trim/去重后的值校验，接受
  未知非空字符串，同时保持 `validate_manifest` 原样返回传入对象。
- README 补充企业目录、通知异步状态语义、可靠性边界及结构化错误处理示例。

### Security

- 改用拒绝所有 3xx 的 urllib opener，避免自动重定向将 Bearer `Authorization` 转发到其他地址。

## [0.2.0] - 2026-07-16

### Added

- `EasyAuthAppClient` 用户目录方法：`search_directory_users`、`get_directory_user`、
  `get_directory_user_manager`、`list_directory_user_subordinates`、
  `list_directory_departments`。
- `EasyAuthAppClient` 钉钉通知方法：`send_notification`（含可选 `deeplink_title`）、
  `get_notification`。
- 通知相关常量：`NOTIFY_TEMPLATE_TEXT`、`NOTIFY_TEMPLATE_MARKDOWN`、
  `NOTIFY_TEMPLATE_ACTION_CARD`。
- manifest 可选顶层节 `capabilities`（`["directory", "notify"]` 白名单校验）；
  申明仅供展示，**不产生授权副作用**（开通仍由超管手工翻转）。

## [0.1.0] - 2026-07-04

### Added

- 集成描述符：`build_descriptor_payload` / `parse_descriptor_payload`，
  下游在 `GET /.well-known/easyauth-app.json` 暴露应用元数据与权限 manifest。
- 描述符 HTTP 端点：纯函数内核 `descriptor_http_response` + 可选 FastAPI 路由。
- `EasyAuthAppClient`：权限查询（`query_user_permissions`）、manifest 推送
  （`sync_manifest`）、审批中心（`list_approval_templates` / `list_approvals` /
  `create_approval` / `get_approval`）。
- webhook 验签：`verify_webhook` 校验 EasyAuth 反向推送的签名与时间戳。
- 生命周期交接端点：`lifecycle_http_response` + `easyauth_lifecycle_router`
  （preview/execute 同步回调）。
- `validate_manifest`：manifest 结构级 + 交叉引用校验（对齐服务端导入子集）。
