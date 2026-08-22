# 运行健康探针

## 目标

运行健康接口分为两层：

- `/health/` 是匿名 liveness，只证明 Django 进程可响应，固定返回整体状态，不包含组件名、
  心跳年龄、调度节奏或依赖拓扑。
- `/health/readiness/` 是详细 readiness，必须通过控制台管理员授权后访问，返回数据库、
  Redis/broker 和后台任务心跳详情。

这个边界避免把内部组件和任务节奏暴露给匿名调用方，同时保留运维排障需要的真实依赖状态。

## 依赖服务的 healthcheck

healthcheck 必须探测真实存活，不用 `sleep` 占位。

- `docker-compose.yml`（开发数据存储）：PostgreSQL 用 `pg_isready -U easyauth -d easyauth`，
  Redis 用 `redis-cli ping`。两者都 `healthy` 后再执行迁移和启动应用进程。
- `docker-compose.deploy.yml`（反代部署）：`web` 仍用镜像默认的 `curl :8001/health/`。
  Celery `worker` / `webhook-worker` / `notify-worker` 覆盖该探针。进程在 `worker_ready`
  后于 `127.0.0.1`、端口 `EASYAUTH_WORKER_HEALTH_PORT`（默认 8002）启动一个进程内
  `ThreadingHTTPServer`：`GET /health` 对本 worker 做进程内 self-ping
  （`app.control.ping(destination=[worker_hostname], timeout=2.0)`，hostname 来自
  `worker_ready` 的 sender，例如 `webhooks@<container>`），证明消费循环仍在排空广播
  队列。检查在独立短线程中执行，4 秒未完成则 503；通过则 200
  `{"status":"ok","worker":"<hostname>"}`，失败则 503。Compose 探针与 EasyTrade 相同：
  `python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/health', timeout=5)"`，
  每 30 秒一次（compose `timeout: 10s`，覆盖 4 秒上界）。这样不会为每次探针冷启动完整
  Python/Django/Celery 进程——原先的 `celery inspect ping` 会把空闲 worker 打到
  20–55% CPU。`worker_shutting_down` 只置位无锁标志使 `/health` 立即 503；
  `worker_shutdown` 才关闭该端口。关闭中的容器立即不健康。webhook-worker /
  notify-worker 的入口脚本已放行环回（`iptables -o lo ACCEPT`），探针走 `127.0.0.1`，
  不受出站防火墙影响。

启动命令见[根 README 的部署章节](../../README.md#生产部署手动)。

## Stream 心跳

`run_dingtalk_stream` 的心跳线程每轮写入运行心跳。缓存短暂不可用时，线程记录异常并在下一轮
继续尝试；缓存失败不会被解释为健康，详细 readiness 会继续按心跳年龄暴露真实不健康状态。
