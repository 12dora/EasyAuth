# Authentik 控制台身份与钉钉组织联调实施计划

> **给执行代理：** 必须使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 逐项执行。执行前必须再次读取本文件和 `AGENTS.md`；步骤使用 checkbox 语法跟踪。

**目标：** 将 EasyAuth 管理控制台身份统一到 Authentik，并让 EasyAuth 能从已运行的 Authentik 获取钉钉组织架构、主管链和通讯录信息。

**架构：** EasyAuth 继续把 Authentik `sub` 作为统一用户标识。控制台、员工门户共用 Authentik OIDC 登录和 `AUTHENTIK_SESSION_KEY`；控制台权限仍由 EasyAuth 的 `AppMembership` 和 Authentik group 映射控制。钉钉组织数据不由 EasyTrade 传入，EasyAuth 通过 Authentik OIDC claim 获取当前用户组织上下文，并通过 Authentik 目录 API 获取完整组织架构、主管链和通讯录快照。

**技术栈：** Django 5.2、Django session、OIDC/JWKS、DRF、Celery、PostgreSQL、pytest、运行中的 Authentik Docker 服务。

---

## 已确认事实

- EasyAuth 员工门户已使用 Authentik OIDC，会话键为 `AUTHENTIK_SESSION_KEY`，实现位于 `/Users/konata/code/EasyAuth/src/easyauth/accounts/auth.py` 和 `/Users/konata/code/EasyAuth/src/easyauth/accounts/views.py`。
- EasyAuth 管理控制台当前仍依赖 Django `request.user`、`is_superuser` 和 `/admin/login/`，主要入口在 `/Users/konata/code/EasyAuth/src/easyauth/admin_console/views.py`、`request_guards.py`、`authz.py`。
- `UserMirror` 已有 `department`、`dingtalk_union_id`、`dingtalk_userid`、`dingtalk_corp_id`、`employee_number`、`manager_userid` 字段，可继续承载当前用户摘要；完整部门、用户和组织上下文需要新增本地缓存模型，避免把目录能力压扁成单个 `manager_userid`。
- Authentik 已有钉钉目录缓存模型、同步任务和只读 API：
  - `GET /api/v3/sources/oauth/dingtalk-directory/<source_slug>/status/`
  - `POST /api/v3/sources/oauth/dingtalk-directory/<source_slug>/sync/`
  - `GET /api/v3/sources/oauth/dingtalk-directory/<source_slug>/departments/`
  - `GET /api/v3/sources/oauth/dingtalk-directory/<source_slug>/users/`
  - `GET /api/v3/sources/oauth/dingtalk-directory/<source_slug>/users/<corp_id>/<user_id>/org/`
- 本机 Docker 中 Authentik 服务当前暴露为 `http://localhost:19000` 和 `https://localhost:19443`，容器名包括 `easyauth-authentik-server-1`、`easyauth-authentik-worker-1`。
- 运行实例当前可发现：
  - EasyAuth OIDC Application slug 为 `easyauth`，client id 为 `easyauth-portal`，Provider 为 confidential client。
  - DingTalk source slug 为 `dingtalk`，名称为 `钉钉登录`，已启用。
  - 最近一次钉钉目录同步成功，计数为 133 个用户、39 个部门。
  - 当前已有 `EasyAuth 本地模拟员工` group；执行时需要幂等创建或确认 `EasyAuth Admins` group 作为控制台系统管理员来源。
  - 不把已发现的 client secret、bootstrap token 或 API token 写入计划、日志、健康检查或测试快照。

## 总体策略

1. 先冻结联调契约，确认运行中的 Authentik 镜像和源码一致。
2. 先统一控制台登录与 actor 解析，避免继续依赖 Django 本地用户。
3. 再接 Authentik 组织数据，OIDC `dingtalk_org` claim 更新当前用户摘要，目录 API 同步完整部门、用户和组织上下文缓存。
4. 后端目录 API 客户端只访问 Authentik，不接触钉钉 app secret；执行代理自行在 Authentik 创建 EasyAuth 专用 API token 并写入本地 EasyAuth 运行配置。
5. 控制台系统管理员统一来自 Authentik group；执行代理自行创建或复用 `EasyAuth Admins`。
6. 主管链审批规则作为后续业务语义，不在本轮静默改变审批规则含义。

---

## 文件结构规划

### EasyAuth 新增文件

- `/Users/konata/code/EasyAuth/src/easyauth/admin_console/identity.py`
  - 统一从 Authentik session 解析 `ConsoleActor`。
  - 负责系统管理员映射。
  - 兼容现有 JSON API 错误响应。

- `/Users/konata/code/EasyAuth/src/easyauth/integrations/authentik/directory_client.py`
  - Authentik 钉钉目录 API 的最小 HTTP 客户端。
  - 只读拉取 `status`、`departments`、`users`、`org`。
  - 不记录 token，不返回 raw profile。

- `/Users/konata/code/EasyAuth/src/easyauth/integrations/authentik/directory_payloads.py`
  - 用 Pydantic 或 dataclass 解析 Authentik 目录 API 返回。
  - 明确字段白名单。

- `/Users/konata/code/EasyAuth/src/easyauth/accounts/org_context.py`
  - 将 OIDC `dingtalk_org` claim 或目录 API org context 映射到 `UserMirror`。
  - 更新当前用户摘要，并把完整组织上下文交给目录缓存服务落库。

- `/Users/konata/code/EasyAuth/src/easyauth/integrations/authentik/directory_sync.py`
  - 从 Authentik 目录 API 同步完整部门列表、通讯录用户列表和用户组织上下文。
  - 幂等更新本地目录缓存。

