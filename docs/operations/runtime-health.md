# 运行健康探针

## 目标

运行健康接口分为两层：

- `/health/` 是匿名 liveness，只证明 Django 进程可响应，固定返回整体状态，不包含组件名、
  心跳年龄、调度节奏或依赖拓扑。
- `/health/readiness/` 是详细 readiness，必须通过控制台管理员授权后访问，返回数据库、
  Redis/broker 和后台任务心跳详情。

这个边界避免把内部组件和任务节奏暴露给匿名调用方，同时保留运维排障需要的真实依赖状态。

## 本地数据服务

开发用 `docker-compose.yml` 为 PostgreSQL 和 Redis 定义真实 healthcheck：

- PostgreSQL：`pg_isready -U easyauth -d easyauth`
- Redis：`redis-cli ping`

启动命令示例：

```bash
EASYAUTH_POSTGRES_PASSWORD=<生成> docker compose up -d postgres redis
docker compose ps
```

只有两个服务都显示 `healthy` 后，才继续执行迁移和启动 Django/Celery。

## 运行服务

当前仓库只把 Gunicorn 作为运行依赖锁定：

```bash
.venv/bin/gunicorn easyauth.config.wsgi:application --bind 0.0.0.0:8001 --workers 4
```

ASGI 入口文件仍存在，但没有锁定 Uvicorn 或等价 ASGI server；在补依赖、锁文件和启动探测前，
不要把 ASGI 命令写入部署流程。

## Stream 心跳

`run_dingtalk_stream` 的心跳线程每轮写入运行心跳。缓存短暂不可用时，线程记录异常并在下一轮
继续尝试；缓存失败不会被解释为健康，详细 readiness 会继续按心跳年龄暴露真实不健康状态。
