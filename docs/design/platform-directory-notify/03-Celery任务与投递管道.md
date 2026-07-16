# Celery 任务与投递管道设计（统一钉钉通知）

> 第 3 篇。数据模型见第 2 篇；钉钉侧 API/频控事实与出处见第 4 篇。

## 0. 结论先行：复用 outbox 入队，参照 webhooks 骨架新建管道，不改造 webhooks

对现状的核实结论（这决定了「复用还是并列」）：

1. **outbox 是通用事务性任务发件箱，不是 webhook 专用**。
   `outbox.services.enqueue_task(event_key, task_name, args, kwargs, countdown)`
   （`src/easyauth/outbox/services.py:47`）已被 connectors、lifecycle、dingtalk stream、
   webhooks 四个模块共用；它只保证「业务事务提交后，至少一次把 Celery 任务发布到
   broker」（beat 每 5s 扫描 `easyauth.outbox.dispatch_pending`，指数退避 5s→300s，
   无死信——发布层不需要死信）。**通知管道直接复用它做入队**，获得
   「API 落库与投递排程原子一致」的性质，不自造扫描器。
2. **webhooks 的 transport 不可插拔**。`webhooks/transport.py` 是写死的
   HTTPS 出站客户端（`post_webhook`/`_PinnedHttpsConnection`），没有 transport
   抽象、注册表或 channel 字段；`WebhookDelivery` 模型语义（target_url、HMAC 签名、
   allowed_hosts）与钉钉工作通知（batch userid、agent_id、task_id 回执）完全不同。
   **强行塞一个 "DingTalk transport" 进 webhooks 是错误的抽象**——两者唯一的共性
   （claim/lease/attempts/重试计划/耗尽死信）是模式而非代码，值得照抄的是骨架设计。
3. 因此整体形态：**新建 `easyauth/notify` 模块 + `easyauth/tasks/notify.py` 任务，
   与 webhooks 并列；两者都经 outbox 入队**。

```
POST /api/v1/apps/{k}/notify/messages
        │ (同一 DB 事务)
        ▼
NotifyMessage(pending) + NotifyRecipient×N 落库
        │ enqueue_task(event_key="notify-delivery:{message_id}:1",
        │              task_name="easyauth.notify.deliver_message",
        │              args=[message_id, 1])          ← 事务内写 outbox
        ▼ 事务提交, API 返回 202
outbox 扫描(≤5s) ──▶ broker ──▶ deliver_message task
        │ 抢租约(claim_token+lease) → 取 pending/throttled 收件人
        │ 按 100/批 调 DingTalkApiClient.send_work_notification()
        ▼
成功批: recipients → sent(+task_id)     失败批: 按错误分类 → 重试排程/终态
        │
        ▼ (beat, 60s)
easyauth.notify.reconcile_send_results ──▶ getsendprogress/getsendresult
        │
        ▼
sent → delivered / failed(DINGTALK_REJECTED), 刷新消息聚合状态
```

---

## 1. 任务划分

| 任务名 | 触发方式 | 职责 |
|---|---|---|
| `easyauth.notify.deliver_message` | outbox 入队（API 受理时 + 重试排程时） | 单条消息的一轮投递：抢租约 → 分批调钉钉 → 推进收件人状态 → 排程下一轮或收敛终态 |
| `easyauth.notify.reconcile_send_results` | beat，每 60s（`EASYAUTH_NOTIFY_RECONCILE_SECONDS`） | 对 `sent` 收件人按 task_id 查钉钉投递回执，升级为 delivered / failed |
| `easyauth.notify.prune_messages` | beat，每 86400s（`EASYAUTH_NOTIFY_PRUNE_SECONDS`） | 按保留期（默认 180 天）删除历史消息与收件人行 |