- `/Users/konata/code/EasyAuth/src/easyauth/tasks/authentik.py`
  - 提供手动和周期性目录同步入口。
  - 不记录 token、手机号、邮箱、raw profile。

- `/Users/konata/code/EasyAuth/tests/integration/authentik/test_directory_client.py`
  - 覆盖 Authentik 目录 API 客户端、分页、403、敏感字段过滤。

- `/Users/konata/code/EasyAuth/tests/integration/auth/test_oidc_org_context.py`
  - 覆盖 OIDC claim 写入用户镜像。

- `/Users/konata/code/EasyAuth/tests/integration/authentik/test_directory_sync.py`
  - 覆盖完整部门、用户、组织上下文同步。

### EasyAuth 修改文件

- `/Users/konata/code/EasyAuth/src/easyauth/accounts/auth.py`
  - 扩展 `VerifiedOidcClaims`，支持 `groups` 和 `dingtalk_org`。
  - 增加 `next` 会话键，供控制台登录后回跳。

- `/Users/konata/code/EasyAuth/src/easyauth/accounts/views.py`
  - `/auth/login/` 支持安全 `next`。
  - `/auth/callback/` 成功后回跳原始 `next`，默认仍为 `/portal/`。

- `/Users/konata/code/EasyAuth/src/easyauth/admin_console/views.py`
  - 控制台未登录跳 `/auth/login/?next=...`。
  - `_actor_from_request` 改用 `admin_console.identity`。

- `/Users/konata/code/EasyAuth/src/easyauth/admin_console/request_guards.py`
  - `require_console_actor()` 改用 Authentik session。

- `/Users/konata/code/EasyAuth/src/easyauth/admin_console/authz.py`
  - `require_superuser()` 改用 Authentik session 和管理员映射。

- `/Users/konata/code/EasyAuth/src/easyauth/admin_console/catalog_write_common.py`
  - 不再直接读取 `request.user`。

- `/Users/konata/code/EasyAuth/src/easyauth/admin_console/permission_template_api.py`
  - 将直接使用 `request.user.get_username()` 的地方改为统一 actor。

- `/Users/konata/code/EasyAuth/src/easyauth/config/settings/base.py`
  - 增加 Authentik 目录 API 配置和控制台管理员映射配置。

- `/Users/konata/code/EasyAuth/src/easyauth/accounts/services.py`
  - 扩展 Authentik payload 同步，写入已有钉钉字段。

- `/Users/konata/code/EasyAuth/src/easyauth/accounts/models.py`
  - 增加 Authentik 钉钉目录缓存模型：
    - `DingTalkDepartmentMirror`
    - `DingTalkUserMirror`
    - `DingTalkUserOrgContext`
    - `DingTalkDirectorySyncState`
  - `UserMirror` 继续保存当前用户摘要字段，不承载完整通讯录。

- `/Users/konata/code/EasyAuth/src/easyauth/integrations/authentik/payloads.py`
  - 支持解析 `dingtalk` 和 `dingtalk_org` 白名单字段。

- `/Users/konata/code/EasyAuth/src/easyauth/applications/dependency_health.py`
  - 增加 Authentik 目录同步健康项。

---

## 阶段 0：联调契约冻结

**目的：** 在改 EasyAuth 前确认运行中的 Authentik Docker 服务确实包含钉钉目录 API、迁移和字段。

- [ ] **步骤 0.0：自行发现 Authentik 运行配置**

执行代理必须自行读取 `/Users/konata/code/Authentik` 源码和运行实例，不向用户索要以下输入：

- EasyAuth OIDC Application slug、Provider、client id、client secret、redirect URI。
- DingTalk source slug。
- 控制台系统管理员 group。
- EasyAuth 调用 Authentik 目录 API 所需 API token。

已知当前实例可作为起点：

- OIDC Application slug：`easyauth`
- OIDC client id：`easyauth-portal`
- DingTalk source slug：`dingtalk`
- 对外 HTTP 地址：`http://localhost:19000`

执行规则：

- secret/token 只能进入本地运行配置或受控 secret 存储，不得写入计划、日志、测试快照、健康检查响应。
- 如果 `EasyAuth Admins` group 不存在，执行代理需要在 Authentik 中幂等创建。
- 如果 EasyAuth 专用 API token 不存在，执行代理需要创建；如果已存在但 key 不可读取，则创建或轮换一个新的专用 token。

- [ ] **步骤 0.1：确认容器和端口**

运行：

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
```

期望：

```text
easyauth-authentik-server-1 ... 19000->9000/tcp ... healthy
easyauth-authentik-worker-1 ... healthy
```

- [ ] **步骤 0.2：确认 API 可达**

运行：

```bash
curl -i http://localhost:19000/api/v3/sources/oauth/dingtalk-directory/dingtalk/status/
```

期望：

```text
HTTP/1.1 401 Unauthorized
```

说明：401 表示路由存在但缺少认证；404 表示运行镜像没有该 API，必须先回到 Authentik 仓库处理镜像一致性。

- [ ] **步骤 0.3：自行创建或发现 API token 并验证目录状态**

执行代理在 Authentik 中创建或复用 EasyAuth 专用 API token：

- token identifier 建议为 `easyauth-directory-api`。
- token 所属用户建议为 EasyAuth 专用服务用户。
- 权限范围只覆盖读取 EasyAuth OIDC 配置、读取 group、读取钉钉目录 API 所需对象。
- 创建后的 token key 只写入 EasyAuth 本地环境变量 `EASYAUTH_AUTHENTIK_API_TOKEN` 或受控 secret 文件，不输出到终端摘要和文档。

运行：

```bash
curl -sS \
  -H "Authorization: Bearer ${EASYAUTH_AUTHENTIK_API_TOKEN}" \
  http://localhost:19000/api/v3/sources/oauth/dingtalk-directory/dingtalk/status/
