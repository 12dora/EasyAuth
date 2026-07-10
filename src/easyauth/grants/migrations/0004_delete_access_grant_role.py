from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("grants", "0003_access_grant_version_unique"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.DeleteModel(name="AccessGrantRole"),
    ]
