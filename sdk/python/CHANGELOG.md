# Changelog

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.3.0] - 2026-07-16

### Added

- `EasyAuthClientError` 新增结构化字段：`error_code`、`details`、`retry_after`、
  `retry_after_seconds`、`retryable`、`transport_error`，并解析公共 API 统一错误 JSON 与
  `Retry-After`。

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
  `NOTIFY_TEMPLATE_ACTION_CARD`、`DINGTALK_REF_PREFIX`。
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
