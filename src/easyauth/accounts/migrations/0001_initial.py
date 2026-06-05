from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    initial: ClassVar[bool | None] = True

    dependencies: ClassVar[Sequence[tuple[str, str]]] = []

    operations: ClassVar[Sequence[Operation]] = [
        migrations.CreateModel(
            name="UserMirror",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("authentik_user_id", models.CharField(max_length=128, unique=True)),
                ("name", models.CharField(blank=True, max_length=128)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("department", models.CharField(blank=True, max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "active"),
                            ("disabled", "disabled"),
                            ("departed", "departed"),
                        ],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("dingtalk_union_id", models.CharField(blank=True, max_length=128)),
                ("dingtalk_userid", models.CharField(blank=True, max_length=128)),
                ("dingtalk_corp_id", models.CharField(blank=True, max_length=128)),
                ("employee_number", models.CharField(blank=True, max_length=64)),
                ("manager_userid", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["authentik_user_id"],
            },
        ),
    ]
