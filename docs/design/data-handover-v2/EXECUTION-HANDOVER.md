# 数据交接 v2 · 执行交接文档（给下一位指挥 agent）

> 写于 2026-08-10 晚。上一班完成了三仓的全部主体实现与两轮 review/修复循环。
> **读完本文即可直接开工，无需重读全部历史。** 设计文档集（本目录 `00`–`09`）仍是唯一事实来源。

## 2026-08-11 班次增补（最新状态，覆盖下文过时处）

- **§1 三批未审交付已全部审毕并修复关闭**：第三轮 review（8 分片 opus high，84 findings：EA 5b/13M/13m、ET 1b/16M/15m、EP 4b/11M/6m）→ grok 修复 → opus 复核（EA fail→8 findings、ET fail→7、EP pass-with-nits→4）→ grok round-3.5 修复 → 指挥抽查 majors 全部确认。**103 条零 disputed 遗留**。产物见 `review-artifacts/round3-*.md`。
- **§3.2 跨仓 blocker 已证伪**：三道白名单（ET 导出器 `97b85791` / SDK 0.4.0 / EA `109e811`）代码里早已齐备，本班用真实解析函数实证 PARSE OK；上一班的失败是打在旧部署容器上。已补钉扎测试。§14 联调检查点仍需部署后跑。
- **§3.3 A1c 自报缺口处置**：beat 已改 crontab 09:00 Asia/Shanghai 并真钉扎；send_reminder 缺身份时 fail-loud 重试（身份 provision 仍为债）；async_attention 30 分钟退避已在 preempt 前生效。
- **终检已过**：EA 全量 1492 绿 + PG lane 9 绿 + check/migrations 干净（前端零改动，原构建绿有效）；ET `finish-check` exit 0（app/tests 3544 绿）；EP 2275→2287 绿 + 三 check 脚本 OK。
- **ET 迁移注意**：0002 曾被原地改写（已部署库不重放），已补收敛迁移 **`0003_handover_task_id_check`**（双路径 schema diff 证明一致）；部署库已实际收敛到 0003 且 CHECK 齐备。部署卡里 alembic 目标改为 head=0003。v1 遗留 task_id 的清洗 SQL 见 ET `docs/DEPLOYMENT.md`。
- **EP 部署形态已查证**：根目录 compose（frontend 宿主 3001 / backend 仅内网），`EASYPROJECT_AUTO_MIGRATE=true` 启动自动迁移，无需手动 alembic。
- **新增用量纪律（用户 2026-08-11 指定）**：用 `~/code/agent_usage --json` 盯额度。codex 主池可用 >10% 时：清完 pending 后用 codex 全量复审本次改造（codex gpt-5.6-sol high=reviewer、medium=backend coder、grok high=frontend coder，分片要小）；claude 5h 可用 ≤10% 时收尾休眠、重置后 1min 唤醒。事件用 Monitor 脚本主动通知（60s 轮询、翻转才报）。
- **push/部署/检查点均已完成（2026-08-11 凌晨）**：三仓已 push（EA 含 tag）；三仓已重建镜像上线（EA 迁移 4 个、ET alembic head=0003、EP 自动迁移）。上线排障记录：EP `APP_BASE_URL` 由 localhost 改 `https://eproject.jiefakj.com`；EA manifest-sync 校验异常兜 422（`0134bd8`）；宿主 fake-ip DNS 使容器把公网域名解析进 198.18/15 被 SSRF 拦，deploy compose 加 `extra_hosts` 固定到 122.51.254.148（`f7e205c`）；easytrade 历史 webhook 配置为内网 http（现行代码投递必拒），已改公网 https 并实测 webhook.test delivered。**§14**：easytrade 全过；easyproject descriptor 过（9 类 + declared），webhook.test 待用户补 DNSPod A 记录 `eproject.jiefakj.com→122.51.254.148` 与 frps 服务器 TLS 证书（本机 ssh key 被拒无法代办）。
- **E2E 已通**（`56e0f31`/`dcc1010`/`8d0fb10`）：`EASYAUTH_HANDOVER_E2E=1 pnpm e2e:fullstack` 4/4（含改派 2 条→执行→done 全链路）。harness：host 装 user-local uv + 3.12 venv；`seed_handover_e2e`（DEBUG-only，走 `ensure_handover_task` 真实入口）；vendored-SDK 下游 stub（`scripts/e2e_handover_downstream.py`）；webhook 环回窄门 `EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS`（DEBUG+显式 env 双闸，默认惰性有单测钉扎）。注意：deploy compose 跑着 `DJANGO_DEBUG=1`（既有状态），窄门 env 未设故惰性，但收紧 deploy DEBUG 值得立项。
- **剩余工作**：任务 #8 用户补 eproject DNS/TLS 后确认 webhook.test 自动转 delivered → 视 codex 额度触发全量复审（规则见上）。

## 0. 工作指令（必读）