任务模块放 `src/easyauth/tasks/notify.py`（对齐 `tasks/webhooks.py` 惯例），登记到
`CELERY_IMPORTS`；`deliver_message` 路由到独立队列 `notify`
（`CELERY_TASK_ROUTES` 仿 `easyauth.webhooks.deliver` → `webhooks` 的做法），
防止通知洪峰阻塞授权撤销等关键任务。

```python
@shared_task(
    name="easyauth.notify.deliver_message",
    acks_late=True,
    soft_time_limit=25,   # 5 批 × (钉钉 5s 超时) + 余量
    time_limit=30,
)
def deliver_message_task(message_id: str, generation: int) -> None: ...
```

超时口径：单轮最多处理 `NOTIFY_MAX_CHUNKS_PER_RUN = 5` 批（500 收件人）；
更大的消息由本轮结束时的「继续排程」消化（见 §3），避免任务超 time_limit 被硬杀。

## 2. 幂等设计（三层）

| 层 | 机制 | 对齐的现有实现 |
|---|---|---|
| API 受理 | `(app, dedup_key)` DB 部分唯一约束；命中且 payload_hash 一致 → 返回既有 message_id（HTTP 200），不一致 → 409 | `ApprovalInstance.biz_key` + `payload_hash` |
| outbox 入队 | `event_key = "notify-delivery:{message_id}:{generation}"` 唯一；重复入队被 `get_or_create` 吸收 | `webhook-delivery:{id}:{generation}`（`webhooks/delivery.py:221`） |
| 任务执行 | 消息级 `claim_token` + `lease_expires_at`（45s）条件更新抢占；收件人按状态过滤（只取 pending/throttled），已 sent 的不重发 | `webhooks/delivery.py:228 _claim_delivery` |

**at-least-once 与重复推送**：outbox + acks_late 是至少一次语义。极端情形
（worker 在「钉钉受理成功」与「recipients 落 sent」之间崩溃）会导致该批次重发一次。
接受此代价，理由：(a) 窗口极小；(b) 钉钉官方对「同一应用相同内容发同一用户」有
服务端去重（第 4 篇 §4），重复调用大概率被钉钉自身吸收；(c) 反向选择（at-most-once）
会把崩溃变成静默丢通知，对提醒类业务不可接受。

## 3. 单轮投递算法（`deliver_message`）

```
1. SELECT message FOR UPDATE-免锁抢占: 条件更新
   (status IN (pending, sending)) AND (claim 空 或 lease 过期)
   → 写入新 claim_token, lease=now+45s, attempts+=1, status=sending
   抢不到 → 直接返回(另一执行体在跑, 或已终态)
2. 取 recipients WHERE status IN (pending, throttled) LIMIT 500, 按 100/批分组
3. 从消息冻结的 `AppNotificationChannel` 构造 client，逐批调
   send_work_notification(agent_id, userid_list, msg):
   - 成功(拿到 task_id) → 该批 recipients: status=sent, dingtalk_task_id, sent_at
   - 钉钉频控类错误(errcode 清单见第 4 篇 §4) → 该批 recipients: status=throttled
   - 参数/权限类终态错误 → 该批 recipients: status=failed, error_code=DINGTALK_REJECTED,
     error=errmsg(截断 500 字符)
   - 网络不可用(DingTalkApiUnavailableError) → 本批保持原状态, 中断本轮
4. 收敛判定:
   a. 仍有 pending/throttled 且 attempts < 上限
      → enqueue_task("notify-delivery:{id}:{generation+1}", countdown=退避[attempts])
        (network 失败沿用退避; 纯 throttled 用钉钉限流专用更长退避, 见 §4)
   b. 仍有未终态收件人且 attempts ≥ 上限
      → 残余 recipients: status=failed, error_code=EXHAUSTED; 进入 c
   c. 无 pending/throttled → 按 failed 计数写消息终态
      (completed / partially_failed / failed), completed_at=now, 释放 claim
5. 每轮结束刷新消息的 recipient_sent/recipient_failed 计数与审计(见第 5 篇 §4)
```

要点：

