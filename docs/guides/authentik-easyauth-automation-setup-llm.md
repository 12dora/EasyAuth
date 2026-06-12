# Authentik 接入 EasyAuth 自动化配置指南

## 状态

试点联调自动化指南。

## 适用读者

本文面向 LLM 执行代理、运维脚本和自动化配置工具。允许使用 Authentik API、容器 shell、Django shell、HTTP 探测和幂等脚本。执行过程不得把 `client_secret`、API token、DingTalk secret 或原始用户敏感资料写入文档、日志摘要或测试快照。

## 官方文档依据

- Authentik Application 与 Provider：<https://docs.goauthentik.io/add-secure-apps/applications/manage_apps/>
- Authentik OAuth2/OIDC Provider：<https://docs.goauthentik.io/add-secure-apps/providers/oauth2/>
- Authentik Provider Property Mapping：<https://docs.goauthentik.io/add-secure-apps/providers/property-mappings/>
- Authentik OAuth Source：<https://docs.goauthentik.io/users-sources/sources/protocols/oauth/>
- Authentik Group 管理：<https://docs.goauthentik.io/users-sources/groups/manage_groups/>
- Authentik Binding 语义：<https://docs.goauthentik.io/add-secure-apps/bindings-overview/>
- Authentik 反向代理要求：<https://docs.goauthentik.io/install-config/reverse-proxy/>

## 目标状态

自动化执行完成后，应满足：

1. Authentik 有 DingTalk Source，slug 为 `dingtalk`。
2. Authentik 有 `EasyAuth Admins` group。
3. Authentik 有 OAuth2/OIDC Provider，client id 为 `easyauth-portal`。
4. Authentik 有 Application，slug 为 `easyauth`，名称为 `EasyAuth Portal`。
5. EasyAuth Provider 允许 `https://easyauth.example.com/auth/callback/` 或本地等价回调。
6. EasyAuth Provider 绑定 `openid`、`profile`、`email`、`easyauth_org` 和可选 `dingtalk` scope mapping。
7. `easyauth_org` mapping 返回 `groups` 和 `dingtalk_org`。
8. EasyAuth 运行配置指向该 Provider，并请求 `openid profile email dingtalk easyauth_org`。
9. 不通过 Authentik Application Binding 表达 EasyAuth 系统管理员。

## 不变量

- Authentik 是登录身份和 OIDC subject 来源。
- EasyAuth 是业务授权事实来源。
- DingTalk 只提供登录源和审批链路。
- EasyAuth 系统管理员来自 OIDC `groups` claim 与 `EASYAUTH_CONSOLE_SUPERUSER_GROUPS` 的交集。
- EasyAuth App owner 和 developer 来自 EasyAuth 本地 `AppMembership`。
- Authentik Application `Policy / Group / User Bindings` 只限制 Application 访问和可见性，不自动成为 EasyAuth 管理员。

## 输入参数

自动化执行必须显式接收或自行发现：

```text
AUTHENTIK_BASE_URL=https://auth.example.com
EASYAUTH_BASE_URL=https://easyauth.example.com
EASYAUTH_CALLBACK=https://easyauth.example.com/auth/callback/
EASYAUTH_APPLICATION_SLUG=easyauth
EASYAUTH_APPLICATION_NAME=EasyAuth Portal
EASYAUTH_CLIENT_ID=easyauth-portal
EASYAUTH_ADMIN_GROUP=EasyAuth Admins
DINGTALK_SOURCE_SLUG=dingtalk
DINGTALK_SOURCE_NAME=钉钉登录
DINGTALK_CLIENT_ID=<钉钉应用 client id>
DINGTALK_CLIENT_SECRET=<钉钉应用 secret>
```

本地联调可替换为：

```text
AUTHENTIK_BASE_URL=http://localhost:19000
EASYAUTH_BASE_URL=http://localhost:8001
EASYAUTH_CALLBACK=http://localhost:8001/auth/callback/
```

钉钉真实登录仍需要公网 Authentik 域名。

## 发现运行实例

如果运行在本项目 Docker 环境，优先发现容器：

```bash
docker ps --format '{{.Names}}\t{{.Ports}}\t{{.Status}}' | grep authentik
```

预期至少存在：

```text
easyauth-authentik-server-1
easyauth-authentik-worker-1
```

如需进入 Authentik Django shell：

```bash
docker exec easyauth-authentik-server-1 ak shell
```

如果使用 API，优先使用 Authentik 管理员 API token，并通过 `Authorization: Bearer <token>` 访问 `/api/v3/`。

## 幂等配置 Authentik 对象

### 创建或复用管理员组

目标：

```text
Group.name = EasyAuth Admins
```

Django shell 参考逻辑：

```python
from authentik.core.models import Group

group, created = Group.objects.get_or_create(
    name="EasyAuth Admins",
    defaults={
        "is_superuser": False,
    },
)
if group.is_superuser:
    group.is_superuser = False
    group.save(update_fields=["is_superuser"])
```

