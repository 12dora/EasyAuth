# Authentik 接入 EasyAuth 人工 UI 配置指南

## 状态

试点联调指南。

## 适用读者

本文面向只能使用 Authentik、DingTalk 和 EasyAuth 可视化界面的实施人员。本文不要求执行 API、数据库 shell、容器 shell 或脚本。

## 官方文档依据

- Authentik Application 与 Provider 创建：<https://docs.goauthentik.io/add-secure-apps/applications/manage_apps/>
- Authentik OAuth2/OIDC Provider：<https://docs.goauthentik.io/add-secure-apps/providers/oauth2/>
- Authentik Single Logout：<https://docs.goauthentik.io/add-secure-apps/providers/single-logout/>
- Authentik User Logout Stage：<https://docs.goauthentik.io/add-secure-apps/flows-stages/stages/user_logout/>
- Authentik Brands：<https://docs.goauthentik.io/brands/>
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
8. 点击 EasyAuth 登出后，同时清理 EasyAuth 本地 session 和 Authentik 浏览器登录态。

## 前置地址

生产或试点公网环境建议使用：

```text
Authentik 外部地址：https://auth.example.com
EasyAuth 外部地址：https://easyauth.example.com
EasyAuth OIDC 回调：https://easyauth.example.com/auth/callback/
EasyAuth 登出回落页：https://easyauth.example.com/auth/logged-out/?next=%2Fportal%2F
Authentik DingTalk Source 回调：https://auth.example.com/source/oauth/callback/dingtalk/
```

本地只验证 Authentik 到 EasyAuth 的 OIDC 回调时可以使用：

```text
Authentik 本地地址：http://localhost:19000
EasyAuth 本地地址：http://localhost:8001
EasyAuth OIDC 回调：http://localhost:8001/auth/callback/
EasyAuth 本地登出回落页：http://localhost:8001/auth/logged-out/?next=%2Fportal%2F
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
Redirect URIs：
  authorization：https://easyauth.example.com/auth/callback/
  logout：https://easyauth.example.com/auth/logged-out/?next=%2Fportal%2F
Invalidation flow：default-provider-invalidation-flow
```

本地调试时可使用：

```text
Redirect URIs：
  authorization：http://localhost:8001/auth/callback/
  logout：http://localhost:8001/auth/logged-out/?next=%2Fportal%2F
```

如果浏览器可能使用 `127.0.0.1`，额外加入：

```text
authorization：http://127.0.0.1:8001/auth/callback/
logout：http://127.0.0.1:8001/auth/logged-out/?next=%2Fportal%2F
```

EasyAuth 登出会先清理本地会话，再跳转到 Authentik Provider 的 End Session 入口：

```text
https://auth.example.com/application/o/easyauth/end-session/
```

如果 EasyAuth 配置了 `post_logout_redirect_uri`，Authentik Provider 必须登记完全一致的 `logout` 类型 Redirect URI。不要把 EasyAuth 登出入口配置成 `/if/flow/default-invalidation-flow/`，该地址不是 OIDC RP-Initiated Logout 入口。

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
7. 保存 Provider。

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

## 配置 Authentik Provider 登出清理

1. 进入 `Flows and Stages` -> `Flows`。
2. 打开 `default-provider-invalidation-flow`。
3. 查看 `Stage Bindings`。
4. 确认已绑定 `default-invalidation-logout`。
5. 如果没有该绑定，点击 `Bind existing stage`，选择：

```text
Stage：default-invalidation-logout
Order：0
```

6. 如果没有 `default-invalidation-logout` stage，进入 `Flows and Stages` -> `Stages`，创建 `User Logout Stage`，名称填写 `default-invalidation-logout`，再回到上一步绑定。

这一步使用的是 Authentik 现有的 Provider invalidation flow。EasyAuth 不直接跳转到 `default-invalidation-flow`，而是跳转到 Provider End Session；End Session 再执行 `default-provider-invalidation-flow`，由 `User Logout Stage` 清理 Authentik 浏览器登录态。

## 配置 Authentik Brand 默认应用

1. 进入 `System` -> `Brands`。
2. 打开当前访问域名使用的 Brand。默认安装通常是 `authentik-default`。
3. 将 `Default application` 设置为 `EasyAuth Portal`。
4. 保存。

这一步用于外部用户完成钉钉登录后回到 EasyAuth。如果没有设置，外部用户可能被送到 Authentik 内部界面，并看到：

```text
Permission denied
Request has been denied.
Interface can only be accessed by internal users.
```

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

登出链路需要 Authentik Provider End Session 可用。EasyAuth 默认会从 Issuer 推导该地址：

```text
https://auth.example.com/application/o/easyauth/end-session/
```

通常不需要显式配置 `EASYAUTH_AUTHENTIK_LOGOUT_URL`。如果 Authentik 使用了非标准 Provider slug，或反向代理改写了路径，请在 EasyAuth 运行配置中显式填写：

```text
EASYAUTH_AUTHENTIK_LOGOUT_URL=https://auth.example.com/application/o/easyauth/end-session/
```

如果希望 Authentik End Session 完成后自动回到 EasyAuth 已登出页，还需要同时满足两点：

1. Authentik Provider 已登记完全一致的 `logout` 类型 Redirect URI。
2. EasyAuth 运行配置中填写：

```text
EASYAUTH_AUTHENTIK_POST_LOGOUT_REDIRECT_URI=https://easyauth.example.com/auth/logged-out/?next=%2Fportal%2F
```

点击 EasyAuth 的 logout 后会清理本地 session，并跳转到 Authentik Provider End Session。EasyAuth 会带上本次 OIDC 登录拿到的 `id_token_hint`；只有配置了 `EASYAUTH_AUTHENTIK_POST_LOGOUT_REDIRECT_URI` 且 Authentik 已登记对应 `logout` Redirect URI 时，才会附带 `post_logout_redirect_uri`。

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
9. 点击 EasyAuth 登出。
10. 浏览器应进入 Authentik End Session 或 EasyAuth 已登出页。
11. 再点击钉钉登录时，应重新进入 Authentik/DingTalk 登录流程，而不是直接回到 EasyAuth。

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

### 登出跳转到 Authentik 后提示 Bad Request

通常是 EasyAuth 配置了 `EASYAUTH_AUTHENTIK_POST_LOGOUT_REDIRECT_URI`，但 Authentik Provider 没有登记完全一致的 `logout` 类型 Redirect URI。

处理：

1. 在 Provider Redirect URIs 中添加 `logout` 类型：

```text
https://easyauth.example.com/auth/logged-out/?next=%2Fportal%2F
```

2. 确认 EasyAuth 运行配置里的 `EASYAUTH_AUTHENTIK_POST_LOGOUT_REDIRECT_URI` 与 Authentik 中的值逐字一致。
3. 如果暂时无法登记 logout Redirect URI，先移除 EasyAuth 里的 `EASYAUTH_AUTHENTIK_POST_LOGOUT_REDIRECT_URI`。EasyAuth 仍会跳 End Session，但不会附带 `post_logout_redirect_uri`。

### 钉钉登录后提示只能内部用户访问

错误形如：

```text
Permission denied
Request has been denied.
Interface can only be accessed by internal users.
```

原因通常是外部用户登录 Authentik 后被送到了 Authentik 内部界面，而不是 EasyAuth Application。

处理：进入 `System` -> `Brands`，将当前 Brand 的 `Default application` 设置为 `EasyAuth Portal`。