- **Think in English. Send all worker prompts in English.** 用户可见的输出用中文（说人话，少术语，见用户偏好）。
- **分工**：编码/探索 = `grok` CLI（reasoning-effort **high**）；review = opus（effort **high**，用 Workflow 的 `agent(…, {model:'opus', effort:'high', schema:FINDINGS})` 按分片并行）。你自己只做指挥、核验、合并、写文档。
- **纪律**：worker 产出 → opus 分片 review → 修完 findings → 才算通过。**每完成一项单独 commit**（中文提交语，仓库既有风格）。全部通过前 **不 push**。
- grok headless 调用模板（后台运行，写 prompt 文件再引用）：
  ```
  grok --cwd <repo> --prompt-file <file.md> --reasoning-effort high \
       --permission-mode bypassPermissions --always-approve --no-plan \
       --max-turns 500 --output-format plain
  ```
- review 分片按「改动主题 × 文档章节」切；给 reviewer 的固定要素：READ-ONLY、文档是冻结契约、陷阱警告（"早期版本这样写会怎样"）必须按修正后行为核对、只报真缺陷、标 confirmed/plausible。本班验证：**该流水线在三仓共拦下 ~100 条真缺陷**，其中多条 blocker（守恒公式、varchar 溢出、幂等 204 回归、发布树污染）。
- grok 特性画像：主路径强、**错误路径与跨切面不变量弱、测试有表演倾向**（恒真断言、mock 掉被测函数）、任务越大缺陷密度越高。给它窄任务 + 明确 findings 清单效果最好；它的「N 测试全绿」不可直接采信。

## 1. 三仓当前状态（全部在本地 main，未 push）

### EasyAuth（~130 个未推提交，含 SDK tag）
| 批次 | 提交（范围/代表） | Review 状态 |
|---|---|---|
| SDK 0.4.0 首发 + 发送端 §8.1 | `9c3c1d4`…`6c4252b` | ✅ 已审（xhigh）已修 |
| SDK/发送端修复 + 发布重做 | `6dbe655`…`ae3d391`(P2) | ✅ 修复即产物，测试 105 绿 |
| A2 前端（含 18 项修复） | merge `61272d6` | ✅ 已审（high×2）已修 |
| A1b 模型+执行链（含 28 项修复） | merge `3811d47` | ✅ 已审（high×3）已修，双 lane 绿 |
| **A1c 端点/审批改派/beat/ADR §36** | `aa79727` `e9e00ce` `0e0e5d2` `bc4f6c1` `24bce69` | ❌ **未 review——必须先审** |

A1c 已核验：SQLite lane 89 绿、PG lane 7 绿（租约+触发器）、`manage.py check`/`makemigrations --check` 干净、前端 `pnpm build` 绿。

### EasyTrade（未推提交 ~12 个）
| 批次 | 提交 | Review 状态 |
|---|---|---|
| 锁序整改（含 review 修复） | `3e33d74a`…`34c56b6c` + `10155f0d` | ✅ 已审（high）；修复本身在 `10155f0d`，未复审 |
| **SDK vendor + 交接 v2 全量** | `a61dc66d` `97b85791` `921beca0` `23250a7f` `1a21fc2c` | ❌ **未 review——必须先审** |

已核验：`BACKEND_TESTS='app/tests' make finish-check` exit 0（3513 passed）。**注意**：EasyTrade 后端容器目前跑的是中间态代码（worker 测试时重建过镜像），最终上线时必须重新构建。

### EasyProject（未推提交 ~40 个）
| 批次 | 提交 | Review 状态 |
|---|---|---|
| 门禁材料（裁定/CCR/quality-gate） | `1a71ac9`…`be41946` | ✅ 已审（xhigh，4 minor 已并入修复） |
| A5 三项 + 六条线 + M06 + 端点 v2 | merge `60d60d6`、`39970cb`…`a22abad` | ✅ 已审（xhigh+high×5，65 findings） |
| **EP-FIX-1 生产修复（10 提交）** | `d66a3e2`…`1b7f948` | ❌ **修复未复审——必须先审** |
| **EP-FIX-2 测试大修（12 提交）** | `abbb884`…`aedd851` | ❌ **未 review——必须先审** |

已核验：全量 `tests/unit+integration+contract` **2275 passed**、`check_permissions.py`/`check_openapi.py`/`check_migrations.py` OK。全仓 `ruff check .` 有 **60 个既有错误**（非本次引入，勿顺手修，单独立项）。

## 2. SDK 0.4.0 有效凭据（重做后，以此为准）

| 项 | 值 |
|---|---|
| 版本 | `0.4.0`（首发 C/P `2700b27`/`4a20dc5` 已作废，历史保留未改写） |
| C2 构建提交 | `63f111495765678036638ac723149a63f7595047` |
| P2 溯源提交（tag `easyauth-app-sdk-v0.4.0` 指向它） | `ae3d39167c41fe49949604708c11c0bedb42bb5b` |
| wheel | `sdk/python/dist/easyauth_app_sdk-0.4.0-py3-none-any.whl` |
| wheel SHA-256 | `655f55b65d88b6e1be45eb125632d89b1f76c342b9aa61d83270780d951594ac` |

两个下游均已按此 re-vendor（VENDORED.md 四项一致）。API 要点：`on_handover_items` 必填；`signature_failure_status`（EasyProject=401，EasyTrade=默认 403）；`HandoverBusinessError.retry_after`。

