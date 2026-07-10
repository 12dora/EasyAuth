# 三应用从零部署实录（Authentik + EasyAuth + EasyTrade）

## 状态

2026-07-06 按本文顺序完成过一次真实的从零部署（清空全部数据重来），全链路验收通过：
钉钉扫码登录 → EasyTrade 默认无权限跳申请页 → EasyAuth 门户申请 → 审批 → 权限生效。
文中"坑"都在当次部署真实踩过。

## 前置条件

- 有 docker + docker compose 的机器一台。
- 反向代理指向本机（本环境为 frpc：`auth.jiefakj.com→:19000`、`iam.jiefakj.com→:8001`、
  `etrade.jiefakj.com→:3000`），必须透传 `Host` / `X-Forwarded-Proto`。
- 钉钉开放平台企业内部应用一个，需要：
  - appKey / appSecret；
  - 登录回调域名登记 `https://<authentik 域名>/source/oauth/callback/dingtalk/`；
  - 权限：通讯录只读（目录同步）。
  - **直属主管不是权限点，是数据**：`manager_userid` 只有在钉钉管理后台
    （oa.dingtalk.com 通讯录成员编辑，或智能人事花名册）维护过「直属主管」字段
    时才有值；没维护过则全员为空，EasyAuth 会阻止包含 `MANAGED_USERS` 的申请提交，
    必须先在权威目录补齐直属主管关系。开放平台没有单独叫"查询直属主管"的权限可选。

## 部署顺序

### 1. Authentik（定制 fork，含钉钉 Source）

1. 构建镜像：`cd Authentik && DOCKER_BUILDKIT=1 docker build . -f lifecycle/container/Dockerfile --tag authentik-dingtalk:local`。
2. 部署目录 `~/.local/share/easyauth/authentik/`：`compose.yml`（postgres + server + worker）
   加 `.env`（`PG_PASS`、`AUTHENTIK_SECRET_KEY`、`AUTHENTIK_BOOTSTRAP_PASSWORD/TOKEN/EMAIL`、
   `AUTHENTIK_IMAGE=authentik-dingtalk`、`AUTHENTIK_TAG=local`、端口 19000/19443）。
   bootstrap token 之后同时充当 EasyAuth 的 `EASYAUTH_AUTHENTIK_API_TOKEN`。
3. `docker compose up -d`。**等 blueprint 应用完**（worker 异步建默认 flows；
   轮询 `/api/v3/flows/instances/` 见到 `default-source-authentication` 再继续）。
4. 按 [authentik-easyauth-automation-setup-llm.md](authentik-easyauth-automation-setup-llm.md)
   幂等配置：钉钉 Source（slug `dingtalk`）、`EasyAuth Admins` 组、`easyauth_org`/`dingtalk`
   scope mapping、`easyauth-portal` Provider + Application、logout stage 绑定、brand
   default_application、Identification stage 挂钉钉源。三条当次踩过的坑：
   - Provider `grant_types` 必须显式含 `authorization_code`（2026.x API 默认空=全拒）。
   - 登录页钉钉入口保持「图标+文字」：stage `show_source_labels=True`、source 不设 `promoted`。
   - PATCH identification stage 要同时带 `user_fields` + `sources`。
5. 验收：`/application/o/easyauth/jwks/` 有 key；`/source/oauth/login/dingtalk/` 的
   Location 中 `redirect_uri` 是公网 https 回调。

### 2. EasyAuth

1. 构建：`docker compose -f docker-compose.deploy.yml build web`。
2. 初始化（全新库）：`touch db.sqlite3`，然后在**容器内**跑
   `docker compose -f docker-compose.deploy.yml run --rm --no-deps web python manage.py migrate`
   和 `... create_local_admin admin --password <随机> --no-force-password-change`。
3. `.env.local`：OIDC 端点指向公网 Authentik、`EASYAUTH_AUTHENTIK_API_TOKEN` 用 bootstrap
   token、client secret 与 Authentik provider 一致。部署级覆盖（容器内地址、公网回调、
   WebAuthn RP）都在 `docker-compose.deploy.yml` 里，通常不用改。
4. `docker compose -f docker-compose.deploy.yml up -d`（web/worker/beat/stream/redis 全套）。
5. 本地管理员登录 `/auth/local/` → `/console/settings` 填钉钉 AppKey/AppSecret →
   「测试连通性」应显示"钉钉凭证有效"。stream 容器随后能连上钉钉 WebSocket。
6. 目录同步依赖 Authentik 侧钉钉目录，而 Authentik 的目录同步需要 corp_id——
   **首次钉钉登录之后才有**。着急可手动触发：
   `POST /api/v3/sources/oauth/dingtalk-directory/dingtalk/sync/ {"corp_id": ...}`，
   然后 EasyAuth 侧等 beat（5 分钟）或手动执行 `sync_dingtalk_directory_task`。

### 3. EasyTrade

1. `.env`：改 `POSTGRES_PASSWORD`/`DATABASE_URL`/`JWT_SECRET`/`EASYTRADE_SEED_ADMIN_PASSWORD`；
   `EASYAUTH_STATIC_APP_TOKEN`、`EASYAUTH_WEBHOOK_SECRET` 先留空（注册后回填）。