不要让 `EasyAuth Admins` 成为 Authentik 自身超级管理员组，除非安全负责人明确要求。

### 创建或复用 DingTalk Source

目标：

```text
source.slug = dingtalk
source.name = 钉钉登录
source.enabled = True
```

自动化代理应优先使用运行实例支持的 DingTalk Source 模型或 API schema。若当前 Authentik 镜像没有 DingTalk Source 类型，应停止并报告镜像能力不匹配，不要退化为 Generic OAuth Source 后静默丢失钉钉目录能力。

配置时必须写入：

```text
client_id = DINGTALK_CLIENT_ID
client_secret = DINGTALK_CLIENT_SECRET
scopes = openid corpid Contact.User.Read
```

不得输出 secret。

### 确认登录 Flow 展示 DingTalk Source

目标：

1. 默认 authentication flow 的 Identification stage 包含 DingTalk Source。
2. 浏览器访问 Authentik 登录页能看到钉钉登录入口。

如果通过 API 或 shell 修改 Identification stage，必须保留已有 Source，不得覆盖其它登录源。

### 创建或复用 `easyauth_org` Scope Mapping

目标：

```text
name = EasyAuth DingTalk organization context
scope_name = easyauth_org
```

Expression：

```python
from authentik.sources.oauth.dingtalk.selectors import get_dingtalk_org_context

return {
    "groups": [group.name for group in request.user.groups.all()],
    "dingtalk_org": get_dingtalk_org_context(request.user, source_slug="dingtalk"),
}
```

当前运行库若使用 `request.user.ak_groups` 或其它历史关系名，应以实际 Authentik 版本模型为准。已知当前 2026.8 运行实例使用 `request.user.groups.all()`。

### 可选创建 `dingtalk` Scope Mapping

目标：

```text
name = EasyAuth DingTalk profile claims
scope_name = dingtalk
```

Expression：

```python
dingtalk = request.user.attributes.get("dingtalk", {}) or {}

claims = {
    "dingtalk_user_id": dingtalk.get("user_id"),
    "dingtalk_union_id": dingtalk.get("union_id"),
    "dingtalk_corp_id": dingtalk.get("corp_id"),
    "department_ids": dingtalk.get("dept_id_list") or [],
}

return {key: value for key, value in claims.items() if value not in (None, "", [], {})}
```

不要默认返回手机号、邮箱或 `raw_profile`，除非已有数据最小化评审。

### 创建或复用 OAuth2/OIDC Provider

目标字段：

```text
name = EasyAuth Portal OIDC
client_id = easyauth-portal
client_type = confidential
redirect_uris 包含 EASYAUTH_CALLBACK
property_mappings 包含 openid、profile、email、easyauth_org 和可选 dingtalk
signing_key 使用非空证书，便于 EasyAuth 通过 JWKS 和 RS256 验签
```

若已存在 Provider：

1. 不轮换 client secret，除非明确要求。
2. 只追加缺失的 redirect URI。
3. 只追加缺失的 scope mapping。
4. 不删除未知 mapping。

### 创建或复用 Application

目标字段：

```text
name = EasyAuth Portal
slug = easyauth
provider = EasyAuth Portal OIDC
launch_url = https://easyauth.example.com/console/
```

若已经存在同 slug Application，只更新缺失或错误字段。不要删除 Application。

### Application Binding 策略

默认不创建 Application Binding。

如业务要求限制谁能打开 EasyAuth Portal，可绑定普通访问组：

```text
EasyAuth Users
```

不要把 `EasyAuth Admins` 当作唯一 Application Binding，除非明确要求只有系统管理员能打开 EasyAuth。EasyAuth 员工门户和控制台共用登录链路，过窄的 Application Binding 会阻断普通员工入口。

## 写入 EasyAuth 运行配置

目标环境变量：

```bash
export EASYAUTH_AUTHENTIK_OIDC_ISSUER="${AUTHENTIK_BASE_URL}/application/o/easyauth/"
export EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT="${AUTHENTIK_BASE_URL}/application/o/authorize/"
export EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT="${AUTHENTIK_BASE_URL}/application/o/token/"
export EASYAUTH_AUTHENTIK_OIDC_JWKS_URL="${AUTHENTIK_BASE_URL}/application/o/easyauth/jwks/"
export EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID="easyauth-portal"
export EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET="<provider-client-secret>"
export EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI="${EASYAUTH_CALLBACK}"
export EASYAUTH_AUTHENTIK_OIDC_SCOPES="openid profile email dingtalk easyauth_org"
export EASYAUTH_CONSOLE_SUPERUSER_GROUPS="EasyAuth Admins"
```

自动化配置 Authentik Provider 时，Redirect URIs 至少要包含：

```text
${EASYAUTH_BASE_URL}/auth/callback/
```

EasyAuth 登出只清理本地会话并跳转到本地 `/auth/logged-out/` 页面，因此自动化配置不需要额外的 Authentik 登出配置。

