# EasyAuth 员工门户 React 私有 API

## 范围

本页记录员工门户 React 页面使用的同源私有 API。接口依赖 Django session 识别当前员工，不接受请求体传入 requester 身份。

## GET /portal/api/v1/request-catalog

用途：返回员工提交授权申请时可选择的应用和角色目录。

鉴权：必须存在有效 `AUTHENTIK_SESSION_KEY`，且绑定的 `UserMirror` 状态为 active。未登录或绑定用户失效时返回 `401 AUTHENTICATION_FAILED`。

筛选规则：

- `apps` 只返回 active App，且至少包含一个可申请角色。
- `roles` 只返回所属 App active、自身 active、`requestable=true`、并且存在 active 审批规则的角色。
- 不返回 inactive App、inactive Role、不可申请 Role、缺少 active 审批规则的 Role。

成功响应：

```json
{
  "apps": [
    {
      "id": 1,
      "app_key": "crm",
      "name": "CRM",
      "description": "客户管理系统"
    }
  ],
  "roles": [
    {
      "id": 10,
      "app_key": "crm",
      "key": "auditor",
      "name": "审计员",
      "description": "查看审计数据",
      "requestable": true,
      "requires_approval": true
    }
  ]
}
```

兼容性：

- 该接口是门户页面私有接口，不改变公共 `/api/v1/apps/{app_key}/users/{user_id}/permissions` 授权查询契约。
- 旧版 `/portal/` 表单 POST 仍保留，用于兼容未迁移的提交路径；React 页面应优先使用 `/portal/api/v1/me/access-requests`。
