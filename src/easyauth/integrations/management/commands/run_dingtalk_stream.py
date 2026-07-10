from __future__ import annotations

import threading
from typing import Final, final, override

from django.core.management.base import BaseCommand, CommandError

from easyauth.config.runtime_health import STREAM_PROCESS_HEARTBEAT, mark_heartbeat
from easyauth.integrations.dingtalk.api_client import DingTalkNotConfiguredError
from easyauth.integrations.dingtalk.stream import build_stream_client

STREAM_HEARTBEAT_INTERVAL_SECONDS: Final = 15.0


@final
class Command(BaseCommand):
    help = (
        "以钉钉 Stream 模式常驻消费事件推送: 通讯录入离职/部门变更触发目录快速同步, "
        "审批实例变更实时推进审批状态。"
    )

    @override
    def handle(self, *args: object, **options: object) -> None:
        try:
            client = build_stream_client()
        except DingTalkNotConfiguredError as error:
            # 凭证未配置时快速失败: 常驻进程静默空转比崩溃更难发现。
            raise CommandError(str(error)) from error
        self.stdout.write("钉钉 Stream 消费进程启动, 等待事件推送……")
        stop = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat_loop,
            args=(stop,),
            name="easyauth-stream-heartbeat",
            daemon=True,
        )
        heartbeat.start()
        try:
            client.start_forever()
        finally:
            stop.set()
            heartbeat.join(timeout=STREAM_HEARTBEAT_INTERVAL_SECONDS)


def _heartbeat_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        mark_heartbeat(STREAM_PROCESS_HEARTBEAT)
        _ = stop.wait(STREAM_HEARTBEAT_INTERVAL_SECONDS)
