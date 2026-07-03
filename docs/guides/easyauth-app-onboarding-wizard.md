# 应用接入向导与部署口径

## 自动接入(推荐)

下游应用集成 `easyauth-app-sdk`(仓库 `sdk/python`)并暴露集成描述符端点 `GET /.well-known/easyauth-app.json` 后,向导第一步顶部的「自动接入」面板只需填写下游地址与 app_key(下游配置了共享密钥时另填描述符 token),即可一键完成:

1. EasyAuth 拉取下游描述符(`POST /console/api/v1/apps/auto-onboarding`,仅系统管理员)。
2. 校验描述符与 manifest(app_key 一致、schema_version 为正整数)。
3. 应用不存在时按描述符元数据创建 App。
4. 将 manifest 走既有导入管线落库(schema_version 必须大于已导入最新版本;同版本同内容幂等返回 `already_up_to_date`,同版本不同内容返回 409 要求下游递增版本)。

成功后可直接跳到第 3 步配置检查;凭据签发与联调仍按向导后续步骤进行。权限的中英文显示名(`name` / `name_en`)由下游 manifest 携带,EasyAuth 不做任何硬编码兜底——这是权限 i18n 从下游传递到 EasyAuth 的唯一通道。

## 接入向导(手动)

控制台提供向导式应用接入入口,路由为 `/console/apps/new`,入口在应用列表右上角「接入向导」按钮;配置未就绪的应用在列表操作列提供「继续接入」,携带 `?app_key=<key>&step=catalog` 续接。未集成 SDK 的下游仍可在第一步「手动录入」部分创建应用并手动导入 manifest。

向导共六步,除自动接入外全部复用既有控制台 API:

| 步骤 | 内容 | 后端 API |
|---|---|---|
| 1 基本信息 | 创建 App 与 Owner/Developer 成员 | `POST /console/api/v1/apps` |
| 2 权限目录 | 粘贴/上传下游导出的 manifest,预览差异后确认导入;可跳过 | `POST .../permission-template-imports/preview`、`POST .../permission-template-imports/{preview_id}/confirm` |
| 3 授权与审批 | 展示配置完整性检查结果,阻塞项跳转工作台对应页签处理 | `GET .../configuration-status` |
| 4 接入凭据 | 创建 static token 或 OAuth client,明文只展示一次 | `POST .../credentials/static-tokens`、`POST .../credentials/oauth-clients` |
| 5 联调验证 | 用刚签发的凭据发起真实公共权限查询 | `POST .../permission-query-tests` |
| 6 完成 | 输出下游接入参数(base URL、app_key、查询端点、curl 示例) | `GET .../configuration-status` |

向导对任何企业应用通用:接入新应用只需要下游按 manifest 契约(见 `docs/api/easyauth-authorization-operations-api-design.md` 的 App Manifest 章节)导出权限目录,不需要在 EasyAuth 侧为单个应用写专用代码。

状态以 URL 参数承载(`app_key` + `step`),刷新或中断后可从任意步骤续接;缺少 `app_key` 时除第一步外自动回落到第一步。

## 界面语言

前端提供 zh-CN / en 两种界面语言,顶栏「中 / EN」切换,选择持久化在 `localStorage` 的 `easyauth.locale`,默认 zh-CN。

- 界面文案消息目录在 `frontend/src/i18n/messages.ts`,zh-CN 为事实源,en 通过 `Record<MessageKey, string>` 在编译期强制键集合一致。
- 权限、权限组、权限范围、授权组等目录数据的英文显示名来自目录双语字段 `name_en` / `description_en`(manifest 可选字段,控制台目录页和 Django admin 均可维护);en 语言下英文字段为空时回落中文主字段。
- 公共权限查询响应形状不变,不包含双语字段;下游展示名以下游本地目录为准。

## 部署口径(S0-Q2)

下游应用(如 EasyTrade)在容器内访问宿主机上的 EasyAuth 时,请求 Host 为 `host.docker.internal`,必须加入 Django `ALLOWED_HOSTS`,否则返回 400 DisallowedHost:

- 环境变量:`DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,host.docker.internal`(`manage.py` 会从 `.env.local` 读取,但**不会覆盖进程环境中已存在的同名变量**)。
- 本机 dev 服务由 launchd 任务 `com.konata.easyauth.dev` 守护(`launchctl submit`,KeepAlive)。该任务的启动命令显式 `export DJANGO_ALLOWED_HOSTS=...`,优先级高于 `.env.local`;调整 allowlist 必须同步更新该任务的提交命令并 `launchctl remove` 后重新 `submit`。
- dev 服务监听 `0.0.0.0:8001`;下游容器内使用 `EASYAUTH_BASE_URL=http://host.docker.internal:8001`。
- 服务端凭据模式当前采用 static token(`Authorization: Bearer eat_...`),由控制台凭据页或接入向导第 4 步签发。
