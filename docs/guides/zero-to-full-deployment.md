# 从零部署全链路（Authentik + EasyAuth + 下游应用）

本文是三方联调的部署顺序与踩坑清单。按此顺序完整跑通过一次全新部署：钉钉扫码登录 → 下游应用
无权限跳申请页 → EasyAuth 门户申请 → 审批 → 权限生效。下文的"坑"都是真实遇到过的。

只部署 EasyAuth 本身看 [README 的生产部署](../../README.md#生产部署手动)；
本文关注的是**三方之间**的接线。

## 前置条件

- 一台装好 docker + docker compose 的机器。
- 反向代理指向本机，三个域名（Authentik / EasyAuth / 下游应用），必须透传 `Host` 和
  `X-Forwarded-Proto`。
- 钉钉开放平台的企业内部应用一个，需要：
  - appKey / appSecret；
  - 登录回调域名登记 `https://<authentik 域名>/source/oauth/callback/dingtalk/`；
  - 通讯录只读权限（用于目录同步）。

> ⚠️ **直属主管不是权限点，是数据。** `manager_userid` 只有在钉钉管理后台（通讯录成员编辑
> 或智能人事花名册）维护过「直属主管」字段时才有值。没维护过则全员为空，EasyAuth 会阻止包
> 含 `MANAGED_USERS` 的申请提交，必须先在权威目录补齐主管关系。开放平台没有单独的"查询直属
> 主管"权限可选。

## 1. Authentik（定制 fork，含钉钉 Source）

1. 构建镜像：
   `DOCKER_BUILDKIT=1 docker build . -f lifecycle/container/Dockerfile --tag authentik-dingtalk:local`。
2. 部署目录放 `compose.yml`（postgres + server + worker）和 `.env`（`PG_PASS`、
   `AUTHENTIK_SECRET_KEY`、`AUTHENTIK_BOOTSTRAP_PASSWORD/TOKEN/EMAIL`、镜像名与 tag、端口）。
   **bootstrap token 之后同时充当 EasyAuth 的 `EASYAUTH_AUTHENTIK_API_TOKEN`。**
3. `docker compose up -d`，然后**等 blueprint 应用完**——worker 异步创建默认 flow，轮询
   `/api/v3/flows/instances/` 看到 `default-source-authentication` 再继续。
   本机现行拓扑是 Authentik 发布在宿主 `127.0.0.1:19000`，由反代对外为 auth 域名；
   EasyAuth 容器访问它必须走 `http://host.docker.internal:19000`（容器内的 `localhost` 不是宿主）。
4. 按 [Authentik 自动化配置](authentik-easyauth-automation-setup-llm.md) 幂等配置：钉钉
   Source（slug `dingtalk`）、`EasyAuth Admins` 组、`easyauth_org` / `dingtalk` scope mapping、
   `easyauth-portal` Provider + Application、logout stage 绑定、brand default_application、
   identification stage 挂钉钉源。
5. 验收：`/application/o/easyauth/jwks/` 有 key；`/source/oauth/login/dingtalk/` 的
   `Location` 里 `redirect_uri` 是公网 https 回调。

**这一步的三个坑：**

- Provider 的 `grant_types` 必须显式包含 `authorization_code`（2026.x API 默认空 = 全拒）。
- 登录页钉钉入口要保持「图标 + 文字」：stage 设 `show_source_labels=True`，source 不设
  `promoted`。
- PATCH identification stage 时必须同时带 `user_fields` 和 `sources`，只带一个会覆盖另一个。

## 2. EasyAuth

1. 构建：`docker compose -f docker-compose.deploy.yml build web`。
2. 初始化（全新库）在**容器内**执行：
   ```bash
   docker compose -f docker-compose.deploy.yml run --rm --no-deps web python manage.py migrate
   docker compose -f docker-compose.deploy.yml run --rm --no-deps web \
     python manage.py create_local_admin admin --password '<随机强密码>'
   ```
3. `.env.local`：OIDC 端点指向公网 Authentik、`EASYAUTH_AUTHENTIK_API_TOKEN` 用上一步的
   bootstrap token、client secret 与 Authentik provider 一致。部署级覆盖（容器内地址、公网
   回调、WebAuthn RP）都在 `docker-compose.deploy.yml` 里。
4. `docker compose -f docker-compose.deploy.yml up -d`——七个服务全起：
   web、worker、webhook-worker、notify-worker、beat、stream、redis。
   **worker 和 beat 不是可选增强**：beat 调度的目录同步是离职检出的信号源，缺了离职/转岗自动化
   根本不触发；webhook-worker 和 notify-worker 各自消费独立队列，缺了对应投递会静默积压。
   端口只发布到 `127.0.0.1:8001`，由反代对外为 iam 域名。
   **之后每次改代码都要 `build web` 再 `up -d`**——源码 `COPY` 进镜像，只重启不重建等于没上线。
5. 本地管理员登录 `/auth/local/` → `/auth/local/security/` 绑定 TOTP 或通行密钥 →
   `/console/settings` 填钉钉 AppKey / AppSecret →「测试连通性」应显示"钉钉凭证有效"。
   之后 stream 容器就能连上钉钉 WebSocket。
6. **目录同步有个先后依赖**：EasyAuth 的目录同步依赖 Authentik 侧的钉钉目录，而 Authentik 的
   目录同步需要 corp_id——**首次钉钉登录之后才有**。着急可手动触发：
   `POST /api/v3/sources/oauth/dingtalk-directory/dingtalk/sync/ {"corp_id": ...}`，
   然后在 EasyAuth 侧等 beat（5 分钟）或手动跑 `sync_dingtalk_directory_task`。

## 3. 下游应用

1. 应用侧配置 OIDC：issuer `https://<authentik>/application/o/<app>/`，client_id / secret 与
   Authentik 一致。
2. 应用侧生成描述符同步密钥（明文只显示一次），并配置「权限申请页 URL」指向
   `https://<easyauth>/portal/request`。
3. EasyAuth 控制台 → 应用列表 → 接入向导 → **自动接入**：填下游地址、`app_key`、描述符密钥
   → 导入 manifest。交接 webhook URL 会由 manifest 的 lifecycle 声明自动回填。
4. 应用工作台：凭据页签发静态 token（`eat_`）、Webhook 页生成签名密钥（`whsec_`），回填到下
   游配置后重启下游。Webhook 页「发送测试事件」应一次投递成功。
5. 之后权限模板变更走自动同步：改模板 → manifest `schema_version` +1 → 重启下游，启动日志出
   现 `easyauth_manifest_push_ok` 即完成（见 [SDK 集成指南](easyauth-app-sdk-integration.md)）。

## 4. 全链路验收

1. 打开下游应用 →「使用工作账号登录」→ Authentik 登录页应有钉钉入口 → 扫码。
2. 首次登录预期落在 **403 权限申请页**，点「申请权限」跳 EasyAuth 门户。
3. 门户选授权组（下方权限列表会联动显示覆盖范围）→ 默认审批人来自直属上级 / 审批规则 /
   App owner（都解析不到时需手动选择，且不能选自己）→ 提交。
4. 审批人在门户「待我审批」或管理员在控制台「申请运营」通过 → 下游刷新授权快照 → 用户获得
   对应模块。

## 5. 生命周期（离职/转岗交接）

- **没有"审批人"环节是设计使然**：离职/转岗是管理员执行的人事决策落地工具，决策本身在钉钉
  HR 流程完成；交接单只负责数据归属、权限差异和团队调整的执行。
- **转岗前要先建岗位模板**：全新库模板为空，先到「入职授权」页新建模板（应用 + 授权组/权限
  逐项添加），转岗单里才有可选项。
- **交接向导第 2 步是两段式**：选「统一接收人」后还要点「应用到所选应用」；漏点时「下一步」
  会自动补齐，也可以按应用分别指定或释放到公海。
- **交接单清理**：进行中只能取消；已取消可删除（落审计）；已完成作为交接史料保留，不提供删除。
- **内置本地管理员不参与生命周期**：人员目录和选人控件不展示，建单与接收人解析都会拒绝
  local-admin。

## 常见坑速查

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| authorize 报 `invalid_request`，日志 `Invalid grant_type for provider` | provider `grant_types` 为空 | 补 `authorization_code` + `refresh_token` |
| OIDC「自动发现」404，`curl .well-known` 公网 404 但本机 200 | 宝塔/aaPanel 生成的 `location ~ \.well-known{` 没有锚定，URI 任意位置含 `.well-known` 都被截走落盘 | 三个域名的 vhost 都改成 `location ~ ^/\.well-known/{` 后 reload（注意机器上可能有两个 nginx master，要 reload 持有 443 的那个）；ACME 根路径验证不受影响 |
| 配置脚本 404 `default-source-authentication` | blueprint 还没应用完 | 等默认 flow 出现再配置 |
| 申请页没有默认审批人 | 钉钉后台没维护「直属主管」/ 目录未同步 / 审批规则里是占位 userid | 后台补主管关系并触发目录同步；把审批规则换成真实 userid（钉钉 userid 或 `local-admin:<name>`） |
| manifest 导入报"无法解析" | EasyAuth 版本落后于下游 manifest 契约（如 lifecycle / webhook 节） | 升级 EasyAuth 后重试 |
| 本人申请提交不了 | 审批人不能选自己 | 规则里配第二审批人（如 `local-admin:admin`），由管理员代审 |
| 改完代码公网没变化 | 源码构建进镜像，重启不重建无效 | 重建镜像再 `up -d` |
