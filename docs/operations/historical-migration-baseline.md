# 历史破坏性迁移基线

## 背景

`EA-AUD-023` 指出多条早期迁移曾包含无条件删除、清空或静默改写业务事实的行为：

- `access_requests.0009_access_request_idempotency`
- `applications.0012_approval_rule_target_unique`
- `grants.0005_membership_expiration`
- `grants.0003_access_grant_version_unique`
- `accounts.0007_alter_localadminaccount_totp_secret`
- `accounts.0013_directory_user_contact_tombstones`
- `applications.0015_alter_integrationsettings_authentik_api_token`
- `applications.0025_credential_capabilities`

项目尚未上线，但本地开发库、Docker 库和试点快照仍可能包含需要保留的业务事实或凭据。迁移不再把
“未上线”解释为可以静默删除、清空或默认重写数据。

## 迁移策略

上述迁移只允许在可证明安全的历史状态继续执行：

- 申请幂等迁移要求旧 `AccessRequest` 表为空。已有申请缺少可证明的 `idempotency_key` 和
  `payload_digest` 来源，迁移不能自动生成。
- 审批规则目标唯一迁移要求不存在重复 `(app, authorization_group)` 或 `(app, permission)`。
  迁移不能按最大 id 保留一条并删除其余规则。
- 授权成员期限迁移要求旧 `AccessGrant` 表为空。已有父级 `grant_type` 和 `grant_expires_at`
  不能在迁移中静默投射到成员级期限。
- 授权版本唯一迁移要求 `(user, app, version)` 已经唯一。迁移不能自动重编号
  `AccessGrant.version`，因为版本是审批和授权事实的一部分。
- 本地管理员 TOTP 加密迁移要求旧 `totp_secret` 全为空。已有明文种子不能清空，也不能当作
  新密文继续使用。
- DingTalk 用户状态迁移只接受 `active`、`disabled`、`departed`。`inactive`、`deleted`、空串
  或其他未知状态都必须由显式目录修复流程处置，迁移不能批量降级为 `disabled`。
- Authentik 管理 token 加密迁移要求旧 `authentik_api_token` 全为空。已有明文 token 不能清空，
  也不能当作新密文继续使用。
- Credential capability 迁移要求不存在“已启用 App capability 且该 App 仍有 active
  credential”的旧状态。迁移不能把应用能力自动授权给单条凭据。

发现不满足条件的数据时，迁移会在任何破坏性 schema 或数据变更前失败，并输出行数与最多 5 个
样本主键。错误消息不包含 secret 明文。

## 阻断消息

| 迁移 | 阻断条件 | 操作员处置 |
| --- | --- | --- |
| `access_requests.0009` | 旧申请表非空 | 先导出申请、审批人和目标权限/授权组，按当前申请幂等契约显式重建或人工关闭，再重新迁移。 |
| `applications.0012` | 审批规则同一目标重复 | 人工合并重复规则，明确保留的审批人集合和审计说明，再重新迁移。 |
| `grants.0005` | 旧授权表非空 | 先导出授权、成员权限和授权组，按当前成员级期限契约显式重建授权事实，再重新迁移。 |
| `grants.0003` | `(user, app, version)` 重复 | 人工确定真实授权版本序列；不得在迁移中重编号。 |
| `accounts.0007` | 任一本地管理员存在 TOTP 种子 | 通过运维流程通知管理员重新绑定二次验证；迁移前必须显式清除旧明文种子并记录处置。 |
| `accounts.0013` | DingTalk 用户状态不在 `active/disabled/departed` | 回到目录同步事实修正状态来源；不得把未知状态降级为禁用。 |
| `applications.0015` | IntegrationSettings 存在 Authentik token | 通过运维流程重新录入 Authentik 管理凭据；迁移前必须显式清除旧明文 token 并记录处置。 |
| `applications.0025` | 已启用 App capability 且存在 active credential | 由 App owner 对每条 credential 显式授权 capability；迁移不代替授权决策。 |

## 全量扫描结论

复查 `src/easyauth/*/migrations/*.py` 中的 `.delete()`、`.update()`、`bulk_create()`、
`get_or_create()` 和 `update_or_create()` 后，当前仍保留的写入属于确定性结构迁移或已有
fail-fast 数据保持迁移：

- 角色到授权组、申请审批人关系等 `bulk_create()` 是从旧字段到新关系表的确定性复制，缺少目标
  行时会失败，不删除旧事实后再猜测。
- 通知通道历史绑定只在目录作用域唯一或通道完整时执行；否则迁移失败。逆迁移只处理迁移创建的
  通道，不作为上线升级路径的数据清理手段。
- 目录身份绑定形状、托管范围策略、跨 App 关系和状态机迁移已有只读扫描，坏数据时失败。
- `applications.0027` 只在全库目录 scope 唯一时为通知通道补充 scope；不唯一且有通道时失败。

## 验收要求

- 空库 SQLite 完整迁移必须通过。
- PostgreSQL 16 lane 必须执行同一空库完整迁移回放。
- 携带旧试点快照升级时，不允许出现破坏业务事实的 `delete()`、批量 `update(secret="")`、
  默认值回填、自动重编号、未知状态降级、自动凭据授权或读取时兼容转换。
- 迁移失败后原始行仍保留在失败前的历史 schema 中，由操作员使用独立、显式、可审计流程处置。
