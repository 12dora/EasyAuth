# 质量门禁

## CI 作业

`.github/workflows/docker-build.yml` 定义 6 个必过作业，全部通过后才构建、多架构发布、
Cosign 签名并验证镜像（打 `v*.*.*` tag 时还会创建 GitHub Release）。发布**不会**绕过质量作业。

| 作业 | 覆盖 |
| --- | --- |
| 后端 SQLite 隔离套件 | 构建前端产物 → 断言测试库确实是 SQLite → `manage.py check` → `makemigrations --check --dry-run` → 主 pytest |
| PostgreSQL 多连接与 Redis/broker 套件 | 真实 PG 16 + Redis 7 服务；断言 vendor → 迁移回放 → 通知配额并发、outbox、连接器 dispatch、运行健康 |
| SDK 与 FastAPI 全功能套件 | 以 `.[fastapi]` 安装后跑全量 SDK 测试，并**禁止出现 skip**（防止可选依赖缺失被当成通过） |
| Ruff 与 BasedPyright | 静态检查 |
| 前端 | typecheck → vitest → 生产构建（含分包预算） |
| Playwright 真实全栈冒烟 | 真实构建产物 + 真实 Django + 真实 SQLite，**不 mock EasyAuth 自身 API** |

后两类作业是刻意分开的：普通 Playwright 套件大量 mock 自身 API，只能算 UI/布局冒烟；
只有 `e2e:fullstack` 能证明前后端闭环。

## 静态检查边界

- `ruff check .` 覆盖仓库内 Python 代码和测试；迁移目录按生成代码处理，不参与风格检查。
- `basedpyright` 覆盖生产运行时代码 `src/easyauth`，保持 `typeCheckingMode = "all"`。

排除项只有两个：

- `src/easyauth/**/migrations/**` —— 迁移正确性由迁移回放和漂移检查验证，不由类型门禁替代；
- `src/easyauth/config/settings/deploy.py` —— 用户明确排除的反代部署路径。该排除只表示范围
  边界，**不代表**这条部署路径通过验收或可以上线。

不得通过降低 `typeCheckingMode`、排除普通生产模块、加宽泛 `noqa` 或扩大 `per-file-ignores`
制造绿色。静态检查失败时修根因。

## 复杂度与体积棘轮

Ruff `C901` / `PLR0911` / `PLR0912` / `PLR0913` / `PLR0915` 使用显式阈值
complexity=10、returns=6、branches=12、args=5、statements=50。
现网生产代码在这些阈值下为 0 违规（9 处 PLR0913 与 1 处 PLR0911 为例外,
清单见 `scripts/ruff-noqa-baseline.txt`, 只允许变短）。

文件/函数长度不走 Ruff：

- 后端 `tests/unit/config/test_code_quality.py`：`src/easyauth` 文件 >600 行、
  函数 >60 行必须出现在 baseline, 且实测值不得上升。
- 前端 `src/codeQuality.test.ts`：文件 >500 行、函数/组件 >120 行、
  hook 的 useState+useEffect >8、顶层 import >25 同上。

禁止用加宽 `per-file-ignores`、全局 ignore C901、或删 baseline 行来制造绿色。
新代码必须落在硬帽以内；旧债只许还、不许借。

当前棘轮存量（2026-09-13 实测, 后端对照 git HEAD）：

| 侧 | 帽 | 存量 |
| --- | --- | --- |
| 后端文件 | 600 | 2（最大 619 `grants/query.py`） |
| 后端函数 | 60 | 8（最大 90 `Command.handle`） |
| 后端 C901 | 10 | 0 超标 |
| 前端文件 | 500 | 3（最大 807 `AppTable.tsx`） |
| 前端函数 | 120 | 30（最大 274 `WebhookTab`） |
| 前端 hook se | 8 | 2（最大 14） |
| 前端 import | 25 | 0（最大 23） |

## 测试约定

- 业务回归由 pytest 执行；测试代码的导入、临时路径和危险调用由 Ruff 检查。
- 需要临时文件或目录时使用 `tmp_path` / `tmp_path_factory`，不写固定系统临时路径。
- mock 只用于隔离外部依赖，**不得替代业务事实或掩盖缺陷**。

## 本地等价命令

Vite manifest 与 `src/easyauth/static/` 产物不入库，而 React shell 集成测试和 `manage.py check`
都依赖它们，所以先构建前端再跑后端测试。未配置 `.env.local` 时，`manage.py` 需要显式指定
测试配置模块（否则 `base` 会因缺少 `DJANGO_SECRET_KEY` 而拒绝启动）。

```bash
pnpm --filter @easyauth/frontend build
DJANGO_SETTINGS_MODULE=easyauth.config.settings.test .venv/bin/python manage.py check
DJANGO_SETTINGS_MODULE=easyauth.config.settings.test .venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/pytest
.venv/bin/pytest tests/unit/config/test_code_quality.py tests/unit/config/test_ruff_noqa_baseline.py
.venv/bin/ruff check .
.venv/bin/basedpyright
pnpm --filter @easyauth/frontend test
pnpm --filter @easyauth/frontend test src/codeQuality.test.ts
pnpm --filter @easyauth/frontend e2e:fullstack
```
