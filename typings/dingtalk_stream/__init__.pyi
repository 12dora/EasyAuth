import logging

class Credential:
    client_id: str
    client_secret: str
    def __init__(self, client_id: str, client_secret: str) -> None: ...

class Headers:
    app_id: str | None
    connection_id: str | None
    content_type: str | None
    message_id: str | None
    time: int | None
    topic: str | None
    extensions: dict[str, object]
    event_born_time: int | None
    event_corp_id: str | None
    event_id: str | None
    event_type: str | None
    event_unified_app_id: str | None

class AckMessage:
    STATUS_OK: int
    STATUS_BAD_REQUEST: int
    STATUS_NOT_IMPLEMENT: int
    STATUS_SYSTEM_EXCEPTION: int
    code: int
    headers: Headers
    message: str
    data: dict[str, object]

class EventMessage:
    TYPE: str
    spec_version: str
    type: str
    headers: Headers
    data: dict[str, object]
    extensions: dict[str, object]

class CallbackMessage:
    TYPE: str
    spec_version: str
    type: str
    headers: Headers
    data: dict[str, object]
    extensions: dict[str, object]

class SystemMessage:
    TYPE: str
    TOPIC_DISCONNECT: str
    spec_version: str
    type: str
    headers: Headers
    data: dict[str, object]
    extensions: dict[str, object]

class EventHandler:
    dingtalk_client: DingTalkStreamClient
    logger: logging.Logger
    def pre_start(self) -> None: ...
    async def process(self, event: EventMessage) -> tuple[int, str]: ...
    async def raw_process(self, event_message: EventMessage) -> AckMessage: ...

class CallbackHandler:
    dingtalk_client: DingTalkStreamClient
    logger: logging.Logger
    def pre_start(self) -> None: ...
    async def process(self, message: CallbackMessage) -> tuple[int, str]: ...

class SystemHandler:
    dingtalk_client: DingTalkStreamClient
    logger: logging.Logger
    def pre_start(self) -> None: ...
    async def process(self, message: SystemMessage) -> tuple[int, str]: ...

class DingTalkStreamClient:
    credential: Credential
    def __init__(self, credential: Credential, logger: logging.Logger | None = None) -> None: ...
    def register_all_event_handler(self, handler: EventHandler) -> None: ...
    def register_callback_handler(self, topic: str, handler: CallbackHandler) -> None: ...
    def start_forever(self) -> None: ...
    async def start(self) -> None: ...