- **重试排程走 outbox 的 countdown**（`available_at = now + countdown`），与
  webhooks 完全同款——重试计划以 DB 的 `attempts` 为准，不依赖 Celery 任务链，
  worker 重启不丢重试。
- **generation 递增**保证每轮的 outbox event_key 唯一，同时旧轮次任务因抢不到
  claim 而自然失效（webhooks 的既有语义）。
- 批内失败不影响其它批（第 3 步逐批独立结算），一条消息里部分人成功部分人频控是
  正常终局（`partially_failed`）。

## 4. 重试策略与死信

```python
NOTIFY_RETRY_DELAYS_SECONDS: Final = (60, 300, 1800, 7200)   # 常规: 1m/5m/30m/2h, 共 5 轮
NOTIFY_THROTTLE_RETRY_SECONDS: Final = 120                   # 命中钉钉 QPM/QPS 频控: 2 分钟后再试
```

- 常规失败（网络抖动、钉钉 5xx）用 4 段递增退避——比 webhooks 的
  `(60,300,1800,7200,21600)` 少最后一段 6h：通知的时效价值随时间衰减，
  超过 ~4h 的任务提醒不如判失败让业务侧走兜底。
- **调用级频控是分钟级窗口**：send 调用直接报错的频控只有 QPS（每应用每接口
  20/s，errcode 90018）与 QPM 人次（143103/143104，每分钟 5000 人次），
  第 4 篇 §4 有官方出处——2 分钟退避即可越过窗口，不需要小时级等待。
- **日额度/重复内容类限制不在 send 调用报错**：143105（单应用对单人 500 条/日）
  与 143106（相同内容同人一天 1 次）是**收件人级静默丢弃**，send 照样返回成功，
  只能在回执对账（§5）中从 `forbidden_list` 发现并标为终态 failed
  （`DINGTALK_DAILY_LIMIT` / `DINGTALK_DUPLICATE`）——重试对它们无意义，不重试。
- **死信 = `failed(EXHAUSTED)` 终态 + 审计事件 `notify_delivery_exhausted`**，
  与 `webhook_delivery_exhausted` 同款。不提供 API 层重投端点（下游用新
  dedup_key 重发即可）；console 运维页提供人工重投（复位 attempts、generation+1
  重新入队，学 `webhooks/delivery.py:198 redeliver`）。

## 5. 回执对账任务（`reconcile_send_results`）

钉钉 asyncsend_v2 是**异步受理**：调用成功仅代表任务排队（返回 task_id），
真正的逐人成败要靠 `getsendprogress` / `getsendresult` 查询（第 4 篇 §2）。

```
每 60s:
1. SELECT DISTINCT dingtalk_task_id FROM notify_recipient
   WHERE status='sent' AND sent_at > now()-24h LIMIT 50
2. 对每个 task_id: getsendprogress(agent_id, task_id)
   - status != 2(处理完毕) → 跳过, 下轮再查
   - 已完成 → getsendresult, 按名单归类该 task_id 下的 sent recipients:
     · invalid_user_id_list / failed_user_id_list → failed(DINGTALK_REJECTED)
     · forbidden_list: code 143106 → failed(DINGTALK_DUPLICATE);
                       code 143105 → failed(DINGTALK_DAILY_LIMIT)
     · 明确出现在 read_user_id_list / unread_user_id_list
       → delivered, delivered_at=now
     · 未出现在任何明确名单
       → 保持 sent，不做送达推断
3. 刷新受影响消息的聚合计数; 若消息因此从 completed 变为 partially_failed, 同步改写
```

- **分批 ≤100 是回执能力的前提**：官方规定接收人超过 100 的任务不支持
  getsendresult（第 4 篇 §2.2）；§3 的 100/批切分正好保证每个 task_id 都可查。
- 官方窗口：发送结果只保留 **24h**、发送进度 **7 天**——对账扫描只看
  `sent_at > now()-24h`。`sent_at` 超过 24h 仍无明确回执时继续保持 `sent`；
  不得因查询窗口结束而乐观收敛为 `delivered`。