如需目录 API：

```bash
export EASYAUTH_AUTHENTIK_BASE_URL="${AUTHENTIK_BASE_URL}"
export EASYAUTH_AUTHENTIK_DINGTALK_SOURCE_SLUG="dingtalk"
export EASYAUTH_AUTHENTIK_API_TOKEN="<authentik-api-token>"
```

不得在提交中保存 secret 或 token。

## 反向代理自动化检查

对公网 Authentik 发起探测，确认生成的 DingTalk `redirect_uri` 使用公网 HTTPS 域名。

示例：

```bash
curl -I "${AUTHENTIK_BASE_URL}/source/oauth/login/dingtalk/"
```

检查 `Location` 中的 `redirect_uri` 应为：

```text
https://auth.example.com/source/oauth/callback/dingtalk/
```

如果出现以下任一情况，必须修复反向代理或入口地址：

```text
http://localhost:19000/source/oauth/callback/dingtalk/
http://127.0.0.1:19000/source/oauth/callback/dingtalk/
http://auth.example.com/source/oauth/callback/dingtalk/
```

反向代理必须传递：

```text
Host
X-Forwarded-Proto
X-Forwarded-For
```

## 验收探测

### OIDC discovery

```bash
curl -fsS "${AUTHENTIK_BASE_URL}/application/o/easyauth/.well-known/openid-configuration"
```

必须包含：

```text
issuer = ${AUTHENTIK_BASE_URL}/application/o/easyauth/
authorization_endpoint = ${AUTHENTIK_BASE_URL}/application/o/authorize/
token_endpoint = ${AUTHENTIK_BASE_URL}/application/o/token/
jwks_uri = ${AUTHENTIK_BASE_URL}/application/o/easyauth/jwks/
```

### JWKS

```bash
curl -fsS "${AUTHENTIK_BASE_URL}/application/o/easyauth/jwks/"
```

必须返回至少一个可用 signing key。

### EasyAuth 登录跳转

```bash
curl -I "${EASYAUTH_BASE_URL}/auth/login/?next=/console/"
```

`Location` 必须指向：

```text
${AUTHENTIK_BASE_URL}/application/o/authorize/
```

并包含：

```text
client_id=easyauth-portal
redirect_uri=<EASYAUTH_CALLBACK URL encoded>
scope=openid+profile+email+dingtalk+easyauth_org
```

### Authentik DingTalk redirect URI

```bash
curl -I "${AUTHENTIK_BASE_URL}/source/oauth/login/dingtalk/"
```

`Location` 必须跳向 DingTalk，且其中 `redirect_uri` 解码后必须是：

```text
${AUTHENTIK_BASE_URL}/source/oauth/callback/dingtalk/
```

### 管理员组 claim

使用测试用户完成登录后，确认：

1. Authentik 用户属于 `EasyAuth Admins`。
2. OIDC token 或 EasyAuth session 中有 `groups`。
3. `groups` 包含 `EasyAuth Admins`。
4. EasyAuth `/console/` 允许执行系统管理员动作。

不要把 ID token 或 access token 明文写入日志。

## 回滚策略

1. 从 EasyAuth 运行配置恢复旧 OIDC 配置。
2. 在 Authentik Application 中移除新建 Application 或断开 Provider 关联。
3. 保留 `EasyAuth Admins` group，除非确认没有其它环境使用。
4. 不删除用户、DingTalk Source 或已有 Flow。
5. 如轮换过 client secret，应记录 secret 版本和生效时间，但不得记录 secret 明文。

## 常见失败定位

### 钉钉 `redirect_uri` 参数错误

判断：

```bash
curl -I "${AUTHENTIK_BASE_URL}/source/oauth/login/dingtalk/"
```

如果 `redirect_uri` 不是公网 HTTPS Authentik callback，则问题在 Authentik 入口地址或反向代理，不在 EasyAuth OIDC callback。

### Authentik 报 redirect URI 不匹配

判断：

1. EasyAuth `/auth/login/` 发出的 `redirect_uri`。
2. Authentik Provider `redirect_uris`。

两者必须逐字匹配，包括协议、host、端口和尾部斜杠。

### 登录成功但 EasyAuth 不是系统管理员

检查：

1. 用户是否属于 Authentik `EasyAuth Admins` group。
2. Provider 是否绑定 `easyauth_org` scope mapping。
3. EasyAuth 请求 scope 是否包含 `easyauth_org`。
4. `easyauth_org` mapping 是否返回 `groups`。
5. EasyAuth `EASYAUTH_CONSOLE_SUPERUSER_GROUPS` 是否包含 `EasyAuth Admins`。

### Application Binding 已绑定但 EasyAuth 不认管理员

这是预期行为。Application Binding 不是 EasyAuth 管理员来源。若需要让 EasyAuth 识别，必须让 OIDC claim 返回 `groups`，并让用户属于 `EasyAuth Admins`。
