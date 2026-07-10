from __future__ import annotations

from celery import shared_task

from easyauth.applications.dependency_health_checks import run_dependency_health_checks
from easyauth.config.runtime_health import BEAT_WORKER_HEARTBEAT, mark_heartbeat

RUNTIME_HEARTBEAT_TASK_NAME = "easyauth.health.runtime_heartbeat"


@shared_task(name=RUNTIME_HEARTBEAT_TASK_NAME)
def runtime_heartbeat_task() -> None:
    # 只有 beat 成功发布且 worker 成功消费后才更新时间, 因而同时覆盖两者存活性。
    mark_heartbeat(BEAT_WORKER_HEARTBEAT)


@shared_task(name="easyauth.health.run_dependency_health_checks")
def run_dependency_health_checks_task() -> int:
    # 周期性探测上游依赖并写入健康快照, 返回本轮记录的依赖数量。
    return len(run_dependency_health_checks())
