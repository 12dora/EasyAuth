from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, override

from easyauth.access_requests.models import REQUEST_TYPE_GRANT

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App, Permission, Role

type AccessRequestType = Literal["grant", "change", "revoke", "renew"]
type AccessRequestGrantType = Literal["permanent", "timed"]


@dataclass(frozen=True, slots=True)
class AccessRequestSubmissionError(Exception):
    messages: tuple[str, ...]

    @override
    def __str__(self) -> str:
        return "; ".join(self.messages)


@dataclass(frozen=True, slots=True)
class AccessRequestSubmission:
    user: UserMirror
    app: App
    roles: Iterable[Role]
    grant_type: AccessRequestGrantType
    grant_expires_at: datetime | None
    reason: str
    actor_type: str
    actor_id: str
    request_type: AccessRequestType = REQUEST_TYPE_GRANT
    permissions: Iterable[Permission] = ()


AccessRequestInput = AccessRequestSubmission