- 该任务是**尽力而为的增强**：它挂掉不影响主投递链路，消费方看到的最低保证是
  `sent`（钉钉已受理）。此弱依赖关系写进契约的状态语义（契约 §N4）。
- **API 月配额提示**：标准版（免费版）钉钉组织全部服务端 API 共 5000 次/月且
  工作通知计入（第 4 篇 §4.2）；对账使每条消息的调用数 ×3（send + progress +
  result）。提供 `EASYAUTH_NOTIFY_RECONCILE_ENABLED`（默认 True）开关——若组织
  为标准版且量级吃紧，可关闭对账，状态停留在 `sent`。
  `sent` 是最低可靠保证；`delivered` 只表示钉钉明确 read/unread 回执分类，
  不表示已读、审批知悉或法务送达。

## 6. 保留期清理（`prune_messages`）

每日一次，删除 `created_at < now - EASYAUTH_NOTIFY_RETENTION_DAYS(180)` 的
`NotifyMessage`（级联删 recipients），单次删除分批（每批 500 行）防长事务。
参照 `easyauth.connectors.prune_sync_runs` 的既有先例。

## 7. 与现有基建的接线清单（文件级）

| 位置 | 改动 |
|---|---|
| `src/easyauth/integrations/dingtalk/api_client.py` | 新增 `send_work_notification(...) -> str(task_id)`、`get_send_progress(...)`、`get_send_result(...)` 三个方法。**注意**：工作通知只有旧域名 `oapi.dingtalk.com` 的 topapi 版本（第 4 篇 §1），需在该文件新增 `DINGTALK_OAPI_BASE_URL` 常量与带 `?access_token=` 查询参数的请求分支；access_token 仍复用现有 `/v1.0/oauth2/accessToken` 获取与缓存逻辑（新旧域名通用，第 4 篇 §6）。原「不接旧 topapi」决策（`api_client.py:21` 注释）在此文档化地开例外：仅限工作通知三端点，理由与出处见第 4 篇 §1 |
| `src/easyauth/notify/`（新） | `models.py`（第 2 篇）、`services.py`（受理/解析/投递编排，对应 `webhooks/delivery.py` 的角色）、`apps.py`、`migrations/` |
| `src/easyauth/tasks/notify.py`（新） | 三个 `@shared_task` 定义 |
| `src/easyauth/api/notify_views.py`（新） | 公共 API 视图（契约 §N） |
| `src/easyauth/api/directory_views.py`（新） | 目录视图（契约 §D，纯读，不涉本篇管道） |
| `src/easyauth/config/settings/base.py` | `INSTALLED_APPS` + `CELERY_IMPORTS` + `CELERY_TASK_ROUTES`（notify 队列）+ `CELERY_BEAT_SCHEDULE`（reconcile 60s、prune 86400s）+ 各 `EASYAUTH_NOTIFY_*` 默认值 |
| `src/easyauth/config/celery.py` | 视运维需要把 `easyauth.notify.deliver_message` 加进 `_SUCCESS_HEARTBEATS` 健康心跳映射（可选，建议加） |

## 8. 可观测与告警（简述）

- **指标来源即数据库**：`NotifyMessage.status` / `NotifyRecipient.status`+`error_code`
  的分组计数就是投递大盘（console 运维页直接查询展示；无需引入新指标系统）。
- **告警**（两条,均走现有日志/健康通道）：
  1. `notify_delivery_exhausted` 审计事件伴随 `logger.error`——按现有日志告警管道消费；
  2. 依赖健康：按 App 检查 active `AppNotificationChannel`、密钥与 agent_id；
     不使用全局 `IntegrationSettings` 判定 notify App 可用性。配置缺失在健康快照中亮红，
     且 POST 受理返回 dependency unavailable。
- 失败样本自带上下文：`error_code` + 钉钉 errmsg + `raw_ref`，排障不需要翻日志。
