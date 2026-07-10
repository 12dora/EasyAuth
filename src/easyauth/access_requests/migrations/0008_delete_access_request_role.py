from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("access_requests", "0007_remove_accessrequest_dingtalk_process_instance_id"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.DeleteModel(name="AccessRequestRole"),
    ]
