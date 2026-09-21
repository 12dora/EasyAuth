from __future__ import annotations

import logging
import signal
import threading
from typing import TYPE_CHECKING, Final, final, override

from django.core.management.base import BaseCommand, CommandError

from easyauth.config.runtime_health import STREAM_PROCESS_HEARTBEAT, mark_heartbeat
from easyauth.integrations.dingtalk.api_client import DingTalkNotConfiguredError
from easyauth.integrations.dingtalk.stream import build_stream_client
from easyauth.integrations.dingtalk.stream_runner import (
    bind_stream_session,
    run_supervised_stream,
    supervisor_hooks_from_event,
)
from easyauth.usage.enforcement import stream_should_run
from easyauth.usage.recorder import record_and_check

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import FrameType

STREAM_HEARTBEAT_INTERVAL_SECONDS: Final = 15.0
LOGGER = logging.getLogger(__name__)


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
            target=heartbeat_loop,
            args=(stop,),
            name="easyauth-stream-heartbeat",
            daemon=True,
        )
        heartbeat.start()
        previous_int = signal.getsignal(signal.SIGINT)
        previous_term = signal.getsignal(signal.SIGTERM)
        try:
            _install_shutdown_signals(stop)
            run_supervised_stream(
                bind_stream_session(
                    client,
                    stream_should_run=stream_should_run,
                    record_stream_open=record_stream_open,
                    should_stop=stop.is_set,
                ),
                supervisor_hooks_from_event(stop, stream_should_run=stream_should_run),
            )
        except KeyboardInterrupt:
            LOGGER.info("钉钉 Stream 消费进程收到中断, 正在退出")
        finally:
            _ = signal.signal(signal.SIGINT, previous_int)
            _ = signal.signal(signal.SIGTERM, previous_term)
            stop.set()
            heartbeat.join(timeout=STREAM_HEARTBEAT_INTERVAL_SECONDS)


def record_stream_open() -> None:
    record_and_check("stream_open")


def heartbeat_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            mark_heartbeat(STREAM_PROCESS_HEARTBEAT)
        except Exception:
            LOGGER.exception("钉钉 Stream 心跳写入失败, 将在下一轮继续尝试")
        _ = stop.wait(STREAM_HEARTBEAT_INTERVAL_SECONDS)


def stop_only_signal_handler(stop: threading.Event) -> Callable[[int, FrameType | None], None]:
    def handle(signum: int, frame: FrameType | None) -> None:
        # 只置位停止事件, 禁止在 asyncio.run 之前 raise KeyboardInterrupt。
        del signum, frame
        stop.set()

    return handle


def _install_shutdown_signals(stop: threading.Event) -> None:
    handle = stop_only_signal_handler(stop)
    _ = signal.signal(signal.SIGINT, handle)
    _ = signal.signal(signal.SIGTERM, handle)