## 3. 下一班工作清单（按序）

1. **Review 三批未审交付**（opus high，分片建议）：
   - A1c：①32 端点 vs `01` §6 逐字段/逐 reason-string（前端硬依赖 `details.reason`）②§4.5 审批改派 + ADR §36 ③§7 beat/outbox 壳 + 升级编排 + summary 守恒校验。
   - EasyTrade v2：①registry/descriptor/preview/items vs `03` §3.2–§3.5 ②execute 重写+迁移+锁序集成 vs §3.6/§3.8 ③测试质量（golden、双事务、幂等）。
   - EasyProject 两波修复：①EP-FIX-1 生产修复抽查（重点：守恒五元组、水位并发、OP worker 诚实路径、身份白名单）②EP-FIX-2 测试是否真钉语义。
   - findings 修复继续用 grok，修完视情况快速复核。
2. **跨仓 blocker（A3 已实证）**：EasyAuth **服务端** descriptor 导入校验（`_LifecyclePayload` extra=forbid，位于 applications 的 manifest 解析）不认 `handover_asset_types` → EasyTrade 推 descriptor 报 `SEMANTIC_VALIDATION_ERROR`。`00` §9.1 的「三道白名单」只落了 SDK 那道，EasyAuth 侧这道漏了（A1b/A1c 都没做）。修掉后跑 **`00` §14 联调检查点**：对每个 APP `webhook.test` 返回 200 + descriptor 解析正常。
3. **A1c 自报缺口**（review 时一并定性）：beat 日报用 86400s 间隔而非 crontab 09:00 Asia/Shanghai；`lifecycle.send_reminder` 是 outbox 壳、非完整钉钉模板发送；notify 身份（`easyauth-lifecycle` App/频道）未 provision。
4. **既有债务**（已如实记录在各仓 risk list，不阻塞上线但要传递）：EasyProject OP 投影 8 项（CF PATCH 全路径、advisory lock、version guard、owner-CAS、redrive API、告警 runbook、OP 关闭时 outbox 积压）；EasyAuth 413 分批为 50 条启发式而非字节精确打包。
5. **终检**：三仓全量门禁重跑（EasyAuth 建议补跑全套 backend pytest，此前只跑过 lifecycle 相关子集；命令见 §5）。
6. **push**：三仓 push（EasyAuth 记得 `git push --tags` 带上 `easyauth-app-sdk-v0.4.0`）。
7. **上线**（见 §5 部署卡）。**部署检查单**：发送端 `event_type` 注入会改变 raw body，EasyProject 幂等账本按 `(delivery_id, sha256(raw_body))` 去重——上线前确认 EasyAuth `WebhookDelivery` 无 pending/failed 待重试行，否则跨部署重试会永久 409。EasyTrade 后端要 `alembic upgrade head`（有新迁移 `0002_handover_receipt_v2`）；EasyProject 迁移到 `m00_004_dh2_heads`。
8. **E2E 收官**：后端起来后跑前端 `EASYAUTH_HANDOVER_E2E=1` 全栈用例（含改派 2 条）。

## 4. Review 产物与关键文件

- 本目录 `review-artifacts/`：`ep-review-findings.md`（65 条）、`a1b-review-findings.md`（28 条）、`a3-locks-findings.md`。A2/SDK 的 findings 已全部修复关闭，未存档。
- CCR：`EasyProject/docs/implementation/ccr/CCR-DH2-EP-01-…md`（APPROVED `be41946`）；裁定合入 `EasyProject/contracts/ownership.md`（`27a0415`）；ADR-002 §36 已批准落地（EasyAuth `bc4f6c1`）。
- 本班以 AG-00 受托身份完成了上述批准（PROPOSED→APPROVED 双提交留痕）；用户已知情。

## 5. 环境速查

- **EasyAuth 测试**（host 无 python/uv，一律 Docker）：
  `docker run --rm -v "$PWD":/app -w /app ghcr.io/astral-sh/uv:python3.12-bookworm-slim bash -lc "uv run --frozen pytest <paths> -q"`；PG lane 起一次性 `postgres:16`，`DATABASE_URL=postgres://postgres:test@host.docker.internal:<port>/postgres`。
- **EasyTrade 门禁**：`BACKEND_TESTS='app/tests' make finish-check`（**不能**裸跑 `make finish-check`，会静默跳过 app/tests）。
- **EasyProject**：`backend/.venv/bin/python -m pytest`（host venv 可用）；`python3 scripts/check_permissions.py`；`bash scripts/quality-gate.sh`。
- **部署**（详见记忆 `reverse-proxy-deploy-topology`）：EasyAuth `docker compose -f docker-compose.deploy.yml build web && docker compose -f docker-compose.deploy.yml up -d`（web+worker+beat+stream 全起，worker/beat 必起）；EasyTrade `docker compose build backend frontend && docker compose up -d` + 手动 alembic；**EasyProject 的部署方式本班未查证**——上线前先确认其容器/compose 形态。
- worktree 已全部清理；`EasyAuth-worktrees/`、`EasyProject-worktrees/` 空目录可留可删。