```

期望返回 JSON，包含：

```json
{
  "source_slug": "dingtalk",
  "sync": []
}
```

或 `sync` 中存在 `corp_id/status/started_at/finished_at/error/counters`。

- [ ] **步骤 0.4：确认 OIDC Provider 给 EasyAuth 的 claim 合同**

在 Authentik 给 EasyAuth Provider 增加或确认 OIDC `ScopeMapping`：

```python
from authentik.sources.oauth.dingtalk.selectors import get_dingtalk_org_context

dingtalk = request.user.attributes.get("dingtalk", {})
return {
    "name": dingtalk.get("name") or dingtalk.get("nick") or request.user.name,
    "email": request.user.email,
    "groups": [group.name for group in request.user.ak_groups.all()],
    "dingtalk_user_id": dingtalk.get("user_id"),
    "dingtalk_union_id": dingtalk.get("union_id"),
    "dingtalk_corp_id": dingtalk.get("corp_id"),
    "dingtalk_org": get_dingtalk_org_context(
        request.user,
        source_slug="dingtalk",
        include_manager_chain=True,
        include_department_path=True,
    ),
}
```

验收：

- EasyAuth 所用 OIDC client 的 `scope` 包含该 mapping 对应 scope。
- `dingtalk_org` 不包含 `mobile`、`email`、`raw`。
- `groups` 可用于系统管理员映射。

---

## 阶段 1：控制台身份统一到 Authentik

### 任务 1：支持 OIDC 登录后安全回跳

**文件：**

- 修改：`/Users/konata/code/EasyAuth/src/easyauth/accounts/auth.py`
- 修改：`/Users/konata/code/EasyAuth/src/easyauth/accounts/views.py`
- 测试：`/Users/konata/code/EasyAuth/tests/integration/auth/test_oidc_session_s12.py`

- [ ] **步骤 1.1：写失败测试**

新增测试：

```python
def test_oidc_login_preserves_safe_next(client: Client, settings):
    settings.EASYAUTH_AUTHENTIK_OIDC_ISSUER = AUTHENTIK_ISSUER
    settings.EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT = AUTHORIZATION_ENDPOINT
    settings.EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID = CLIENT_ID
    settings.EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI = REDIRECT_URI
    settings.EASYAUTH_AUTHENTIK_OIDC_SCOPES = ("openid", "profile", "email")

    response = client.get("/auth/login/?next=/console/apps/crm/")

    assert response.status_code == HTTPStatus.FOUND
    assert client.session["easyauth_oidc_next"] == "/console/apps/crm/"
```

再新增不安全回跳测试：

```python
def test_oidc_login_rejects_external_next(client: Client, settings):
    settings.EASYAUTH_AUTHENTIK_OIDC_ISSUER = AUTHENTIK_ISSUER
    settings.EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT = AUTHORIZATION_ENDPOINT
    settings.EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID = CLIENT_ID
    settings.EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI = REDIRECT_URI
    settings.EASYAUTH_AUTHENTIK_OIDC_SCOPES = ("openid", "profile", "email")

    response = client.get("/auth/login/?next=https://evil.example/console/")

    assert response.status_code == HTTPStatus.FOUND
    assert client.session["easyauth_oidc_next"] == "/portal/"
```

- [ ] **步骤 1.2：运行失败测试**

运行：

```bash
.venv/bin/python -m pytest tests/integration/auth/test_oidc_session_s12.py -k "next" -vv
```

期望：失败，原因是 `easyauth_oidc_next` 尚未实现。

- [ ] **步骤 1.3：实现最小回跳能力**

在 `auth.py` 增加：

```python
OIDC_NEXT_SESSION_KEY: Final = "easyauth_oidc_next"
DEFAULT_AUTH_SUCCESS_NEXT: Final = "/portal/"
```

在 `views.py` 的 `oidc_login()` 中保存安全 next：

```python
request.session[OIDC_NEXT_SESSION_KEY] = _safe_local_next(
    request.GET.get("next", DEFAULT_AUTH_SUCCESS_NEXT),
    default=DEFAULT_AUTH_SUCCESS_NEXT,
)
```

在 `oidc_callback()` 成功后：

```python
next_path = _session_string(request, OIDC_NEXT_SESSION_KEY) or DEFAULT_AUTH_SUCCESS_NEXT
request.session.pop(OIDC_NEXT_SESSION_KEY, None)
return HttpResponseRedirect(next_path)
```

安全路径函数复用当前 dev login 的本地路径判断。

- [ ] **步骤 1.4：验证**

运行：

```bash
.venv/bin/python -m pytest tests/integration/auth/test_oidc_session_s12.py tests/integration/portal/test_session_boundary_s12.py -vv
```

期望：全部通过。

### 任务 2：新增控制台 Authentik actor 解析层

**文件：**

- 新建：`/Users/konata/code/EasyAuth/src/easyauth/admin_console/identity.py`
- 修改：`/Users/konata/code/EasyAuth/src/easyauth/config/settings/base.py`
- 测试：`/Users/konata/code/EasyAuth/tests/unit/admin_console/test_request_guards.py`

- [ ] **步骤 2.1：写失败测试**

新增测试覆盖 Authentik session：

```python
def test_require_console_actor_uses_authentik_session(rf):
    request = rf.get("/console/")
    request.user = AnonymousUser()
    request.session = {AUTHENTIK_SESSION_KEY: "ak-user-1"}
    UserMirror.objects.create(authentik_user_id="ak-user-1", status=USER_STATUS_ACTIVE)

    actor = require_console_actor(request)

    assert actor == ConsoleActor(user_id="ak-user-1", is_superuser=False)
