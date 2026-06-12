# Authentik 接入 EasyAuth 人工 UI 配置指南

## 状态

试点联调指南。

## 适用读者

本文面向只能使用 Authentik、DingTalk 和 EasyAuth 可视化界面的实施人员。本文不要求执行 API、数据库 shell、容器 shell 或脚本。

## 官方文档依据

- Authentik Application 与 Provider 创建：<https://docs.goauthentik.io/add-secure-apps/applications/manage_apps/>
- Authentik OAuth2/OIDC Provider：<https://docs.goauthentik.io/add-secure-apps/providers/oauth2/>
- Authentik Provider Property Mapping：<https://docs.goauthentik.io/add-secure-apps/providers/property-mappings/>
- Authentik OAuth Source：<https://docs.goauthentik.io/users-sources/sources/protocols/oauth/>
- Authentik Group 管理：<https://docs.goauthentik.io/users-sources/groups/manage_groups/>
- Authentik Binding 语义：<https://docs.goauthentik.io/add-secure-apps/bindings-overview/>
- Authentik 反向代理要求：<https://docs.goauthentik.io/install-config/reverse-proxy/>

## 目标

完成以下闭环：

1. 员工打开 EasyAuth。
2. EasyAuth 跳转到 Authentik。
3. Authentik 使用钉钉 Source 完成登录。
4. Authentik 通过 OIDC 回调 EasyAuth。
5. EasyAuth 使用 Authentik `sub` 建立会话。
6. EasyAuth 根据 OIDC `groups` claim 判断系统管理员。
7. EasyAuth 根据本地 `AppMembership` 判断业务 App 的 owner 和 developer。

## 前置地址

生产或试点公网环境建议使用：

```text
Authentik 外部地址：https://auth.example.com
EasyAuth 外部地址：https://easyauth.example.com
EasyAuth OIDC 回调：https://easyauth.example.com/auth/callback/
Authentik DingTalk Source 回调：https://auth.example.com/source/oauth/callback/dingtalk/
```

本地只验证 Authentik 到 EasyAuth 的 OIDC 回调时可以使用：

```text
Authentik 本地地址：http://localhost:19000
EasyAuth 本地地址：http://localhost:8001
EasyAuth OIDC 回调：http://localhost:8001/auth/callback/
```

钉钉真实登录不能完整依赖 `localhost`。钉钉开放平台需要能回调公网 Authentik 域名。

## 配置钉钉开放平台

1. 打开钉钉开放平台。
2. 进入目标应用。
3. 进入「应用开发」->「登录与分享」。
4. 配置回调域名为 Authentik 外部域名，例如：

```text
auth.example.com
```

不要填写 EasyAuth 域名，也不要填写 `localhost`。

钉钉回调的是 Authentik Source，完整回调地址形如：

```text
https://auth.example.com/source/oauth/callback/dingtalk/
```

## 在 Authentik 配置 DingTalk Source

1. 使用管理员登录 Authentik。
2. 打开 Admin interface。
3. 进入 `Directory` -> `Federation and Social login`。不同版本也可能显示为 `Directory` -> `Sources`。
4. 创建新的 OAuth Source，类型选择 DingTalk。
5. 填写：

```text
Name：钉钉登录
Slug：dingtalk
Client ID：钉钉应用的 AppKey 或 Client ID
Client Secret：钉钉应用密钥
Scopes：openid corpid Contact.User.Read
Enabled：开启
```

6. 保存 Source。
7. 进入 `Flows and Stages` -> `Stages`。
8. 找到默认登录 flow 使用的 Identification stage。
9. 在该 Identification stage 的 Sources 中加入 `钉钉登录`。
10. 保存。

验收：打开 Authentik 默认登录页时，应能看到钉钉登录入口。

## 创建 EasyAuth 管理员组

1. 进入 `Directory` -> `Groups`。
2. 点击 `Create`。
3. 填写：

```text
Name：EasyAuth Admins
Superuser status：不勾选
```

4. 保存。
5. 打开 `EasyAuth Admins` 组详情。
6. 将需要成为 EasyAuth 系统管理员的用户加入该组。

`EasyAuth Admins` 是 EasyAuth 控制台系统管理员来源。它不需要成为 Authentik 自身的超级管理员组。

## 创建 EasyAuth OIDC Scope Mapping

1. 进入 `Customization` -> `Property Mappings`。
2. 点击 `Create`。
3. 选择 OAuth2/OIDC Scope Mapping。
4. 创建组织上下文 mapping：

```text
Name：EasyAuth organization claims
Scope name：easyauth_org
Description：EasyAuth 控制台管理员组和钉钉组织上下文
```

5. Expression 填写：

```python
from authentik.sources.oauth.dingtalk.selectors import get_dingtalk_org_context

return {
    "groups": [group.name for group in request.user.groups.all()],
    "dingtalk_org": get_dingtalk_org_context(request.user, source_slug="dingtalk"),
}
```

6. 保存。

如需给 EasyAuth 额外暴露钉钉基础字段，可再创建一个 mapping：

```text
Name：EasyAuth DingTalk claims
Scope name：dingtalk
```

Expression：

```python
dingtalk = request.user.attributes.get("dingtalk", {}) or {}

return {
    "dingtalk_user_id": dingtalk.get("user_id"),
    "dingtalk_union_id": dingtalk.get("union_id"),
    "dingtalk_corp_id": dingtalk.get("corp_id"),
    "department_ids": dingtalk.get("dept_id_list") or [],
}
```

## 创建 EasyAuth OIDC Provider

1. 进入 `Applications` -> `Providers`。
2. 点击 `Create`。
3. 选择 `OAuth2/OpenID Provider`。
4. 填写：