2. `docker compose up -d`（entrypoint 自动 alembic 迁移）→
   `docker compose exec backend python -m app.seed`。
3. 管理员登录（首登强制改密）→ `设置-身份集成`：启用 OIDC、issuer
   `https://<authentik>/application/o/easytrade/`、client_id/secret 与 Authentik 一致。
   **「自动发现」在公网反代拦截 `/.well-known` 时会 404（UI 有对应提示），按 hint 手工填
   四个端点即可**；`Server base URL` 留空走公网直连，或填
   `http://host.docker.internal:19000` 走本机直连。保存 → 「连接测试」应 ok。
4. `设置-权限与授权`：新建描述符同步密钥（明文只显示一次）、填「权限申请页 URL」
   `https://<easyauth>/portal/request`。
5. EasyAuth 控制台 → 应用列表 → 接入向导 → 自动接入：下游地址
   `http://host.docker.internal:8000`、app_key `easytrade`、贴描述符密钥 → 导入 manifest。
   交接 webhook URL 会由 manifest 的 lifecycle 声明自动回填。
6. EasyAuth 应用工作台：凭据页签发静态 token（`eat_`）、Webhook 页生成签名密钥
   （`whsec_`），二者回填 EasyTrade `.env` 后 `docker compose up -d backend`。
   Webhook 页「发送测试事件」应一次投递成功。
7. 之后权限模板变更走自动同步：改模板 → `EASYAUTH_MANIFEST_SCHEMA_VERSION` +1 →
   重建/重启 backend，启动日志 `easyauth_manifest_push_ok` 即同步完成
   （见 [easyauth-app-sdk-integration.md](easyauth-app-sdk-integration.md) 的自动同步节）。

### 4. 全链路验收

1. `https://<easytrade>` → 「使用工作账号登录」→ Authentik 登录页应有钉钉入口 → 扫码。
2. 首次登录预期落在 **403 权限申请页**（`permission-onboarding`），点「申请权限」
   跳 EasyAuth 门户。
3. 门户选权限组（下方权限列表会联动显示该组覆盖范围）→ 默认审批人来自
   直属上级/审批规则/App owner（都解析不到时需手动选择，且不能选自己）→ 提交。
4. 审批人在门户「待我审批」或管理员在控制台「申请运营」通过 → EasyTrade 刷新
   授权快照（自动过期拉新，或设置页手动「刷新」）→ 用户获得对应模块。

### 5. 生命周期(离职/转岗交接)操作要点

2026-07-06 用演练账号端到端跑通过一次(建单 → 向导 → EasyTrade 数据交接 webhook →
完成), 要点:

- **没有"审批人"环节是设计使然**: 离职/转岗是管理员执行的人事决策落地工具,
  决策本身在钉钉 HR 流程完成; 交接单只负责数据归属、权限差异与团队调整的执行。
- **转岗的"岗位模板"要先建**: 全新库模板为空, 先到「入职授权」页新建模板
  (应用 + 授权组/权限 逐项添加), 转岗单里才有可选项。
- **向导第 2 步是两段式**: 选「统一接收人」后还要点「应用到所选应用」;
  现在漏点时「下一步」会自动补齐(d9fd144), 也可以按应用分别指定或释放到公海。
- **交接单清理**: 进行中只能取消; 已取消可删除(删除动作落审计); 已完成作为
  交接史料保留, 不提供删除。
- **内置本地管理员不参与生命周期**: 人员目录/选人控件不展示, 建单与接收人
  解析都会拒绝 local-admin(4237f35)。

## 常见坑速查

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| authorize 报 `invalid_request`，日志 `Invalid grant_type for provider` | provider `grant_types` 为空 | 补 `authorization_code`+`refresh_token` |
| OIDC「自动发现」404，`curl .well-known` 公网 404 本机 200 | 宝塔/aaPanel 生成的 `location ~ \.well-known{` 未锚定，URI 任意位置含 `.well-known` 都被截走落盘 | 把三个域名 vhost 的该行改成 `location ~ ^/\.well-known/{` 后 reload（2026-07-06 已修；注意机器上可能有两个 nginx master，要 reload 持有 443 的那个）；ACME 根路径验证不受影响 |
| 配置脚本 404 `default-source-authentication` | blueprint 还没应用完 | 等默认 flow 出现再配置 |
| 申请页没有默认审批人 | 钉钉后台没维护「直属主管」字段 / Authentik fork 旧版同步取不到主管（user/list 不返回该字段, c0fe568 起用 user/get 补全）/ 目录未同步 / 审批规则里是占位 userid | 后台维护直属主管；升级 fork 并触发目录同步；把审批规则换成真实 userid（钉钉 userid 或 `local-admin:<name>`） |
| manifest 导入报"无法解析" | EasyAuth 版本落后于下游 manifest 契约（如 lifecycle/webhook 节） | 升级 EasyAuth 后重试（解析器需支持对应 schema） |
| 本人申请提交不了 | 审批人不能选自己 | 规则里配第二审批人（如 `local-admin:admin`），由管理员代审 |
| 改完代码公网没变化 | 源码构建进镜像，重启不重建无效 | 重建镜像再 `up -d`（见 docs 部署纪律） |
