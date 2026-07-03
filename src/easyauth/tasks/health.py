from __future__ import annotations

from celery import shared_task

from easyauth.applications.dependency_health_checks import run_dependency_health_checks


@shared_task(name="easyauth.health.run_dependency_health_checks")
def run_dependency_health_checks_task() -> int:
    # 周期性探测上游依赖并写入健康快照, 返回本轮记录的依赖数量。
    return len(run_dependency_health_checks())