```text
Name：EasyAuth Portal OIDC
Authorization flow：default-authentication-flow
Client type：Confidential
Client ID：easyauth-portal
Client Secret：自动生成，并记录给 EasyAuth 运维配置使用
Redirect URIs：https://easyauth.example.com/auth/callback/
```

本地调试时可使用：

```text
Redirect URIs：http://localhost:8001/auth/callback/
```

如果浏览器可能使用 `127.0.0.1`，额外加入：

```text
http://127.0.0.1:8001/auth/callback/
```

EasyAuth 登出只清理本地会话并进入本地 `/auth/logged-out/` 页面，因此 Provider Redirect URIs 只需要登记 OIDC callback 地址。

5. 在 Property mappings 或 Scope mappings 中选择：

```text
openid
profile
email
easyauth_org
dingtalk
```

其中 `dingtalk` 可选，`easyauth_org` 必须包含 `groups`，否则 EasyAuth 无法用 Authentik 组判断系统管理员。

6. Signing Key 建议选择 Authentik 默认签名证书，让 EasyAuth 使用 JWKS 和 `RS256` 验签。
7. 如果需要从 EasyAuth 登出时同时结束 authentik 主会话，打开 Provider 使用的 provider invalidation flow，确认其中包含 `User Logout` stage。authentik 默认的 `default-provider-invalidation-flow` 不包含该 stage。
8. 保存 Provider。

## 创建 EasyAuth Application

1. 进入 `Applications` -> `Applications`。
2. 点击 `Create` 或 `New Application`。
3. 填写：

```text
Name：EasyAuth Portal
Slug：easyauth
Provider：EasyAuth Portal OIDC
Launch URL：https://easyauth.example.com/console/
```

本地调试时使用：

```text
Launch URL：http://localhost:8001/console/
```

4. 保存。

## 可选：限制谁能打开 EasyAuth Portal

Authentik Application 的 `Policy / Group / User Bindings` 只控制谁能看见或启动这个 Authentik Application。它不会让 EasyAuth 判定用户为系统管理员。

如果要限制谁能打开 EasyAuth Portal：

1. 进入 `Applications` -> `Applications`。
2. 打开 `EasyAuth Portal`。
3. 打开 `Policy / Group / User Bindings`。
4. 点击 `Create or bind...`。
5. 选择 `Bind an existing group`。
6. 绑定普通访问组，例如：

```text
EasyAuth Users
```

不要只绑定 `EasyAuth Admins`，否则普通员工无法进入 EasyAuth 员工门户。

## 在 EasyAuth 管理界面或运行配置中填写 OIDC 参数

如果 EasyAuth 当前部署提供配置界面，应填写：

```text
Issuer：https://auth.example.com/application/o/easyauth/
Authorization endpoint：https://auth.example.com/application/o/authorize/
Token endpoint：https://auth.example.com/application/o/token/
JWKS URL：https://auth.example.com/application/o/easyauth/jwks/
Client ID：easyauth-portal
Client Secret：EasyAuth Portal OIDC Provider 中生成的 secret
Redirect URI：https://easyauth.example.com/auth/callback/
Scopes：openid profile email dingtalk easyauth_org
Console superuser groups：EasyAuth Admins
```

登出链路不需要额外的 Authentik 登出配置。点击 EasyAuth 的 logout 后会清理本地 session 并跳转到本地登出页。

如果当前 EasyAuth 版本没有 UI 配置入口，这些值需要由运维写入 EasyAuth 运行配置。该限制属于 EasyAuth 当前实现，不属于 Authentik UI 可配置范围。

## 反向代理检查

如果 Authentik 在反向代理后面，确认代理保留以下请求头：

```text
Host
X-Forwarded-Proto
X-Forwarded-For
```

如果缺少 `Host` 或 `X-Forwarded-Proto`，Authentik 可能向钉钉生成错误的 `redirect_uri`，例如 `http://localhost:19000/source/oauth/callback/dingtalk/`。

## 端到端验收

1. 打开：

```text
https://easyauth.example.com/console/
```

2. EasyAuth 跳转到 Authentik。
3. Authentik 登录页显示 `钉钉登录`。
4. 点击钉钉登录并完成认证。
5. Authentik 回调 EasyAuth：

```text
https://easyauth.example.com/auth/callback/
```

6. EasyAuth 进入 `/console/`。
7. `EasyAuth Admins` 成员应获得 EasyAuth 系统管理员能力。
8. 非 `EasyAuth Admins` 用户只按 EasyAuth 本地 `AppMembership` 获得对应 App 的 owner 或 developer 能力。

## 常见错误

### 钉钉提示 redirect_uri 参数错误

原因通常是 Authentik 当前访问地址不是公网域名，或反向代理没有传递正确的 `Host` 和 `X-Forwarded-Proto`。

处理：

1. 浏览器必须从 `https://auth.example.com` 进入 Authentik，而不是 `http://localhost:19000`。
2. 钉钉开放平台回调域名必须配置 `auth.example.com`。
3. 反向代理必须把原始域名和协议传给 Authentik。

### 登录成功但不是 EasyAuth 系统管理员

检查：

1. 用户是否在 `Directory` -> `Groups` -> `EasyAuth Admins`。
2. EasyAuth OIDC Provider 是否包含 `easyauth_org` scope mapping。
3. EasyAuth 请求的 scope 是否包含 `easyauth_org`。
4. `easyauth_org` mapping 是否返回 `groups`。

### Application Binding 配了但 EasyAuth 不认管理员

这是预期行为。Application Binding 只限制 Authentik Application 访问；EasyAuth 系统管理员来自 OIDC `groups` claim 中的 `EasyAuth Admins`。
