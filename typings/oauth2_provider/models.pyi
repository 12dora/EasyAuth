from datetime import datetime
from typing import ClassVar

from django.db import models

class Application(models.Model):
    CLIENT_CONFIDENTIAL: ClassVar[str]
    CLIENT_PUBLIC: ClassVar[str]
    GRANT_CLIENT_CREDENTIALS: ClassVar[str]
    id: int
    client_id: str
    client_secret: str
    client_type: str
    authorization_grant_type: str
    name: str
    objects: ClassVar[models.Manager[Application]]


class AccessToken(models.Model):
    id: int
    token: str
    token_checksum: str
    application_id: int | None
    expires: datetime
    objects: ClassVar[models.Manager[AccessToken]]
