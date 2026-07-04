# 本地超级管理员登录(/auth/local/)

不依赖 Authentik 的兜底登录通道:密码 + 二次验证(TOTP 验证器 / 通行密钥),
验证通过后以 `local-admin:<username>` 为 subject 绑定会话,groups 取
`EASYAUTH_CONSOLE_SUPERUSER_GROUPS`,因此直接是 console 超管。

## 入口

| 页面 | URL |
| --- | --- |
| 登录 | `/auth/local/` |
| 二次验证 | `/auth/local/verify/`(登录后自动跳转,pending 10 分钟有效) |
| 修改密码 | `/auth/local/change-password/`(仅本地管理员会话可用,匿名访问跳回登录页) |
| 安全设置(绑定/停用 2FA、修改密码) | `/auth/local/security/`(仅本地管理员会话可见,其余 404) |

登出复用统一的 `POST /auth/logout/`。

## 创建账号

```bash
uv run python manage.py create_local_admin <username>            # 交互式输入密码
uv run python manage.py create_local_admin <username> --password '<pwd>'
uv run python manage.py create_local_admin <username> --update --password '<pwd>'  # 重置已有账号密码
uv run python manage.py create_local_admin <username> --password '<pwd>' --no-force-password-change  # 不强制下次登录改密
```

用户名只允许小写字母、数字、连字符、下划线。账号已存在且未加 `--update` 时报错(幂等保护)。

本地开发约定的默认账号是 `admin` / `admin123`:

```bash
DJANGO_DEBUG=1 .venv/bin/python manage.py create_local_admin admin --password admin123
```

## 强制修改密码

- 新建账号与 `--update` 重置密码后,账号都会带上 `must_change_password` 标记;
  加 `--no-force-password-change` 可以显式关闭。
- 带该标记的本地管理员登录后,除改密页(`/auth/local/change-password/`)、登出链路
  (`/auth/logout/`、`/auth/logged-out/`)和静态资源外,访问任何页面(含 `/portal/`、
  `/console/` 及其 API)都会被 302 到改密页;设置新密码后标记清除,恢复正常访问。
- 改密要求:当前密码正确、新密码至少 8 位、不能与当前密码相同、两次输入一致。
- 平时也可以在 `/auth/local/security/` 安全设置页的「修改密码」区块自助改密。

## 绑定二次验证

1. 用密码登录(账号还没有任何二次验证方式时直接进入 console)。
2. 打开 `/auth/local/security/`:
   - TOTP:「开始绑定验证器」→ 用验证器应用扫码(或手动输入密钥)→ 回填 6 位验证码确认启用。
     停用需再输入一次当前有效验证码。
   - 通行密钥:填写名称(可选)→「注册通行密钥」→ 完成浏览器指纹/面容/安全密钥流程。
3. 绑定任一方式后,下次登录密码通过后会进入二次验证页;两种方式都绑定时可切换。

## WebAuthn / RP ID 注意事项

- 配置项(`config/settings/base.py`,均可用环境变量覆盖):
  - `EASYAUTH_WEBAUTHN_RP_ID`(默认 `localhost`):必须是**域名**,不含协议与端口。
  - `EASYAUTH_WEBAUTHN_RP_NAME`(默认 `EasyAuth`)。
  - `EASYAUTH_WEBAUTHN_ORIGINS`(默认 `http://localhost:8001`,逗号分隔):必须与浏览器地址栏完全一致。
- **浏览器必须用 `http://localhost:8001` 访问**;`127.0.0.1` 不属于 RP ID `localhost`,
  通行密钥注册/验证会直接失败(TOTP 不受影响)。

## 安全与审计

- 登录失败按用户名节流(5 次 / 5 分钟,含二次验证失败与改密时当前密码错误)。
- 审计事件(append-only,actor_type=`local_admin`):`admin_local_login_succeeded` /
  `admin_local_login_failed` / `admin_local_second_factor_failed` / `admin_local_totp_enabled` /
  `admin_local_totp_disabled` / `admin_local_passkey_registered` / `admin_local_passkey_removed` /
  `admin_local_password_changed` / `admin_local_password_change_failed`。
