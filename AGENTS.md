# EasyAuth 项目协作规则

## 文档语言

- 本项目所有文档必须使用中文撰写。
- 文档包括但不限于 `README`、`docs/` 下的架构文档、计划文档、ADR、API 文档、试点接入文档和其他说明性 Markdown/RST/TXT 文件。
- 代码标识符、文件路径、命令、协议名、HTTP 路径、API 字段、错误码、配置键、产品名和不可翻译专有名词可以保留英文。
- 新增或修改文档时，必须先检查是否引入了非必要英文正文；如果引入，必须改为中文。

## 项目硬约束

- 项目尚未上线，默认不保留历史错误形态；遇到错误设计、错误数据模型、错误接口、错误口径或错误流程时，必须正本清源，优先一次性修正 schema、domain、API、frontend、tests、docs 和相关调用方。
- 不得新增兼容代码、兼容分支、兼容字段或兼容转换层；只有明确写入 legacy 白名单、外部系统契约或短期迁移窗口的场景才允许临时兼容，并必须同时写明移除条件。
- 不得使用模拟数据、伪造数据、静默默认值、空结果兜底或绕行逻辑掩盖真实问题；测试中的 mock 必须只服务于隔离外部依赖，不得替代业务事实或隐藏缺陷。
- 违反业务不变量、数据契约或权限边界时必须快速失败，抛出明确错误并修复根因，不得吞异常、降级为成功或继续执行不可信流程。
- 遵从第一性原则，不得为罕见、不可能或未定义场景堆叠投机兜底、静默回退或长期兼容分支。
- 每完成一项工作就单独提交一次 commit（中文提交语），不要攒到最后批量提交；提交后必须重建前端和后端，确认构建命令成功结束。
- 修改 Django 后端代码、Django 模板、React build 产物、Vite manifest 或其他会影响运行中页面响应的文件后，必须重启承载该改动的服务，并用目标 URL 的真实 HTTP 响应或浏览器页面验证新代码已被加载，不能只以本地测试或 build 成功作为完成依据。
- **本机 dev server 不等于上线。** `Dockerfile` 把 `src/`、`manage.py` 和前端构建产物 `COPY` 进镜像，
  所以反代部署（`docker-compose.deploy.yml`，经 frpc 暴露为 `iam.jiefakj.com` → `127.0.0.1:8001`）
  只重启容器不会带上新代码，**必须重建镜像再起**：
  `docker compose -f docker-compose.deploy.yml build web && docker compose -f docker-compose.deploy.yml up -d`。
  web / worker / beat / stream / webhook-worker 共用同一镜像，要一起起——缺 worker 或 beat 会静默丢掉
  目录同步、离职自动化、授权过期回收和 webhook 投递。验证要打公网 URL 的真实响应，不能只看本机 8001。
- 后端测试用仓库 `.venv`：`.venv/bin/pytest`（host 环境可用，2026-08-11 复核 `tests/unit` 827 绿）。
  需要干净环境或 PostgreSQL lane 时才走 Docker：
  `docker run --rm -v "$PWD":/app -w /app ghcr.io/astral-sh/uv:python3.12-bookworm-slim bash -lc "UV_PROJECT_ENVIRONMENT=/opt/venv uv run --frozen --extra dev pytest -q"`——
  少了 `UV_PROJECT_ENVIRONMENT` 会把 host `.venv` 改写成 Linux 布局。
  完整门禁命令见 `docs/operations/quality-gates.md`。
