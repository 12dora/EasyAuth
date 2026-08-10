"""数据交接 webhook v2 的 TypedDict 契约(冻结字段名与形状)。

下游 APP 直接 import 这些类型做注解与静态检查, 杜绝字段名手抄出错。
**每个 Request 都含 ``event_type`` 字段**, 取值必须与 ``X-EasyAuth-Event`` 完全一致
(契约 §10.1)。权威 JSON 样本见包内 ``contract_samples/handover_v2/``。
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


class PreviewRequest(TypedDict):
    event_type: str
    task_id: str
    generation: int
    kind: str
    from_user_id: str
    mode: str


class PreviewAsset(TypedDict):
    type: str
    label: str
    count: int


class PreviewResponse(TypedDict):
    snapshot_token: str
    assets: list[PreviewAsset]


class ItemsRequest(TypedDict):
    event_type: str
    task_id: str
    generation: int
    snapshot_token: str
    from_user_id: str
    asset_type: str
    page: int
    page_size: int
    q: str


class ItemsItem(TypedDict):
    id: str
    label: str
    hint: str


class ItemsResponse(TypedDict):
    items: list[ItemsItem]
    page: int
    page_size: int
    total: int
    unfiltered_total: NotRequired[int | None]


class ExecuteOverride(TypedDict):
    id: str
    action: str
    to_user_id: NotRequired[str]


class ExecuteAssignment(TypedDict):
    asset_type: str
    default_action: str
    default_to_user_id: NotRequired[str]
    overrides: list[ExecuteOverride]


class ExecuteRequest(TypedDict):
    event_type: str
    task_id: str
    generation: int
    batch_id: int
    snapshot_token: str
    kind: str
    from_user_id: str
    mode: str
    assignments: list[ExecuteAssignment]


class ExecuteSummaryCounts(TypedDict):
    transferred: int
    released: int
    skipped: int
    merged: int
    failed: int


class ExecuteResponse(TypedDict):
    summary: dict[str, ExecuteSummaryCounts]
