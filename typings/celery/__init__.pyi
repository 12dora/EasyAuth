from collections.abc import Callable, Sequence
from typing import overload

class Celery:
    def __init__(self, main: str) -> None: ...
    def config_from_object(
        self,
        obj: str,
        silent: bool = False,
        force: bool = False,
        namespace: str | None = None,
    ) -> None: ...
    def autodiscover_tasks(
        self,
        packages: Sequence[str] | None = None,
        related_name: str = "tasks",
        force: bool = False,
    ) -> None: ...

@overload
def shared_task[**P, R](
    func: Callable[P, R],
    *,
    name: str | None = None,
) -> Callable[P, R]: ...
@overload
def shared_task[**P, R](
    *,
    name: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...
