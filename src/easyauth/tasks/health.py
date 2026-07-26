from __future__ import annotations

from celery import shared_task

from easyauth.applications.dependency_health_checks import run_dependency_health_checks
from easyauth.config.data_retention import run_retention_cleanup
from easyauth.config.runtime_health import BEAT_WORKER_HEARTBEAT, mark_heartbeat

RUNTIME_HEARTBEAT_TASK_NAME = "easyauth.health.runtime_heartbeat"
DATA_RETENTION_CLEANUP_TASK_NAME = "easyauth.health.data_retention_cleanup"


@shared_task(name=RUNTIME_HEARTBEAT_TASK_NAME)
def runtime_heartbeat_task() -> None:
    # 只有 beat 成功发布且 worker 成功消费后才更新时间, 因而同时覆盖两者存活性。
    mark_heartbeat(BEAT_WORKER_HEARTBEAT)


@shared_task(name="easyauth.health.run_dependency_health_checks")
def run_dependency_health_checks_task() -> int:
    # 周期性探测上游依赖并写入健康快照, 返回本轮记录的依赖数量。
    return len(run_dependency_health_checks())


@shared_task(name=DATA_RETENTION_CLEANUP_TASK_NAME)
def data_retention_cleanup_task() -> dict[str, int]:
    # 保留矩阵自动执行入口: 有界批次, 返回每类数据集本轮处理数量。
    return run_retention_cleanup().as_dict()