```

新增非 active 测试：

```python
def test_require_console_actor_rejects_disabled_authentik_user(rf):
    request = rf.get("/console/")
    request.user = AnonymousUser()
    request.session = {AUTHENTIK_SESSION_KEY: "ak-user-1"}
    UserMirror.objects.create(authentik_user_id="ak-user-1", status=USER_STATUS_DISABLED)

    response = require_console_actor(request)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
```

- [ ] **步骤 2.2：实现 `identity.py`**

核心接口：

```python
def console_actor_from_request(request: HttpRequest) -> ConsoleActor | None:
    user_id = request.session.get(AUTHENTIK_SESSION_KEY)
    if not isinstance(user_id, str):
        return None
    user = UserMirror.objects.filter(
        authentik_user_id=user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if user is None:
        request.session.pop(AUTHENTIK_SESSION_KEY, None)
        return None
    return ConsoleActor(
        user_id=user.authentik_user_id,
        is_superuser=is_console_superuser(user.authentik_user_id, request),
    )
```

管理员判定：

```python
def is_console_superuser(user_id: str, request: HttpRequest) -> bool:
    configured_ids = set(getattr(settings, "EASYAUTH_CONSOLE_SUPERUSER_IDS", ()))
    if user_id in configured_ids:
        return True
    configured_groups = set(getattr(settings, "EASYAUTH_CONSOLE_SUPERUSER_GROUPS", ()))
    session_groups = set(request.session.get("easyauth_authentik_groups", ()))
    return bool(configured_groups & session_groups)
```

- [ ] **步骤 2.3：增加配置**

在 `settings/base.py` 增加：

```python
EASYAUTH_CONSOLE_SUPERUSER_IDS = tuple(
    item.strip()
    for item in os.environ.get("EASYAUTH_CONSOLE_SUPERUSER_IDS", "").split(",")
    if item.strip()
)
EASYAUTH_CONSOLE_SUPERUSER_GROUPS = tuple(
    item.strip()
    for item in os.environ.get("EASYAUTH_CONSOLE_SUPERUSER_GROUPS", "").split(",")
    if item.strip()
)
```

- [ ] **步骤 2.4：验证**

运行：

```bash
.venv/bin/python -m pytest tests/unit/admin_console/test_request_guards.py -vv
```

期望：新增和既有测试通过；必要时保留旧 Django user 测试为“迁移期兼容”或明确删除旧语义。

### 任务 3：替换控制台入口和守卫

**文件：**

- 修改：`/Users/konata/code/EasyAuth/src/easyauth/admin_console/views.py`
- 修改：`/Users/konata/code/EasyAuth/src/easyauth/admin_console/request_guards.py`
- 修改：`/Users/konata/code/EasyAuth/src/easyauth/admin_console/authz.py`
- 修改：`/Users/konata/code/EasyAuth/src/easyauth/admin_console/catalog_write_common.py`
- 修改：`/Users/konata/code/EasyAuth/src/easyauth/admin_console/permission_template_api.py`
- 测试：`/Users/konata/code/EasyAuth/tests/integration/admin_console/test_app_detail_ops1.py`
- 测试：`/Users/konata/code/EasyAuth/tests/integration/admin_console/test_operations_api_ops3.py`

- [ ] **步骤 3.1：写失败测试**

新增控制台未登录跳转测试：

```python
def test_console_redirects_to_authentik_login(client: Client):
    response = client.get("/console/")

    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"].startswith("/auth/login/?next=%2Fconsole%2F")
```

新增 App owner 使用 Authentik session 访问测试：

```python
def test_console_app_detail_accepts_authentik_session(client: Client):
    app = App.objects.create(app_key="crm", name="CRM")
    UserMirror.objects.create(authentik_user_id="ak-owner", status=USER_STATUS_ACTIVE)
    AppMembership.objects.create(app=app, user_id="ak-owner", role="owner")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = "ak-owner"
    session.save()

    response = client.get("/console/apps/crm/")

    assert response.status_code == HTTPStatus.OK
```

- [ ] **步骤 3.2：替换页面入口**

在 `views.py`：

```python
from easyauth.admin_console.identity import console_actor_from_request
```

将 `_actor_from_request()` 改为：

```python
def _actor_from_request(request: HttpRequest) -> ConsoleActor | None:
    return console_actor_from_request(request)
```

将登录跳转改为：

```python
def _login_redirect(request: HttpRequest) -> HttpResponseRedirect:
    return HttpResponseRedirect(f"/auth/login/?next={quote(request.get_full_path())}")
```

- [ ] **步骤 3.3：替换 JSON API 守卫**

在 `request_guards.py` 中：

```python
def require_console_actor(request: HttpRequest) -> ConsoleActor | JsonResponse:
    actor = console_actor_from_request(request)
    if actor is None:
        return error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "控制台登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    return actor
```

在 `authz.py` 中：

```python
def require_superuser(request: HttpRequest) -> str | JsonResponse:
    actor = console_actor_from_request(request)
    if actor is None:
        return error_response(ErrorCode.AUTHENTICATION_FAILED, "控制台登录已失效。", status=HTTPStatus.UNAUTHORIZED)
    if not actor.is_superuser:
        return error_response(ErrorCode.PERMISSION_DENIED, "只有系统管理员可以执行该操作。", status=HTTPStatus.FORBIDDEN)
    return actor.user_id
```

- [ ] **步骤 3.4：清掉残留直读 `request.user`**

运行：

```bash
rg -n "request\\.user|get_username\\(|is_superuser" src/easyauth/admin_console
```

期望：只剩与 Django admin 无关的合理兼容点；控制台业务 API 不再直接从 `request.user` 生成 actor。

- [ ] **步骤 3.5：验证**

运行：

```bash
.venv/bin/python -m pytest \
  tests/unit/admin_console/test_request_guards.py \
  tests/integration/admin_console/test_app_detail_ops1.py \
  tests/integration/admin_console/test_apps_api_ops1.py \
  tests/integration/admin_console/test_operations_api_ops3.py \
  tests/integration/admin_console/test_permission_catalog_api_ops1.py \
  tests/integration/admin_console/test_credentials_ops1.py \
  -vv
```

期望：全部通过。

---

## 阶段 2：接入 Authentik 组织上下文

### 任务 4：解析 OIDC 组织 claim 并写入 UserMirror

**文件：**

- 修改：`/Users/konata/code/EasyAuth/src/easyauth/accounts/auth.py`
- 新建：`/Users/konata/code/EasyAuth/src/easyauth/accounts/org_context.py`
- 测试：`/Users/konata/code/EasyAuth/tests/integration/auth/test_oidc_org_context.py`

- [ ] **步骤 4.1：写失败测试**

测试 OIDC claim 落入已有字段：

```python
def test_bind_oidc_session_updates_dingtalk_org_context(rf):
    request = rf.get("/auth/callback/")
    request.session = {}
    claims = VerifiedOidcClaims(
        subject="ak-user",
        name="张三",
        email="zhangsan@example.com",
        groups=("easyauth-admins",),
        dingtalk_org={
            "corp_id": "ding-corp",
            "user_id": "ding-user",
            "departments": [{"name": "销售部"}],
            "manager": {"user_id": "ding-manager", "name": "李经理"},
            "manager_chain": [{"user_id": "ding-manager", "name": "李经理"}],
            "stale": False,
            "last_synced_at": "2026-06-12T01:00:00+00:00",
        },
    )

    user = bind_oidc_session(request, claims)

    assert user.dingtalk_corp_id == "ding-corp"
    assert user.dingtalk_userid == "ding-user"
    assert user.department == "销售部"
    assert user.manager_userid == "ding-manager"
```

- [ ] **步骤 4.2：实现字段白名单映射**

`org_context.py` 提供：

```python
def apply_dingtalk_org_context(user: UserMirror, org: object) -> list[str]:
    parsed = parse_org_context(org)
    changed_fields: list[str] = []
    changed_fields.extend(_set_if_changed(user, "dingtalk_corp_id", parsed.corp_id))
    changed_fields.extend(_set_if_changed(user, "dingtalk_userid", parsed.user_id))
    changed_fields.extend(_set_if_changed(user, "department", parsed.primary_department_name))
    changed_fields.extend(_set_if_changed(user, "manager_userid", parsed.manager_user_id))
    return changed_fields
```

解析原则：

- 只接受 `corp_id`、`user_id`、`departments[].name`、`manager.user_id`。
- 忽略 `mobile`、`email`、`raw`。
- `stale=True` 不阻止登录，只保留现有字段或更新基础身份字段。

- [ ] **步骤 4.3：扩展 VerifiedOidcClaims**

在 `auth.py` 中：

```python
@dataclass(frozen=True, slots=True)
class VerifiedOidcClaims:
    subject: str
    name: str
    email: str
    groups: tuple[str, ...] = ()
    dingtalk_org: object | None = None
```

`verify_oidc_claims()` 从 claims 中读取：

```python
groups=_string_tuple_claim(claims, "groups"),
dingtalk_org=claims.get("dingtalk_org"),
```

- [ ] **步骤 4.4：验证**

运行：

```bash
.venv/bin/python -m pytest tests/integration/auth/test_oidc_org_context.py tests/integration/auth/test_oidc_exchange_s12.py -vv
```

期望：全部通过。

### 任务 5：实现 Authentik 目录 API 客户端

**文件：**

- 新建：`/Users/konata/code/EasyAuth/src/easyauth/integrations/authentik/directory_client.py`
- 新建：`/Users/konata/code/EasyAuth/src/easyauth/integrations/authentik/directory_payloads.py`
- 修改：`/Users/konata/code/EasyAuth/src/easyauth/config/settings/base.py`
- 测试：`/Users/konata/code/EasyAuth/tests/integration/authentik/test_directory_client.py`

- [ ] **步骤 5.1：增加配置**

在 `settings/base.py`：

```python
EASYAUTH_AUTHENTIK_BASE_URL = os.environ.get(
    "EASYAUTH_AUTHENTIK_BASE_URL",
    "http://localhost:19000",
).rstrip("/")
EASYAUTH_AUTHENTIK_API_TOKEN = os.environ.get("EASYAUTH_AUTHENTIK_API_TOKEN", "")
EASYAUTH_AUTHENTIK_DINGTALK_SOURCE_SLUG = os.environ.get(
    "EASYAUTH_AUTHENTIK_DINGTALK_SOURCE_SLUG",
    "dingtalk",
)
```

- [ ] **步骤 5.2：写客户端测试**

使用 monkeypatch 或 requests mock，覆盖：

```python
def test_directory_client_fetches_user_org_context(requests_mock, settings):
    settings.EASYAUTH_AUTHENTIK_BASE_URL = "http://authentik.test"
    settings.EASYAUTH_AUTHENTIK_API_TOKEN = "token-value"
    requests_mock.get(
        "http://authentik.test/api/v3/sources/oauth/dingtalk-directory/dingtalk/users/corp-1/user-1/org/",
        json={
            "corp_id": "corp-1",
            "user_id": "user-1",
            "source_slug": "dingtalk",
            "departments": [{"dept_id": "1", "name": "销售部", "parent_id": ""}],
            "manager": {"user_id": "manager-1", "name": "主管"},
            "manager_chain": [{"user_id": "manager-1", "name": "主管"}],
            "stale": False,
            "last_synced_at": "2026-06-12T01:00:00+00:00",
        },
    )

    context = AuthentikDirectoryClient.from_settings().get_user_org("corp-1", "user-1")

    assert context.manager["user_id"] == "manager-1"
```

- [ ] **步骤 5.3：实现客户端**

接口：

```python
class AuthentikDirectoryClient:
    def get_status(self) -> DingTalkDirectoryStatus: ...
    def iter_departments(self) -> Iterator[DingTalkDirectoryDepartment]: ...
    def iter_users(self) -> Iterator[DingTalkDirectoryUser]: ...
    def get_user_org(self, corp_id: str, user_id: str) -> DingTalkDirectoryOrgContext: ...
```

请求头：

```python
headers={"Authorization": f"Bearer {self.api_token}"}
```

错误处理：

- 401/403：抛 `AuthentikDirectoryPermissionError`。
- 404：抛 `AuthentikDirectoryNotFoundError`。
- 5xx/网络错误：抛 `AuthentikDirectoryUnavailableError`。
- 日志不得包含 token。

- [ ] **步骤 5.4：验证**

运行：

```bash
.venv/bin/python -m pytest tests/integration/authentik/test_directory_client.py -vv
```

期望：全部通过。

---

## 阶段 3：后端同步、健康检查与联调

### 任务 6：同步完整 Authentik 钉钉目录缓存

**文件：**

- 修改：`/Users/konata/code/EasyAuth/src/easyauth/accounts/models.py`
- 修改：`/Users/konata/code/EasyAuth/src/easyauth/accounts/services.py`
- 新建：`/Users/konata/code/EasyAuth/src/easyauth/integrations/authentik/directory_sync.py`
- 修改：`/Users/konata/code/EasyAuth/src/easyauth/tasks/authentik.py`
- 新建迁移：`/Users/konata/code/EasyAuth/src/easyauth/accounts/migrations/`
- 测试：`/Users/konata/code/EasyAuth/tests/integration/authentik/test_sync_s10.py`
- 测试：`/Users/konata/code/EasyAuth/tests/integration/authentik/test_directory_sync.py`

- [ ] **步骤 6.1：写完整目录缓存测试**

覆盖部门、通讯录用户、用户组织上下文三类数据：

```python
def test_directory_sync_caches_departments_users_and_org_context(client_stub):
    client_stub.departments = [
        {
            "corp_id": "corp-1",
            "dept_id": "dept-1",
            "parent_id": "",
            "name": "销售部",
            "order": 10,
        }
    ]
    client_stub.users = [
        {
            "corp_id": "corp-1",
            "user_id": "user-1",
            "union_id": "union-1",
            "name": "张三",
            "department_ids": ["dept-1"],
            "manager_userid": "manager-1",
            "status": "active",
        }
    ]
    client_stub.org_contexts[("corp-1", "user-1")] = {
        "corp_id": "corp-1",
        "user_id": "user-1",
        "departments": [{"dept_id": "dept-1", "name": "销售部"}],
        "manager": {"user_id": "manager-1", "name": "主管"},
        "manager_chain": [{"user_id": "manager-1", "name": "主管"}],
        "stale": False,
    }

    result = sync_authentik_dingtalk_directory(client_stub)

    assert result.department_count == 1
    assert result.user_count == 1
    assert DingTalkDepartmentMirror.objects.get(corp_id="corp-1", dept_id="dept-1").name == "销售部"
    assert DingTalkUserMirror.objects.get(corp_id="corp-1", user_id="user-1").manager_userid == "manager-1"
    assert DingTalkUserOrgContext.objects.get(corp_id="corp-1", user_id="user-1").manager_chain[0]["user_id"] == "manager-1"
```

- [ ] **步骤 6.2：增加目录缓存模型**

模型职责：

- `DingTalkDepartmentMirror`：保存 `source_slug`、`corp_id`、`dept_id`、`parent_id`、`name`、`order`、`last_synced_at`。
- `DingTalkUserMirror`：保存 `source_slug`、`corp_id`、`user_id`、`union_id`、`name`、`department_ids`、`manager_userid`、`status`、`last_synced_at`。
- `DingTalkUserOrgContext`：保存 `source_slug`、`corp_id`、`user_id`、`departments`、`manager`、`manager_chain`、`stale`、`last_synced_at`。
- `DingTalkDirectorySyncState`：保存 `source_slug`、`corp_id`、`status`、`counters`、`finished_at`、`error`。

唯一约束：

- `DingTalkDepartmentMirror`：`source_slug + corp_id + dept_id`
- `DingTalkUserMirror`：`source_slug + corp_id + user_id`
- `DingTalkUserOrgContext`：`source_slug + corp_id + user_id`
- `DingTalkDirectorySyncState`：`source_slug + corp_id`

不得保存：

- Authentik API token
- DingTalk access token 或 app secret
- Authentik 原始 `raw_profile`
- Authentik 目录 API 未明确返回的手机号、邮箱

- [ ] **步骤 6.3：实现目录同步服务**

同步流程：

1. 调用 `get_status()` 写入 `DingTalkDirectorySyncState`。
2. 调用 `iter_departments()` 幂等更新 `DingTalkDepartmentMirror`。
3. 调用 `iter_users()` 幂等更新 `DingTalkUserMirror`。
4. 对每个有 `corp_id + user_id` 的用户调用 `get_user_org()` 幂等更新 `DingTalkUserOrgContext`。
5. 如果用户能关联到 `UserMirror.dingtalk_corp_id + dingtalk_userid`，同步摘要字段到 `UserMirror.department` 和 `UserMirror.manager_userid`。

- [ ] **步骤 6.4：继续支持 Authentik payload 写入当前用户摘要**

保留当前用户登录或用户同步时的摘要字段更新：

```python
def test_sync_payload_updates_dingtalk_fields():
    result = AuthentikSyncService.sync_payload(
        {
            "user": {
                "sub": "ak-user",
                "name": "张三",
                "email": "zhangsan@example.com",
                "attributes": {
                    "department": "销售部",
                    "status": "active",
                    "dingtalk": {
                        "corp_id": "corp-1",
                        "user_id": "user-1",
                        "union_id": "union-1",
                    },
                    "dingtalk_org": {
                        "manager": {"user_id": "manager-1"},
                        "departments": [{"name": "销售部"}],
                    },
                },
            }
        }
    )

    assert result.user.dingtalk_corp_id == "corp-1"
    assert result.user.dingtalk_userid == "user-1"
    assert result.user.manager_userid == "manager-1"
```

- [ ] **步骤 6.5：扩展 payload parser**

在 `payloads.py` 增加白名单字段：

```python
class AuthentikDingTalkAttributes(TypedDict, total=False):
    corp_id: str
    user_id: str
    union_id: str
    job_number: str
```

`AuthentikUserProfile` 增加：

```python
dingtalk_corp_id: str = ""
dingtalk_userid: str = ""
dingtalk_union_id: str = ""
employee_number: str = ""
manager_userid: str = ""
```

- [ ] **步骤 6.6：同步服务写入现有摘要字段**

在 `_upsert_user()` 中更新字段：

```python
user.dingtalk_corp_id = profile.dingtalk_corp_id
user.dingtalk_userid = profile.dingtalk_userid
user.dingtalk_union_id = profile.dingtalk_union_id
user.employee_number = profile.employee_number
user.manager_userid = profile.manager_userid
```

- [ ] **步骤 6.7：验证**

运行：

```bash
.venv/bin/python -m pytest tests/integration/authentik/test_sync_s10.py tests/integration/authentik/test_directory_sync.py -vv
```

期望：全部通过。

### 任务 7：健康检查显示 Authentik 目录状态

**文件：**

- 修改：`/Users/konata/code/EasyAuth/src/easyauth/applications/dependency_health.py`
- 修改：`/Users/konata/code/EasyAuth/src/easyauth/admin_console/operations_api.py`
- 测试：`/Users/konata/code/EasyAuth/tests/integration/admin_console/test_dependency_health_ops3.py`

- [ ] **步骤 7.1：写失败测试**

新增测试：

```python
def test_dependency_health_includes_authentik_directory_status(client, monkeypatch):
    monkeypatch.setattr(
        "easyauth.applications.dependency_health.AuthentikDirectoryClient.from_settings",
        lambda: FakeDirectoryClient(status="success", counters={"users": 12, "departments": 3}),
    )
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = "ak-admin"
    session.save()
    UserMirror.objects.create(authentik_user_id="ak-admin", status=USER_STATUS_ACTIVE)

    response = client.get("/console/api/operations/dependency-health/")

    assert response.status_code == HTTPStatus.OK
    assert "authentik_directory" in response.json()["health_map"]
```

- [ ] **步骤 7.2：实现健康项**

健康项字段：

```json
{
  "key": "authentik_directory",
  "status": "healthy",
  "summary": "钉钉目录最近同步成功",
  "metadata": {
    "source_slug": "dingtalk",
    "corp_ids": ["corp-1"],
    "last_success_at": "2026-06-12T01:00:00+00:00"
  }
}
```

不得包含：

- `EASYAUTH_AUTHENTIK_API_TOKEN`
- DingTalk app secret
- access token
- raw profile

- [ ] **步骤 7.3：验证**

运行：

```bash
.venv/bin/python -m pytest tests/integration/admin_console/test_dependency_health_ops3.py -vv
```

期望：全部通过。

### 任务 8：本地联调

**文件：**

- 除非前面步骤发现配置缺口，否则不需要修改源码。

- [ ] **步骤 8.1：配置 EasyAuth OIDC 指向 Authentik**

示例环境变量：

```bash
export EASYAUTH_AUTHENTIK_OIDC_ISSUER="http://localhost:19000/application/o/easyauth/"
export EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT="http://localhost:19000/application/o/authorize/"
export EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT="http://localhost:19000/application/o/token/"
export EASYAUTH_AUTHENTIK_OIDC_JWKS_URL="http://localhost:19000/application/o/easyauth/jwks/"
export EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID="<easyauth-client-id>"
export EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET="<easyauth-client-secret>"
export EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI="http://127.0.0.1:18000/auth/callback/"
export EASYAUTH_AUTHENTIK_OIDC_SCOPES="openid profile email easyauth_org"
export EASYAUTH_AUTHENTIK_BASE_URL="http://localhost:19000"
export EASYAUTH_AUTHENTIK_DINGTALK_SOURCE_SLUG="dingtalk"
export EASYAUTH_AUTHENTIK_API_TOKEN="<authentik-api-token>"
export EASYAUTH_CONSOLE_SUPERUSER_GROUPS="EasyAuth Admins"
```

- [ ] **步骤 8.2：启动 EasyAuth**

运行：

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 0.0.0.0:18000
```

- [ ] **步骤 8.3：验证控制台登录**

打开：

```text
http://127.0.0.1:18000/console/
```

期望：

- 未登录跳转到 Authentik。
- 钉钉登录成功后回到 `/console/`。
- `UserMirror.authentik_user_id` 等于 Authentik OIDC `sub`。
- App owner/developer 根据 `AppMembership.user_id == authentik_user_id` 生效。

- [ ] **步骤 8.4：验证目录 API**

运行：

```bash
curl -sS \
  -H "Authorization: Bearer ${EASYAUTH_AUTHENTIK_API_TOKEN}" \
  http://localhost:19000/api/v3/sources/oauth/dingtalk-directory/dingtalk/status/
```

再验证用户组织上下文：

```bash
curl -sS \
  -H "Authorization: Bearer ${EASYAUTH_AUTHENTIK_API_TOKEN}" \
  "http://localhost:19000/api/v3/sources/oauth/dingtalk-directory/dingtalk/users/${DINGTALK_CORP_ID}/${DINGTALK_USER_ID}/org/"
```

期望：

- 返回 `departments`、`manager`、`manager_chain`。
- `stale` 字段存在。
- 不返回 `raw`、`mobile`、`email`。

- [ ] **步骤 8.5：验证端到端权限链路**

流程：

1. 钉钉登录 Authentik。
2. 回到 EasyAuth `/portal/` 或 `/console/`。
3. 创建或确认 `AppMembership` 指向 Authentik `sub`。
4. 提交权限申请。
5. 通过钉钉审批回调或测试回调完成授权落库。
6. EasyTrade 通过 EasyAuth 权限查询 API 查询该 Authentik `sub` 的权限。

期望：

- EasyAuth 返回 `roles/permissions/version/expires_at`。
- 权限查询用户 ID 与 Authentik `sub` 一致。

---

## 阶段 4：回归与风险检查

- [ ] **步骤 9.1：EasyAuth 回归测试**

运行：

```bash
.venv/bin/python -m pytest \
  tests/integration/auth \
  tests/integration/portal \
  tests/integration/admin_console \
  tests/integration/authentik \
  tests/integration/api/test_permission_query.py \
  -vv
```

- [ ] **步骤 9.2：Authentik 钉钉相关回归**

在 `/Users/konata/code/Authentik` 运行：

```bash
uv run pytest authentik/sources/oauth/tests -k "dingtalk" -vv
```

- [ ] **步骤 9.3：隐私与日志检查**

运行：

```bash
rg -n "AUTHENTIK_API_TOKEN|consumer_secret|access_token|raw_profile|mobile|EASYAUTH_AUTHENTIK_API_TOKEN" \
  /Users/konata/code/EasyAuth/src \
  /Users/konata/code/EasyAuth/tests
```

期望：

- 没有 token/secret 被写入日志、审计响应或健康响应。
- `mobile` 只出现在测试或明确不暴露的断言中。

---

## 暂不纳入本轮

- 不让 EasyTrade 传主管、通讯录或部门信息给 EasyAuth。
- 不让 EasyAuth 直接调用 DingTalk OpenAPI。
- 不在本轮改变 `ApprovalRule` 语义为“直属主管审批”或“主管链审批”。如果要做，需要单独定义审批规则字段、失败策略和回退策略。
- 不把 Authentik 原始 `raw_profile`、手机号、邮箱作为默认目录同步输出。

## 执行代理自行完成的 Authentik 配置

执行前和执行中不向用户索要以下 Authentik 输入；必须从 `/Users/konata/code/Authentik`、运行中的 Docker 实例和 Authentik API 自行发现或配置：

1. 发现 EasyAuth OIDC Application、Provider、client id、client secret、redirect URI 和 setup URLs；当前运行实例已发现 Application slug 为 `easyauth`，client id 为 `easyauth-portal`。
2. 发现 DingTalk source；当前运行实例已发现 slug 为 `dingtalk`，且最近目录同步成功。
3. 幂等创建或复用 `EasyAuth Admins` Authentik group，并让 EasyAuth 控制台系统管理员判断只依赖该 group。
4. 幂等创建或轮换 EasyAuth 专用 Authentik API token；token key 只进入 EasyAuth 本地运行配置，不进入文档和日志。
5. 通过 Authentik 目录 API 获取完整部门、通讯录用户、当前用户组织上下文和主管链，并同步到 EasyAuth 本地目录缓存。

## 验收标准

- `/console/` 不再跳 `/admin/login/`，而是通过 Authentik OIDC 登录。
- 控制台 actor 的 `user_id` 是 Authentik `sub`。
- App owner/developer 权限仍由 `AppMembership` 控制。
- 系统管理员来自 Authentik group，不再依赖 subject allowlist 作为默认方案。
- EasyAuth 能读取 Authentik 钉钉目录状态、用户组织上下文、部门和用户列表。
- EasyAuth 本地目录缓存能保存完整部门、通讯录用户、主管链和同步状态。
- `UserMirror` 能保存当前用户钉钉 corp、user、union、department、manager 摘要信息。
- 目录 API 错误、过期数据和权限不足不会影响既有权限查询。
- 测试和联调过程中不泄露 Authentik token、DingTalk secret、raw profile。
