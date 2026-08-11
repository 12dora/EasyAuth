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
- `docker-compose.deploy.yml`（反代部署）：Celery worker 覆盖镜像默认的 `curl :8001` 探针，
  改用 `celery inspect ping`——worker 不监听 HTTP 端口，沿用默认探针会把活着的 worker 判成不健康。

启动命令见[根 README 的部署章节](../../README.md#生产部署手动)。

## Stream 心跳

`run_dingtalk_stream` 的心跳线程每轮写入运行心跳。缓存短暂不可用时，线程记录异常并在下一轮
继续尝试；缓存失败不会被解释为健康，详细 readiness 会继续按心跳年龄暴露真实不健康状态。
